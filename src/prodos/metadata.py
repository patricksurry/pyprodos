"""
On-disk directory records, mirroring the ProDOS Technical Reference, Appendix B
(https://prodos8.com/docs/techref/file-organization/).

Glossary
--------
The spec reuses "directory", "entry" and "header" for several different things.
This package uses one name for each idea:

    Volume           Loader blocks + volume bit map + root (volume) directory.  [volume.py]
    Directory        A chain of blocks holding a header and a fixed array of entry
                     slots ("directory file" in the spec).  [directory.py]
    DirectoryHeader  The first record of a directory, where the directory describes
                     itself: VolumeDirectoryHeader for the root (Figure B-3),
                     SubdirectoryHeader for the others (Figure B-4).
    FileEntry        A named slot in a directory that points at storage (Figure B-5).
                     It describes files *and* subdirectories: the entry is how a
                     parent names you, the header is how a directory describes itself.
    Fork             A byte sequence stored as a seedling, sapling or tree.  [file.py]
    File             A FileEntry plus its fork: one for a standard file, or a data
                     fork and a resource fork for a GS/OS extended file.  [file.py]

Back pointers tie these together: a FileEntry's header_pointer is the key block of
the directory containing it, and a SubdirectoryHeader's parent_pointer and
parent_entry_number locate the FileEntry in the parent that names the subdirectory.

storage_type says *how* data is laid out (seedling, sapling, tree, directory, ...);
file_type says *what* it is (text, binary, system, ...).

Figure B-12. Header and Entry Fields

                                                                                 +-------- Write-Enable
                                                                                 |   +---- Read-Enable
                                                                                 |   |
 +--------------+                       +----------+   +-------------------------------+
 | storage_type |                       |  access  | = | D | RN | B | Reserved | W | R |
 |   (4 bits)   |                       | (1 byte) |   +-------------------------------+
 +--------------+                       +----------+     |   |    |
                                                         |   |    +----------------------- Backup
 $0 = inactive file entry                                |   +---------------------------- Rename-Enable
 $1 = seedling file entry                                +-------------------------------- Destroy-Enable
 $2 = sapling file entry
 $3 = tree file entry
 $D = subdirectory file entry                          name_length = length of file_name ($1-$F)
 $E = subdirectory header                              file_name = $1-$F ASCII characters: first = letters
 $F = volume directory header                                      rest are letters, digits, periods.
                                                       key_pointer = block address of file's key block
 +-----------+                                         blocks_used = total blocks for file
 | file_type |                                         EOF = byte number for end of file ($0-$FFFFFF)
 | (1 byte)  |                                         version, min_version = 0 for ProDOS 1.0
 +-----------+                                         entry_length = $27 for ProDOS 1.0
                                                       entries_per_block = $0D for ProDOS 1.0
 See section B.4.2.4                                   aux_type = defined by system program
                                                       file_count = total files in directory
                                                       bit_map_pointer = block address of bit map
                                                       total_blocks = total blocks on volume
                                                       parent_pointer = block address containing entry
                                                       parent_entry_number = number in that block
                                                       parent_entry_length = $27 for ProDOS 1.0
                                                       header pointer = block address of key block
                                                       of entry's directory
"""
import re
import struct
from dataclasses import dataclass, field, fields
from enum import IntEnum
from typing import Any, ClassVar, Final, Protocol, Self

from .errors import ProDOSError
from .globals import block_size, entries_per_block, entry_length, volume_directory_length, volume_key_block
from .p8datetime import P8DateTime


class StorageType(IntEnum):
    empty = 0
    seedling = 1                # one data block
    sapling = 2                 # index block -> up to 256 data blocks
    tree = 3                    # master index -> up to 128 index blocks -> data blocks
#    pascal = 4                 # Pascal area, not supported; see https://prodos8.com/docs/technote/25/
    extended = 5                # GS/OS file with data and resource forks
    dir = 0xD                   # file entry for a subdirectory
    subdirhdr = 0xE             # subdirectory header
    voldirhdr = 0xF             # volume directory header


directory_types = {
    StorageType.dir,
    StorageType.subdirhdr,
    StorageType.voldirhdr,
}

simple_file_types = {
    StorageType.seedling,
    StorageType.sapling,
    StorageType.tree,
}


class FileType(IntEnum):
    """A few common file types.  Any byte value is a valid file_type."""
    TXT = 0x04      # ASCII text
    BIN = 0x06      # binary, aux_type is the load address
    DIR = 0x0F      # directory
    BAS = 0xFC      # Applesoft BASIC program
    SYS = 0xFF      # ProDOS system file, e.g. PRODOS or *.SYSTEM


_access_flags: Final = dict(
    R = 1<<0,  # read
    W = 1<<1,  # write
    I = 1<<2,  # invisible
    # bits 3 and 4 reserved
    B = 1<<5,  # backup
    N = 1<<6,  # rename
    D = 1<<7,  # destroy
)


def access_byte(s: str = 'RWBND') -> int:
    return sum(_access_flags[c] for c in s)


def parse_access(s: str) -> int:
    """Access byte from flag letters like 'RWBND'; dashes are ignored so 'RW-BND' from a listing works"""
    letters = s.upper().replace('-', '')
    bad = set(letters) - _access_flags.keys()
    if bad:
        raise ProDOSError(f"Unknown access flags {''.join(sorted(bad))}, expected letters from {''.join(_access_flags)}")
    return access_byte(''.join(dict.fromkeys(letters)))


def access_repr(flags: int) -> str:
    s = ''
    for c, f in _access_flags.items():
        s += c if flags & f else '-'
    return s


def is_legal_name(name: str) -> bool:
    """1-15 characters: a letter followed by letters, digits or periods"""
    return re.fullmatch(r'[A-Z][A-Z0-9.]{0,14}', name) is not None


class IsDataclass(Protocol):
    # verify whether obj is a dataclass
    __dataclass_fields__: ClassVar[dict[str, Any]]


def shallow_dict(d: IsDataclass) -> dict[str, Any]:
    """create a shallow dict for a dataclass, since asdict() breaks nested objs"""
    return {f.name: getattr(d, f.name) for f in fields(d)}


@dataclass(kw_only=True, frozen=True)
class NamedEntry:
    """The storage_type / name_length byte and file_name common to every record"""
    SIZE: ClassVar = 16
    _struct: ClassVar = "<B15s"

    storage_type: StorageType
    file_name: str

    def pack(self) -> bytes:
        if len(self.file_name) > 15:
            raise ProDOSError(f"Name {self.file_name!r} is longer than 15 characters")
        type_len = (self.storage_type << 4) | len(self.file_name)
        return struct.pack(NamedEntry._struct, type_len, self.file_name.encode('ascii'))

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        (
            type_len,
            name,
        ) = struct.unpack(cls._struct, buf)
        storage_type = (type_len >> 4) & 0b1111
        name = name[:type_len & 0b1111]
        file_name = name.decode('ascii', errors='ignore')
        return cls(
            storage_type=storage_type,
            file_name=file_name,
        )


@dataclass(kw_only=True, frozen=True)
class DirectoryHeader(NamedEntry):
    """Fields common to the volume directory header and subdirectory headers"""
    SIZE: ClassVar = NamedEntry.SIZE + 19
    _struct: ClassVar = "<8s4sBBBBBH"

    reserved: bytes = bytes(8)
    created: P8DateTime = field(default_factory=P8DateTime.now)
    version: int = 0
    min_version: int = 0
    access: int = access_byte()
    entry_length: int = entry_length
    entries_per_block: int = entries_per_block
    file_count: int = 0

    def __repr__(self):
        flags = access_repr(self.access)
        typ = f"{self.storage_type:x}".upper()
        return f"    {self.file_count:d} files in {self.file_name} {typ} {flags} {self.created}"

    def __post_init__(self):
        if self.entry_length != entry_length or self.entries_per_block != entries_per_block:
            raise ProDOSError(
                f"Directory {self.file_name} has entry_length {self.entry_length} and "
                f"entries_per_block {self.entries_per_block}, expected {entry_length} and {entries_per_block}"
            )

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            DirectoryHeader._struct,
            self.reserved,
            self.created.pack(),
            self.version,
            self.min_version,
            self.access,
            self.entry_length,
            self.entries_per_block,
            self.file_count,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        n = NamedEntry.SIZE
        d = NamedEntry.unpack(buf[:n])
        (
            reserved,
            dt,
            version,
            min_version,
            access,
            entry_length,
            entries_per_block,
            file_count
        ) = struct.unpack(DirectoryHeader._struct, buf[n:DirectoryHeader.SIZE])
        return cls(
            reserved=reserved,
            created=P8DateTime.unpack(dt),
            version=version,
            min_version=min_version,
            access=access,
            entry_length=entry_length,
            entries_per_block=entries_per_block,
            file_count=file_count,
            **shallow_dict(d)
        )


@dataclass(kw_only=True, frozen=True, repr=False)
class VolumeDirectoryHeader(DirectoryHeader):
    """
    This is the first (header) entry in the volume directory,
    which describes the volume itself.

    Figure B-3. The Volume Directory Header


    Field                                Byte of
   Length                                Block
          +----------------------------+
  1 byte  | storage_type | name_length | $04
          |----------------------------|
          |                            | $05
          /                            /
 15 bytes /        file_name           /
          |                            | $13
          |----------------------------|
          |                            | $14
          /                            /
  8 bytes /          reserved          /        Zero in volumes written by ProDOS 8
          |                            | $1B
          |----------------------------|
          |                            | $1C
          |          creation          | $1D
  4 bytes |        date & time         | $1D
          |                            | $1F
          |----------------------------|
  1 byte  |          version           | $20    ProDOS version that initialized volume
          |----------------------------|
  1 byte  |        min_version         | $21
          |----------------------------|
  1 byte  |           access           | $22
          |----------------------------|
  1 byte  |        entry_length        | $23    $27, all headers are this size
          |----------------------------|
  1 byte  |     entries_per_block      | $24    $0D, all blocks have this many entries
          |----------------------------|
          |                            | $25    Count of active files in this directory
  2 bytes |         file_count         | $26
          |----------------------------|
          |                            | $27    First block in volume bitmap
  2 bytes |      bit_map_pointer       | $28    (little endian)
          |----------------------------|
          |                            | $29    Total blocks on volume
  2 bytes |        total_blocks        | $2A
          +----------------------------+
    """
    SIZE: ClassVar = DirectoryHeader.SIZE + 4
    _struct: ClassVar = "<HH"

    bitmap_pointer: int         # first block of the volume bit map
    total_blocks: int           # total blocks on the volume

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            VolumeDirectoryHeader._struct,
            self.bitmap_pointer,
            self.total_blocks,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        n = DirectoryHeader.SIZE
        d = DirectoryHeader.unpack(buf[:n])
        if d.storage_type != StorageType.voldirhdr:
            raise ProDOSError(f"VolumeDirectoryHeader: bad storage type {d.storage_type:x}")
        (
            bitmap_pointer,
            total_blocks
        ) = struct.unpack(cls._struct, buf[n:cls.SIZE])
        return cls(
            bitmap_pointer=bitmap_pointer,
            total_blocks=total_blocks,
            **shallow_dict(d)
        )


# ProDOS 8 writes $75 (followed by its version and some constants) at the start
# of the reserved bytes in each subdirectory header; GS/OS writes $76.
subdirectory_reserved: Final = bytes([0x75, 0x00, 0x00, 0xC3, 0x27, 0x0D, 0x00, 0x00])


@dataclass(kw_only=True, frozen=True, repr=False)
class SubdirectoryHeader(DirectoryHeader):
    """
    This is the first (header) entry in each sub directory,
    which describes the directory contents.

    Figure B-4. The Subdirectory Header


    Field                                Byte of
    Length                                Block
            +----------------------------+
    1 byte  | storage_type | name_length | $04
            |----------------------------|
            |                            | $05
            /                            /          Up to 15 characters long (see name_length)
   15 bytes /         file_name          /          containing A-Z, 0-9, and period.
            |                            | $13
            |----------------------------|
            |                            | $14
            /                            /          $75 then constants (ProDOS 8),
    8 bytes /          reserved          /          or $76 then zeros (GS/OS)
            |                            | $1B
            |----------------------------|
            |                            | $1C
            |          creation          | $1D
    4 bytes |        date & time         | $1D
            |                            | $1F
            |----------------------------|
    1 byte  |          version           | $20
            |----------------------------|
    1 byte  |        min_version         | $21
            |----------------------------|
    1 byte  |           access           | $22
            |----------------------------|
    1 byte  |        entry_length        | $23
            |----------------------------|
    1 byte  |     entries_per_block      | $24
            |----------------------------|
            |                            | $25
    2 bytes |         file_count         | $26
            |----------------------------|
            |                            | $27      Block containing this directory's
    2 bytes |       parent_pointer       | $28      entry in its parent (little endian)
            |----------------------------|
    1 byte  |    parent_entry_number     | $29      Number of that entry within the block,
            |----------------------------|          counting from 1 (the key block's header is 1)
    1 byte  |    parent_entry_length     | $2A      $27
            +----------------------------+
    """
    SIZE: ClassVar = DirectoryHeader.SIZE + 4
    _struct: ClassVar = "<HBB"

    reserved: bytes = subdirectory_reserved
    parent_pointer: int         # block containing our entry in the parent directory
    parent_entry_number: int    # entry number of our entry within that block
    parent_entry_length: int = entry_length

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            SubdirectoryHeader._struct,
            self.parent_pointer,
            self.parent_entry_number,
            self.parent_entry_length,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        n = DirectoryHeader.SIZE
        d = DirectoryHeader.unpack(buf[:n])
        if d.storage_type != StorageType.subdirhdr:
            raise ProDOSError(f"SubdirectoryHeader: bad storage type {d.storage_type:x}")
        (
            parent_pointer,
            parent_entry_number,
            parent_entry_length
        ) = struct.unpack(cls._struct, buf[n:cls.SIZE])
        return cls(
            parent_pointer=parent_pointer,
            parent_entry_number=parent_entry_number,
            parent_entry_length=parent_entry_length,
            **shallow_dict(d)
        )


@dataclass(kw_only=True, frozen=True)
class FileEntry(NamedEntry):
    """
    Figure B-5. The File Entry


    Field                                 Entry
    Length                                Offset
            +----------------------------+
    1 byte  | storage_type | name_length | $00
            |----------------------------|
            |                            | $01
            /                            /
   15 bytes /         file_name          /
            |                            | $0F
            |----------------------------|
    1 byte  |         file_type          | $10
            |----------------------------|
            |                            | $11      First block of file
    2 bytes |        key_pointer         | $12      (master/index/data for tree/sapling/seedling)
            |----------------------------|
            |                            | $13      Blocks occupied including index blocks
    2 bytes |        blocks_used         | $14
            |----------------------------|
            |                            | $15      Total readable bytes
    3 bytes |            EOF             |          in little endian order (lo med hi)
            |                            | $17
            |----------------------------|
            |                            | $18
            |          creation          |
    4 bytes |        date & time         |
            |                            | $1B
            |----------------------------|
    1 byte  |          version           | $1C
            |----------------------------|
    1 byte  |        min_version         | $1D
            |----------------------------|
    1 byte  |           access           | $1E
            |----------------------------|
            |                            | $1F      File-type dependent metadata,
    2 bytes |          aux_type          | $20      e.g. binary load address
            |----------------------------|
            |                            | $21
            |                            |
    4 bytes |          last mod          |
            |                            | $24
            |----------------------------|
            |                            | $25      Key block of directory containing this entry
    2 bytes |       header_pointer       | $26
            +----------------------------+

    Entries are immutable values: use dataclasses.replace() to derive a changed copy.
    """
    SIZE: ClassVar = NamedEntry.SIZE + 23
    _struct: ClassVar = "<BHHHB4sBBBH4sH"
    empty: ClassVar['FileEntry']
    root: ClassVar['FileEntry']

    # match __repr__ layout
    heading: ClassVar = "File name               EOF T/FT Access Created        Modified      Blocks @ Key"

    file_type: int
    key_pointer: int        # key block of the file's storage
    blocks_used: int        # all blocks of the file, including index blocks
    eof: int
    created: P8DateTime = field(default_factory=P8DateTime.now)
    version: int = 0
    min_version: int = 0
    access: int = access_byte()
    aux_type: int = 0
    last_mod: P8DateTime = field(default_factory=P8DateTime.now)
    header_pointer: int     # key block of directory owning this entry

    @classmethod
    def new(cls, file_name: str, file_type: int = FileType.BIN, aux_type: int = 0) -> Self:
        """Metadata for a new file; the storage fields are filled in when it's written"""
        return cls(
            storage_type=StorageType.empty,
            file_name=file_name,
            file_type=file_type,
            aux_type=aux_type,
            key_pointer=0,
            blocks_used=0,
            eof=0,
            header_pointer=0,
        )

    def __repr__(self):
        typ = f"{self.storage_type:1x}/{self.file_type:02x}".upper()
        flags = access_repr(self.access)
        name = self.file_name
        if self.is_dir:
            name += '/'
        return f"{name:18s} {self.eof:>8d} {typ} {flags} {self.created} {self.last_mod} {self.blocks_used:>5d} @ {self.key_pointer}"

    @property
    def is_dir(self) -> bool:
        return self.storage_type in directory_types

    @property
    def is_volume_dir(self) -> bool:
        return self.storage_type == StorageType.voldirhdr

    @property
    def is_plain_file(self) -> bool:
        return self.storage_type in simple_file_types

    @property
    def is_active(self) -> bool:
        return self.storage_type != StorageType.empty

    def pack(self) -> bytes:
        return super().pack() + struct.pack(FileEntry._struct,
            self.file_type,
            self.key_pointer,
            self.blocks_used,
            self.eof & 0xffff,
            self.eof >> 16,
            self.created.pack(),
            self.version,
            self.min_version,
            self.access,
            self.aux_type,
            self.last_mod.pack(),
            self.header_pointer,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        n = NamedEntry.SIZE
        d = NamedEntry.unpack(buf[:n])
        (
            file_type,
            key_pointer,
            blocks_used,
            eofw,
            eof3,
            dt,
            version,
            min_version,
            access,
            aux_type,
            mt,
            header_pointer,
        ) = struct.unpack(cls._struct, buf[n:cls.SIZE])

        return cls(
            file_type=file_type,
            key_pointer=key_pointer,
            blocks_used=blocks_used,
            eof=eofw | (eof3 << 16),
            created=P8DateTime.unpack(dt),
            version=version,
            min_version=min_version,
            access=access,
            aux_type=aux_type,
            last_mod=P8DateTime.unpack(mt),
            header_pointer=header_pointer,
            **shallow_dict(d)
        )


@dataclass(kw_only=True, frozen=True)
class ForkEntry:
    """
    Mini-entry describing one fork of an extended file (storage type $5),
    stored in the extended key block.  See https://prodos8.com/docs/technote/25/

    - Offset +0: storage_type (1 byte)
    - Offset +1: key_block (2 bytes)
    - Offset +3: blocks_used (2 bytes)
    - Offset +5: EOF (3 bytes, little-endian: 2-byte word + 1 byte)

    Followed by Finder info (36 bytes).
    """
    SIZE: ClassVar = 44  # 8 bytes mini-entry + 36 bytes finder info
    _struct: ClassVar = "<BHHHB36s"

    storage_type: StorageType
    key_block: int          # block address of fork's key block
    blocks_used: int        # total blocks for this fork
    eof: int                # end of file (3 bytes, 0-$FFFFFF)
    finder_info: bytes = bytes(36)     # 36 bytes of Finder info (optional HFS data)

    def pack(self) -> bytes:
        assert len(self.finder_info) == 36, \
            f"ForkEntry.pack: finder_info should be 36 bytes, got {len(self.finder_info)}"
        return struct.pack(
            ForkEntry._struct,
            self.storage_type,
            self.key_block,
            self.blocks_used,
            self.eof & 0xffff,      # EOF low word (2 bytes)
            self.eof >> 16,         # EOF high byte (1 byte)
            self.finder_info,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        (
            storage_type,
            key_block,
            blocks_used,
            eofw,
            eof3,
            finder_info,
        ) = struct.unpack(cls._struct, buf[:cls.SIZE])

        return cls(
            storage_type=storage_type,
            key_block=key_block,
            blocks_used=blocks_used,
            eof=eofw | (eof3 << 16),
            finder_info=finder_info
        )


# empty file entry to fill unused slots
FileEntry.empty = FileEntry(
    storage_type = StorageType.empty,
    file_name = '',
    file_type = 0,
    key_pointer = 0,
    blocks_used = 0,
    eof = 0,
    created = P8DateTime.empty,
    version = 0,
    min_version = 0,
    access = 0,
    aux_type = 0,
    last_mod = P8DateTime.empty,
    header_pointer = 0,
)

# pseudo-entry naming the volume directory, which has no entry of its own
FileEntry.root = FileEntry(
    storage_type = StorageType.voldirhdr,
    file_name = '/',
    file_type = FileType.DIR,
    key_pointer = volume_key_block,
    blocks_used = volume_directory_length,
    eof = volume_directory_length * block_size,
    created = P8DateTime.empty,
    version = 0,
    min_version = 0,
    access = 0,
    aux_type = 0,
    last_mod = P8DateTime.empty,
    header_pointer = 0,
)

# static tests

assert VolumeDirectoryHeader.SIZE == entry_length
assert SubdirectoryHeader.SIZE == entry_length
assert FileEntry.SIZE == entry_length

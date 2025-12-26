from typing import ClassVar, Self, Final, Protocol, Any
from dataclasses import dataclass, fields, field
from enum import IntEnum
import struct
import logging

from .globals import entry_length, entries_per_block, \
    volume_key_block, volume_directory_length
from .p8datetime import P8DateTime

"""
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


#TODO non-standard types https://prodos8.com/docs/technote/25/
# 4=pascal area, 5=extended file with ExtendedKeyBlock with data and resource fork

class StorageType(IntEnum):
    empty = 0
    seedling = 1
    sapling = 2
    tree = 3
    dir = 0xD
    subdirhdr = 0xE
    voldirhdr = 0xF

directory_types = {
    StorageType.dir,            # directory file entry
    StorageType.subdirhdr,      # subdirectory header
    StorageType.voldirhdr,      # volume directory header
}

simple_file_types = {
    StorageType.seedling,
    StorageType.sapling,
    StorageType.tree,
}


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


def access_repr(flags: int) -> str:
    s = ''
    for c, f in _access_flags.items():
        s += c if flags & f else '-'
    return s


class IsDataclass(Protocol):
    # verify whether obj is a dataclass
    __dataclass_fields__: ClassVar[dict[str, Any]]


def shallow_dict(d: IsDataclass):
    """create a shallow dict for a dataclass, since asdict() breaks nested objs"""
    return {f.name: getattr(d, f.name) for f in fields(d)}


@dataclass(kw_only=True)
class NamedEntry:
    SIZE: ClassVar = 16
    _struct: ClassVar = "<B15s"

    storage_type: StorageType
    file_name: str

    def pack(self) -> bytes:
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


@dataclass(kw_only=True)
class DirectoryEntry(NamedEntry):
    """Entry pointing to a DirectoryFile within a directory block"""
    SIZE: ClassVar = NamedEntry.SIZE + 19
    _struct: ClassVar = "<8s4s5BH"

    #TODO
    # spec suggests there are magic bytes for VolumeDirectoryHeaderEntry
    # namely $75 $23 $00 $c3 $27 $0d $00 where $23 is version 2.3
    # from source of ProDOS 8 V2.0.3      06-May-93
    #   Pass        DB     $75
    #   XDOSver     DB     $0,0,$C3,$27,$0D,0,0,0
    # but this doesn't seem to be the case in the wild
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

    def __post_init___(self):
        assert self.entry_length == entry_length, \
            f"DirectoryHeaderEntry: entry_length {self.entry_length} != {entry_length}"
        assert self.entries_per_block == entries_per_block, \
            f"DirectoryHeaderEntry: entries_per_block {self.entries_per_block} != {entries_per_block}"

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            DirectoryEntry._struct,
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
        ) = struct.unpack(cls._struct, buf[n:])
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


@dataclass(kw_only=True, repr=False)
class VolumeDirectoryHeaderEntry(DirectoryEntry):
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
          /                            /        Allegedly should be magic bytes:
  8 bytes /          reserved          /        $75 $23 $00 $c3 $27 $0d $00
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
    SIZE: ClassVar = DirectoryEntry.SIZE + 4
    _struct: ClassVar = "<HH"

    bit_map_pointer: int        # first block of free map
    total_blocks: int           # total blocks on device

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            VolumeDirectoryHeaderEntry._struct,
            self.bit_map_pointer,
            self.total_blocks,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        n = DirectoryEntry.SIZE
        d = DirectoryEntry.unpack(buf[:n])
        assert d.storage_type == StorageType.voldirhdr, \
            f"VolumeDirectoryHeaderEntry bad storage type {d.storage_type:x}"
        (
            bit_map_pointer,
            total_blocks
        ) = struct.unpack(cls._struct, buf[n:])
        return cls(
            bit_map_pointer=bit_map_pointer,
            total_blocks=total_blocks,
            **shallow_dict(d)
        )


@dataclass(kw_only=True, repr=False)
class SubdirectoryHeaderEntry(DirectoryEntry):
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
            /                            /
    8 bytes /          reserved          /
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
            |                            | $27      Block address of parent directory
    2 bytes |       parent_pointer       | $28      (little endian)
            |----------------------------|
    1 byte  |    parent_entry_number     | $29      This directory's entry in parent
            |----------------------------|
    1 byte  |    parent_entry_length     | $2A      $27
            +----------------------------+
    """
    SIZE: ClassVar = DirectoryEntry.SIZE + 4
    _struct: ClassVar = "<HBB"

    parent_pointer: int         # key block of parent dir
    parent_entry_number: int    # entry index in parent
    parent_entry_length: int = entry_length

    def __post_init___(self):
        assert self.parent_entry_length == entry_length, \
            f"SubdirectoryHeaderEntry: unexpected parent_entry_length {self.parent_entry_length} != {entry_length}"

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            SubdirectoryHeaderEntry._struct,
            self.parent_pointer,
            self.parent_entry_number,
            self.parent_entry_length,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        n = DirectoryEntry.SIZE
        d = DirectoryEntry.unpack(buf[:n])
        assert d.storage_type == StorageType.subdirhdr, \
            f"SubdirectoryHeaderEntry: bad storage type {d.storage_type:x}"
        (
            parent_pointer,
            parent_entry_number,
            parent_entry_length
        ) = struct.unpack(cls._struct, buf[n:])
        return cls(
            parent_pointer=parent_pointer,
            parent_entry_number=parent_entry_number,
            parent_entry_length=parent_entry_length,
            **shallow_dict(d)
        )

@dataclass(kw_only=True)
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

    """
    SIZE: ClassVar = NamedEntry.SIZE + 23
    _struct: ClassVar = "<BHHHB4sBBBH4sH"
    empty: ClassVar['FileEntry']
    root: ClassVar['FileEntry']

    file_type: int
    key_pointer: int        # pointer fo file key block
    blocks_used: int
    eof: int
    created: P8DateTime = field(default_factory=P8DateTime.now)
    version: int = 0
    min_version: int = 0
    access: int = access_byte()
    aux_type: int = 0
    last_mod: P8DateTime = field(default_factory=P8DateTime.now)
    header_pointer: int     # key block of directory owning this entry

    def __repr__(self):
        typ = f"{self.storage_type:1x}/{self.file_type:02x}".upper()
        flags = access_repr(self.access)
        name = self.file_name
        if self.is_dir:
            name += '/'
        return f"{name:18s} {self.eof:>8d} {typ} {flags} {self.created} {self.last_mod} {self.blocks_used:d} @ {self.key_pointer}"

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
        return self.storage_type != 0

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

        if d.storage_type not in {StorageType.empty, StorageType.dir} | simple_file_types:
            logging.warning(f"FileEntry: unexpected storage type {d.storage_type:x}")

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
        ) = struct.unpack(cls._struct, buf[n:])

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

# dummy record to indicate root directory
FileEntry.root = FileEntry(
    storage_type = StorageType.voldirhdr,
    file_name = '/',
    file_type = 0xff,
    key_pointer = volume_key_block,
    blocks_used = volume_directory_length,
    eof = 0,
    created = P8DateTime.empty,
    version = 0,
    min_version = 0,
    access = 0,
    aux_type = 0,
    last_mod = P8DateTime.empty,
    header_pointer = 0,
)

# static tests

assert VolumeDirectoryHeaderEntry.SIZE == entry_length
assert SubdirectoryHeaderEntry.SIZE == entry_length
assert FileEntry.SIZE == entry_length


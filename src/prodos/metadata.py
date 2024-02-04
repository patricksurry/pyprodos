from typing import ClassVar, Dict, Self, Final, Protocol
from dataclasses import dataclass, fields
import struct
import logging

from .globals import entry_length, entries_per_block, \
    volume_key_block, volume_directory_length
from .p8datetime import P8DateTime


storage_type_empty: Final = 0x0

storage_type_dir: Final = 0xD
storage_type_subdir: Final = 0xE
storage_type_voldir: Final = 0xF

storage_type_seedling: Final = 0x1
storage_type_sapling: Final = 0x2
storage_type_tree: Final = 0x3

directory_types = {
    storage_type_dir,
    storage_type_subdir,
    storage_type_voldir,
}

simple_file_types = {
    storage_type_seedling,
    storage_type_sapling,
    storage_type_tree,
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
    __dataclass_fields__: ClassVar[Dict]


def shallow_dict(d: IsDataclass):
    """create a shallow dict for a dataclass, since asdict() breaks nested objs"""
    return {field.name: getattr(d, field.name) for field in fields(d)}


@dataclass(kw_only=True)
class NamedEntry:
    _struct: ClassVar = "<B15s"
    _size: ClassVar = 16

    # non-standard types https://prodos8.com/docs/technote/25/
    # 4=pascal area, 5=extended file with ExtendedKeyBlock with data and resource fork
    storage_type: int       # 0=unused, 1=seedling, 2=sapling, 3=tree, D=subdir, E=subdir header, F=vol header
    file_name: str

    def pack(self) -> bytes:
        type_len = (self.storage_type << 4) | len(self.file_name)
        return struct.pack(NamedEntry._struct, type_len, self.file_name.encode('ascii'))

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        (
            type_len,
            name,
        ) = struct.unpack(kls._struct, buf)
        storage_type = (type_len >> 4) & 0b1111
        name = name[:type_len & 0b1111]
        file_name = name.decode('ascii', errors='ignore')
        return kls(
            storage_type=storage_type,
            file_name=file_name,
        )


@dataclass(kw_only=True)
class DirectoryHeaderEntry(NamedEntry):
    _struct: ClassVar = "<8s4s5BH"
    _size: ClassVar = NamedEntry._size + 19

    # spec suggests there are magic bytes for VolumeDirectoryHeaderEntry
    # namely $75 $23 $00 $c3 $27 $0d $00 where $23 is version 2.3
    # but this doesn't seem to be the case in the wild
    reserved: bytes = bytes(8)
    date_time: P8DateTime
    version: int
    min_version: int
    access: int
    entry_length: int = entry_length
    entries_per_block: int = entries_per_block
    file_count: int

    def __repr__(self):
        flags = access_repr(self.access)
        typ = f"{self.storage_type:x}".upper()
        return f"    {self.file_count:d} files in {self.file_name} {typ} {flags} {self.date_time}"

    def __post_init___(self):
        assert self.entry_length == entry_length, \
            f"DirectoryHeaderEntry: entry_length {self.entry_length} != {entry_length}"
        assert self.entries_per_block == entries_per_block, \
            f"DirectoryHeaderEntry: entries_per_block {self.entries_per_block} != {entries_per_block}"

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            DirectoryHeaderEntry._struct,
            self.reserved,
            self.date_time.pack(),
            self.version,
            self.min_version,
            self.access,
            self.entry_length,
            self.entries_per_block,
            self.file_count,
        )

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = NamedEntry._size
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
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            reserved=reserved,
            date_time=P8DateTime.unpack(dt),
            version=version,
            min_version=min_version,
            access=access,
            entry_length=entry_length,
            entries_per_block=entries_per_block,
            file_count=file_count,
            **shallow_dict(d)
        )


@dataclass(kw_only=True, repr=False)
class VolumeDirectoryHeaderEntry(DirectoryHeaderEntry):
    _struct: ClassVar = "<HH"
    _size: ClassVar = DirectoryHeaderEntry._size + 4

    bit_map_pointer: int        # first block of free map
    total_blocks: int           # total blocks on device

    def pack(self) -> bytes:
        return super().pack() + struct.pack(
            VolumeDirectoryHeaderEntry._struct,
            self.bit_map_pointer,
            self.total_blocks,
        )

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = DirectoryHeaderEntry._size
        d = DirectoryHeaderEntry.unpack(buf[:n])
        assert d.storage_type == storage_type_voldir, \
            f"VolumeDirectoryHeaderEntry bad storage type {d.storage_type:x}"
        (
            bit_map_pointer,
            total_blocks
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            bit_map_pointer=bit_map_pointer,
            total_blocks=total_blocks,
            **shallow_dict(d)
        )


@dataclass(kw_only=True, repr=False)
class SubdirectoryHeaderEntry(DirectoryHeaderEntry):
    _struct: ClassVar = "<HBB"
    _size: ClassVar = DirectoryHeaderEntry._size + 4

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
    def unpack(kls, buf: bytes) -> Self:
        n = DirectoryHeaderEntry._size
        d = DirectoryHeaderEntry.unpack(buf[:n])
        assert d.storage_type == storage_type_subdir, \
            f"SubdirectoryHeaderEntry: bad storage type {d.storage_type:x}"
        (
            parent_pointer,
            parent_entry_number,
            parent_entry_length
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            parent_pointer=parent_pointer,
            parent_entry_number=parent_entry_number,
            parent_entry_length=parent_entry_length,
            **shallow_dict(d)
        )

@dataclass(kw_only=True)
class FileEntry(NamedEntry):
    _struct: ClassVar = "<BHHHB4sBBBH4sH"
    _size: ClassVar = NamedEntry._size + 23
    empty: ClassVar['FileEntry']
    root: ClassVar['FileEntry']

    file_type: int
    key_pointer: int        # pointer fo file key block
    blocks_used: int
    eof: int
    date_time: P8DateTime
    version: int = 0
    min_version: int = 0
    access: int
    aux_type: int = 0
    last_mod: P8DateTime
    header_pointer: int     # key block of directory owning this entry

    def __repr__(self):
        typ = f"{self.storage_type:1x}/{self.file_type:02x}".upper()
        flags = access_repr(self.access)
        name = self.file_name
        if self.is_dir:
            name += '/'
        return f"{name:18s} {self.eof:>8d} {typ} {flags} {self.date_time} {self.last_mod} {self.blocks_used:d} @ {self.key_pointer}"

    @property
    def is_dir(self) -> bool:
        return self.storage_type in directory_types

    @property
    def is_volume_dir(self) -> bool:
        return self.storage_type == storage_type_voldir

    @property
    def is_simple_file(self) -> bool:
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
            self.date_time.pack(),
            self.version,
            self.min_version,
            self.access,
            self.aux_type,
            self.last_mod.pack(),
            self.header_pointer,
        )

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = NamedEntry._size
        d = NamedEntry.unpack(buf[:n])

        if d.storage_type not in {storage_type_empty, storage_type_dir} | simple_file_types:
            logging.warn(f"FileEntry: unexpected storage type {d.storage_type:x}")

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
        ) = struct.unpack(kls._struct, buf[n:])

        return kls(
            file_type=file_type,
            key_pointer=key_pointer,
            blocks_used=blocks_used,
            eof=eofw | (eof3 << 16),
            date_time=P8DateTime.unpack(dt),
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
    storage_type = storage_type_empty,
    file_name = '',
    file_type = 0,
    key_pointer = 0,
    blocks_used = 0,
    eof = 0,
    date_time = P8DateTime.empty,
    version = 0,
    min_version = 0,
    access = 0,
    aux_type = 0,
    last_mod = P8DateTime.empty,
    header_pointer = 0,
)

# dummy record to indicate root directory
FileEntry.root = FileEntry(
    storage_type = storage_type_voldir,
    file_name = '/',
    file_type = 0xff,
    key_pointer = volume_key_block,
    blocks_used = volume_directory_length,
    eof = 0,
    date_time = P8DateTime.empty,
    version = 0,
    min_version = 0,
    access = 0,
    aux_type = 0,
    last_mod = P8DateTime.empty,
    header_pointer = 0,
)

# static tests

assert VolumeDirectoryHeaderEntry._size == entry_length
assert SubdirectoryHeaderEntry._size == entry_length
assert FileEntry._size == entry_length


from typing import ClassVar, Self
from dataclasses import dataclass, asdict
import struct

from .globals import access_flags, entry_length, entries_per_block


directory_types = {0xD, 0xE, 0xF}
simple_file_types = {1, 2, 3}


def format_access(flags: int) -> str:
    s = ''
    for f, c in access_flags.items():
        s += c if flags & f else '-'
    return s


def format_date_time(buf: bytes):
    y = buf[1] >> 1
    m = (buf[0] >> 5) + ((buf[1] & 1) << 3)
    d = buf[0] & 0b11111
    hr = buf[3]
    mi = buf[2]
    return f"{y:03d}-{m:02d}-{d:02d}T{hr:02d}:{mi:02d}"


@dataclass(kw_only=True)
class NamedEntry:
    _struct: ClassVar = "<B15s"
    _size: ClassVar = 16

    # non-standard types https://prodos8.com/docs/technote/25/
    # 4=pascal area, 5=extended file with ExtendedKeyBlock with data and resource fork
    storage_type: int       # 0=unused, 1=seedling, 2=sapling, 3=tree, D=subdir, E=subdir header, F=vol header
    file_name: str

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        (
            type_len,
            name,
        ) = struct.unpack(kls._struct, buf)
        storage_type = (type_len >> 4) & 0xf
        name = name[:type_len & 0xf]
        file_name = name.decode('ascii', errors='ignore')
        return kls(
            storage_type=storage_type,
            file_name=file_name,
        )


@dataclass(kw_only=True)
class DirectoryHeaderEntry(NamedEntry):
    _struct: ClassVar = "<8s4s5BH"
    _size: ClassVar = NamedEntry._size + 19

    reserved: bytes
    date_time: bytes
    version: int
    min_version: int
    access: int
    entry_length: int = entry_length
    entries_per_block: int = entries_per_block
    file_count: int

    def __repr__(self):
        create = format_date_time(self.date_time)
        flags = format_access(self.access)
        typ = f"{self.storage_type:x}".upper()
        return f"    {self.file_count:d} files in {self.file_name} {typ} {flags} {create}"

    def __post_init___(self):
        assert self.entry_length == entry_length
        assert self.entries_per_block == entries_per_block

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = NamedEntry._size
        d = NamedEntry.unpack(buf[:n])
        (
            reserved,
            date_time,
            version,
            min_version,
            access,
            entry_length,
            entries_per_block,
            file_count
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            reserved=reserved,
            date_time=date_time,
            version=version,
            min_version=min_version,
            access=access,
            entry_length=entry_length,
            entries_per_block=entries_per_block,
            file_count=file_count,
            **asdict(d)
        )


@dataclass(kw_only=True, repr=False)
class VolumeDirectoryHeaderEntry(DirectoryHeaderEntry):
    _struct: ClassVar = "<HH"
    _size: ClassVar = DirectoryHeaderEntry._size + 4

    bit_map_pointer: int
    total_blocks: int

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = DirectoryHeaderEntry._size
        d = DirectoryHeaderEntry.unpack(buf[:n])
        (
            bit_map_pointer,
            total_blocks
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            bit_map_pointer=bit_map_pointer,
            total_blocks=total_blocks,
            **asdict(d)
        )


@dataclass(kw_only=True, repr=False)
class SubdirectoryHeaderEntry(DirectoryHeaderEntry):
    _struct: ClassVar = "<HBB"
    _size: ClassVar = DirectoryHeaderEntry._size + 4

    parent_pointer: int
    parent_entry_number: int
    parent_entry_length: int = entry_length

    def __post_init___(self):
        assert self.parent_entry_length == entry_length

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = DirectoryHeaderEntry._size
        d = DirectoryHeaderEntry.unpack(buf[:n])
        (
            parent_pointer,
            parent_entry_number,
            parent_entry_length
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            parent_pointer=parent_pointer,
            parent_entry_number=parent_entry_number,
            parent_entry_length=parent_entry_length,
            **asdict(d)
        )


@dataclass(kw_only=True)
class FileEntry(NamedEntry):
    _struct: ClassVar = "<BHHHB4sBBBH4sH"
    _size: ClassVar = NamedEntry._size + 23

    file_type: int
    key_pointer: int
    blocks_used: int
    eof: int
    date_time: bytes
    version: int
    min_version: int
    access: int
    aux_type: int
    last_mod: bytes
    header_pointer: int

    def __repr__(self):
        typ = f"{self.storage_type:1x}/{self.file_type:02x}".upper()
        flags = format_access(self.access)
        name = self.file_name
        if self.is_dir:
            name += '/'
        create = format_date_time(self.date_time)
        mod = format_date_time(self.last_mod)
        return f"{name:18s} {self.eof:>8d} {typ} {flags} {create} {mod} {self.blocks_used:d} @ {self.key_pointer}"

    @property
    def is_dir(self) -> bool:
        return self.storage_type in directory_types

    @property
    def is_simple_file(self) -> bool:
        return self.storage_type in simple_file_types

    @property
    def is_active(self) -> bool:
        return self.storage_type != 0

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        n = NamedEntry._size
        d = NamedEntry.unpack(buf[:n])
        (
            file_type,
            key_pointer,
            blocks_used,
            eofw,
            eof3,
            date_time,
            version,
            min_version,
            access,
            aux_type,
            last_mod,
            header_pointer,
        ) = struct.unpack(kls._struct, buf[n:])
        return kls(
            file_type=file_type,
            key_pointer=key_pointer,
            blocks_used=blocks_used,
            eof=eofw | (eof3 << 16),
            date_time=date_time,
            version=version,
            min_version=min_version,
            access=access,
            aux_type=aux_type,
            last_mod=last_mod,
            header_pointer=header_pointer,
            **asdict(d)
        )


assert VolumeDirectoryHeaderEntry._size == entry_length
assert SubdirectoryHeaderEntry._size == entry_length
assert FileEntry._size == entry_length


from typing import ClassVar, List, Optional, Self
from dataclasses import dataclass, asdict
import struct
from bitstring import BitArray

from .globals import entry_length, entries_per_block
from .metadata import FileEntry, VolumeDirectoryHeaderEntry, SubdirectoryHeaderEntry


@dataclass(kw_only=True)
class AbstractBlock:
    @classmethod
    def unpack(kls, buf) -> Self:
        return NotImplemented


@dataclass(kw_only=True)
class DataBlock:
    data: bytes

    @classmethod
    def unpack(kls, buf) -> Self:
        return DataBlock(data=buf)


@dataclass(kw_only=True)
class DirectoryBlock(AbstractBlock):
    _struct: str = "<HH"
    _size: ClassVar = 4

    prev_pointer: int
    next_pointer: int
    file_entries: List[FileEntry]

    def __post_init__(self):
        self.file_entries = [
            d if isinstance(d, FileEntry) else FileEntry(**d)
            for d in self.file_entries
        ]

    def __repr__(self):
        return f"<{self.prev_pointer:d}:{self.next_pointer:d}>\n" + (
            "\n".join(repr(f) for f in self.file_entries)
        )

    @classmethod
    def unpack(kls, buf, skip=0) -> Self:
        (
            prev_pointer, next_pointer
        ) = struct.unpack(kls._struct, buf[:kls._size])
        file_entries = []
        for k in range(skip, entries_per_block):
            off = kls._size + k * entry_length
            file_entries.append(FileEntry.unpack(buf[off:off+entry_length]))
        return kls(
            prev_pointer=prev_pointer,
            next_pointer=next_pointer,
            file_entries=file_entries,
        )


@dataclass(kw_only=True)
class VolumeDirectoryKeyBlock(DirectoryBlock):
    volume_header: VolumeDirectoryHeaderEntry

    def __repr__(self):
        return repr(self.volume_header) + "\n" + super().__repr__()

    @classmethod
    def unpack(kls, buf) -> Self:
        v = DirectoryBlock.unpack(buf, skip=1)
        off = DirectoryBlock._size
        n = VolumeDirectoryHeaderEntry._size
        volume_header = VolumeDirectoryHeaderEntry.unpack(buf[off:off+n])
        return kls(volume_header=volume_header, **asdict(v))


@dataclass(kw_only=True)
class SubdirectoryKeyBlock(DirectoryBlock):
    subdirectory_header: SubdirectoryHeaderEntry

    @classmethod
    def unpack(kls, buf) -> Self:
        v = DirectoryBlock.unpack(buf, skip=1)
        off = DirectoryBlock._size
        n = SubdirectoryHeaderEntry._size
        subdirectory_header = SubdirectoryHeaderEntry.unpack(buf[off:off+n])
        return kls(subdirectory_header=subdirectory_header, **asdict(v))


@dataclass(kw_only=True)
class IndexBlock(AbstractBlock):
    """
    index blocks store 256 two byte block pointers, with the lsbs
    in bytes 0-255 and the msbs in bytes 256-511
    """
    block_pointers: List[int]

    @classmethod
    def unpack(kls, buf) -> Self:
        return IndexBlock(block_pointers=[
            lo + (hi<<8) for (lo, hi) in zip(buf[:256], buf[256:])
        ])


@dataclass(kw_only=True)
class BitmapBlock(AbstractBlock):
    """
    The volume bitmap stores one bit per volume block where 1 is free and 0 is used.
    Bits are stored in big-endian order, e.g. block 0 is represented in bit 7 of
    the first byte of the first bitmap block, and bit 0 of the last byte in
    the last bitmap block for a 32Mb volume (with 65535 blocks) is represents a block
    just past the end of the volume.
    """
    free_map: BitArray

    @classmethod
    def unpack(kls, buf) -> Self:
        return BitmapBlock(free_map=BitArray(buf))

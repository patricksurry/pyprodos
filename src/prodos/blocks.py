from typing import ClassVar, List, Self, Optional, Type, TypeVar
from dataclasses import dataclass
import struct
from bitarray import bitarray

from .globals import entry_length, entries_per_block, block_size
from .metadata import FileEntry, DirectoryHeaderEntry


HeaderT = TypeVar('HeaderT', bound=DirectoryHeaderEntry)


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
        return kls(data=buf)


@dataclass(kw_only=True)
class DirectoryBlock(AbstractBlock):
    _struct: str = "<HH"
    _size: ClassVar = 4

    prev_pointer: int
    next_pointer: int
    header_entry: Optional[DirectoryHeaderEntry] = None
    file_entries: List[FileEntry]

    def __post_init__(self):
        self.file_entries = [
            d if isinstance(d, FileEntry) else FileEntry(**d)
            for d in self.file_entries
        ]

    def __repr__(self):
        s = f"<{self.prev_pointer:d}:{self.next_pointer:d}>\n"
        if self.header_entry:
            s += f"{self.header_entry}\n"
        s += "\n".join(repr(f) for f in self.file_entries)
        return s

    def pack(self) -> bytes:
        data = struct.pack(DirectoryBlock._struct, self.prev_pointer, self.next_pointer)
        if self.header_entry:
            data += self.header_entry.pack()
        data += b''.join(e.pack() for e in self.file_entries)
        # each directory block has one unused byte since 4 + 13 * 39 = 511
        padding = block_size - 4 - entries_per_block * entry_length
        assert padding + len(data) == block_size, f"{padding} + {len(data)} != {block_size}"
        return data + bytes(padding)

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        return kls._unpack(buf)

    @classmethod
    def unpack_key_block(kls, buf: bytes, header_factory: Type[HeaderT]) -> Self:
        return kls._unpack(buf, header_factory)

    @classmethod
    def _unpack(kls, buf: bytes, header_factory: Optional[Type[HeaderT]]=None) -> Self:
        offset = kls._size
        (
            prev_pointer, next_pointer
        ) = struct.unpack(kls._struct, buf[:offset])
        header: Optional[HeaderT] = None
        if header_factory:
            header = header_factory.unpack(buf[offset:offset + entry_length])
            offset += entry_length

        file_entries = []
        for k in range(entries_per_block - (1 if header else 0)):
            file_entries.append(FileEntry.unpack(buf[offset:offset + entry_length]))
            offset += entry_length

        return kls(
            prev_pointer=prev_pointer,
            next_pointer=next_pointer,
            header_entry=header,
            file_entries=file_entries,
        )


@dataclass(kw_only=True)
class IndexBlock(AbstractBlock):
    """
    index blocks store 256 two byte block pointers, with the lsbs
    in bytes 0-255 and the msbs in bytes 256-511
    """
    block_pointers: List[int]

    @classmethod
    def unpack(kls, buf) -> Self:
        return kls(block_pointers=[
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
    free_map: bitarray

    def pack(self) -> bytes:
        return self.free_map.tobytes()

    @classmethod
    def unpack(kls, buf) -> Self:
        bits = bitarray()
        bits.frombytes(buf)
        return kls(free_map=bits)

from typing import ClassVar, Self, Optional
from dataclasses import dataclass
import struct
from bitarray import bitarray
import logging

from .globals import entry_length, entries_per_block, block_size
from .metadata import FileEntry, NamedEntry, StorageType, \
    DirectoryEntry, DirectoryHeaderEntry, VolumeDirectoryHeaderEntry, SubdirectoryHeaderEntry


@dataclass(kw_only=True)
class AbstractBlock:
    def pack(self) -> bytes:
        return NotImplemented

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        return NotImplemented


@dataclass(kw_only=True)
class DirectoryBlock(AbstractBlock):
    SIZE: ClassVar = 4
    _struct: str = "<HH"
    _header_factory: ClassVar[dict[StorageType, type[DirectoryHeaderEntry]]] = {
        StorageType.voldirhdr: VolumeDirectoryHeaderEntry,
        StorageType.subdirhdr: SubdirectoryHeaderEntry
    }

    prev_pointer: int
    next_pointer: int
    header_entry: DirectoryHeaderEntry | None = None
    file_entries: list[FileEntry]

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
        assert padding + len(data) == block_size, \
            f"DirectoryBlock.pack: bad padding {padding} + {len(data)} != {block_size}"
        return data + bytes(padding)

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        offset = cls.SIZE
        (
            prev_pointer, next_pointer
        ) = struct.unpack(cls._struct, buf[:offset])
        # check the start of the first entry to see if it's a header entry
        d = NamedEntry.unpack(buf[offset:offset + NamedEntry.SIZE])
        header: Optional[DirectoryEntry] = None
        header_factory = cls._header_factory.get(d.storage_type)
        if header_factory:
            header = header_factory.unpack(buf[offset:offset + entry_length])
            offset += entry_length

        file_entries: list[FileEntry] = []
        while len(file_entries) + (1 if header else 0) < entries_per_block:
            file_entries.append(FileEntry.unpack(buf[offset:offset + entry_length]))
            offset += entry_length

        if any(buf[offset:]):
            logging.warning("DirectoryBlock: non-zero bytes in padding")
        return cls(
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
    block_pointers: list[int]

    def pack(self) -> bytes:
        return bytes(
            [p & 0xff for p in self.block_pointers]
            + [p >> 8 for p in self.block_pointers]
            + [0]*(block_size - (len(self.block_pointers) << 1))
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        return cls(block_pointers=[
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
    def unpack(cls, buf: bytes) -> Self:
        bits = bitarray()
        bits.frombytes(buf)
        return cls(free_map=bits)

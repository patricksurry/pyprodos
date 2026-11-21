"""A disk image viewed as an array of 512-byte blocks, with an access log."""
import struct
from dataclasses import dataclass
from enum import StrEnum
from mmap import ACCESS_READ, ACCESS_WRITE, mmap
from pathlib import Path
from typing import ClassVar, Literal, NamedTuple, Self, TypeVar

from .blocks import AbstractBlock
from .errors import ProDOSError
from .globals import block_size


class DeviceFormat(StrEnum):
    prodos = "prodos"   # raw blocks in ProDOS order (.po)
    twomg = "2mg"       # ProDOS-order blocks after a 64 byte 2IMG header


DeviceMode = Literal['ro', 'rw']


BlockT = TypeVar('BlockT', bound=AbstractBlock)
AccessT = Literal['r', 'w', 'a', 'f']    # read, write, allocate, free


class AccessLogEntry(NamedTuple):
    access_type: AccessT
    block_index: int
    block_type: str


@dataclass(kw_only=True)
class TwoImgHeader:
    """
    Header of a .2mg disk image,
    see https://gswv.apple2.org.za/a2zine/Docs/DiskImage_2MG_Info.txt
    """
    SIZE: ClassVar = 64
    _struct: ClassVar = "<4s4sHHIIIIIIIII16x"
    magic: ClassVar = b'2IMG'
    prodos_order: ClassVar = 1

    creator: bytes = b'PYP8'
    version: int = 1
    image_format: int = prodos_order    # 0 = DOS order, 1 = ProDOS order, 2 = nibbles
    flags: int = 0
    blocks: int = 0
    data_offset: int = SIZE
    data_length: int = 0
    comment_offset: int = 0
    comment_length: int = 0
    creator_offset: int = 0
    creator_length: int = 0

    def pack(self) -> bytes:
        return struct.pack(
            self._struct, self.magic, self.creator, self.SIZE, self.version,
            self.image_format, self.flags, self.blocks, self.data_offset, self.data_length,
            self.comment_offset, self.comment_length, self.creator_offset, self.creator_length,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> Self:
        (
            magic, creator, header_size, version, image_format, flags, blocks,
            data_offset, data_length, comment_offset, comment_length, creator_offset, creator_length,
        ) = struct.unpack(cls._struct, buf[:cls.SIZE])
        if magic != cls.magic:
            raise ProDOSError("Not a 2IMG disk image")
        if image_format != cls.prodos_order:
            raise ProDOSError(f"Only ProDOS-order 2IMG images are supported, not format {image_format}")
        return cls(
            creator=creator,
            version=version,
            image_format=image_format,
            flags=flags,
            blocks=blocks,
            # images from earlier pyprodos versions left these zero
            data_offset=data_offset or header_size,
            data_length=data_length,
            comment_offset=comment_offset,
            comment_length=comment_length,
            creator_offset=creator_offset,
            creator_length=creator_length,
        )


class BlockDevice:
    """
    A disk image file viewed as numbered 512-byte blocks.
    Every read, write, allocation and free is recorded in an access log
    so you can watch how the higher level routines use the device.
    """
    def __init__(self, source: Path, mode: DeviceMode='ro'):
        self.source = source
        self.mode: DeviceMode = mode
        self._file = open(source, 'r+b' if mode == 'rw' else 'rb', buffering=0)
        self._mm = mmap(self._file.fileno(), 0, access=ACCESS_WRITE if mode == 'rw' else ACCESS_READ)
        self._access_log: list[AccessLogEntry] = []

        self.offset = 0
        length = len(self._mm)
        if source.suffix.lower() == '.2mg':
            header = TwoImgHeader.unpack(self._mm[:TwoImgHeader.SIZE])
            self.offset = header.data_offset
            length = header.data_length or length - self.offset

        if length % block_size:
            self.close()
            raise ProDOSError(f"Volume {source} size {length} is not a multiple of {block_size} bytes")
        self.total_blocks = length // block_size

    def __repr__(self):
        return f"BlockDevice on {self.source} contains {self.total_blocks} total blocks"

    @classmethod
    def create(cls, dest: Path, total_blocks: int, format: DeviceFormat = DeviceFormat.prodos) -> Self:
        """Create a zero-filled image and open it for writing"""
        if dest.exists():
            raise ProDOSError(f"{dest} already exists")
        length = total_blocks * block_size
        if format == DeviceFormat.twomg:
            prefix = TwoImgHeader(blocks=total_blocks, data_length=length).pack()
        else:
            prefix = b""
        dest.write_bytes(prefix + bytes(length))
        return cls(dest, mode='rw')

    def close(self):
        if not self._mm.closed:
            if self.mode == 'rw':
                self._mm.flush()
            self._mm.close()
        self._file.close()

    def read_block(self, block_index: int, block_type: str='') -> bytes:
        start = self._start(block_index)
        self.log_access('r', block_index, block_type)
        return self._mm[start:start+block_size]

    def write_block(self, block_index: int, data: bytes, block_type: str=''):
        assert len(data) == block_size, f"write_block: expected {block_size} bytes, got {len(data)}"
        if self.mode != 'rw':
            raise ProDOSError(f"{self.source} is open read-only")
        start = self._start(block_index)
        self.log_access('w', block_index, block_type)
        self._mm[start:start+block_size] = data

    def read_typed_block(self, block_index: int, factory: type[BlockT]) -> BlockT:
        return factory.unpack(self.read_block(block_index, block_type=factory.__name__))

    def write_typed_block(self, block_index: int, block: AbstractBlock):
        self.write_block(block_index, block.pack(), block_type=type(block).__name__)

    def _start(self, block_index: int) -> int:
        if not 0 <= block_index < self.total_blocks:
            raise ProDOSError(f"Block {block_index} is outside the volume (0-{self.total_blocks - 1})")
        return self.offset + block_index * block_size

    # --- access log

    def log_access(self, access_type: AccessT, block_index: int, block_type: str=''):
        self._access_log.append(AccessLogEntry(access_type, block_index, block_type))

    def mark_session(self) -> int:
        return len(self._access_log)

    def get_access_log(self, access_types: str, mark: int=0) -> list[int]:
        return [entry.block_index for entry in self._access_log[mark:] if entry.access_type in access_types]

    def get_typed_access_log(self, access_types: str, mark: int=0) -> list[tuple[int, str]]:
        """Get access log entries with block types for given access types."""
        return [(entry.block_index, entry.block_type) for entry in self._access_log[mark:] if entry.access_type in access_types]

    def write_access_log(self, log_path: Path):
        """Write access log to file."""
        with open(log_path, 'w') as f:
            for entry in self._access_log:
                f.write(f"{entry.access_type} {entry.block_index:04x} {entry.block_type}\n")

    def dump_access_log(self) -> str:
        return '\n'.join(
            ' '.join(entry.access_type + f"{entry.block_index:<4x}".upper() + (f":{entry.block_type}" if entry.block_type else "")
                     for entry in self._access_log[k:k+12])
             for k in range(0, len(self._access_log), 12)
        )

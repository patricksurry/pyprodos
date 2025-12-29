import logging
import struct
from enum import Enum
from mmap import ACCESS_READ, ACCESS_WRITE, mmap
from os import path
from pathlib import Path
from typing import Literal, NamedTuple, Optional, Type, TypeVar

from bitarray import bitarray

from .blocks import AbstractBlock, BitmapBlock
from .globals import block_size, block_size_bits


class DeviceFormat(str, Enum):
    prodos = "prodos"
    twomg = "2mg"


DeviceMode = Literal['ro', 'rw']


BlockT = TypeVar('BlockT', bound=AbstractBlock)
AccessT = Literal['r', 'w', 'a', 'f']


class AccessLogEntry(NamedTuple):
    access_type: AccessT
    block_index: int
    block_type: str


class BlockDevice:
    _struct_2mg = "<4s4sHHI48x"

    def __init__(self, source: Path, mode: DeviceMode='ro', bit_map_pointer: Optional[int]=None):
        self.source = source
        access = ACCESS_WRITE if mode == 'rw' else ACCESS_READ
        f = open(source, 'r+b' if mode == 'rw' else 'rb', buffering=0)
        self.mm = mmap(f.fileno(), 0, access=access)
        self.skip = 0
        self._access_log: list[AccessLogEntry] = []

        if source.suffix.lower() == '.2mg':
            # 2mg files contain a 64 byte header before the volume data
            # see https://gswv.apple2.org.za/a2zine/Docs/DiskImage_2MG_Info.txt
            (
                ident,
                creator,    # type: ignore  # not currently used
                size,
                version,    # type: ignore  # not currently used
                format
            ) = struct.unpack_from(self._struct_2mg, self.mm)
            assert ident == b'2IMG' and format == 1, "BlockDevice: Can't handle non-prodos .2mg volume"
            self.skip = size

        n = len(self.mm)
        n -= self.skip
        assert n & (block_size - 1) == 0,\
            f"BlockDevice: Expected volume {source} size {n} excluding {self.skip} byte prefix to be multiple of {block_size} bytes"
        self.total_blocks = n >> block_size_bits

        self.bit_map_pointer = bit_map_pointer     # updated via set_free_map below
        k = block_size_bits + 3
        self.free_map = bitarray(self.bitmap_blocks << k)
        self.free_map[:self.total_blocks] = 1

    def __del__(self):
        if self.get_access_log('af'):
            self.write_free_map()
        self.mm.flush()

    def __repr__(self):
        used = 1 - self.blocks_free/self.total_blocks
        return f"BlockDevice on {self.source} contains {self.total_blocks} total blocks, {self.blocks_free} free ({used:.0%} used)"

    @classmethod
    def create(cls,
            dest: Path,
            total_blocks: int,
            bit_map_pointer: int,
            format: DeviceFormat = DeviceFormat.prodos,
        ):
        if format == DeviceFormat.twomg:
            prefix = struct.pack(cls._struct_2mg, b'2IMG', b'PYP8', 64, 1, 1)
        else:
            prefix = bytes()

        assert not path.exists(dest), f"Device.create: {dest} already exists!"
        open(dest, 'wb').write(prefix + bytes([0]*total_blocks*block_size))
        return BlockDevice(dest, mode='rw', bit_map_pointer=bit_map_pointer)

    @property
    def blocks_free(self) -> int:
        return sum(self.free_map)

    @property
    def bitmap_blocks(self) -> int:
        """Number of blocks used by the volume bitmap."""
        k = block_size_bits + 3
        return ((self.total_blocks - 1) >> k) + 1

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

    def dump_access_log(self):
        return '\n'.join(
            ' '.join(entry.access_type + f"{entry.block_index:<4x}".upper() + (f":{entry.block_type}" if entry.block_type else "")
                     for entry in self._access_log[k:k+12])
             for k in range(0, len(self._access_log), 12)
        )

    def read_typed_block(self, block_index: int, factory: Type[BlockT], unsafe: bool=False) -> BlockT:
        return factory.unpack(self.read_block(block_index, unsafe, block_type=factory.__name__))

    def read_block(self, block_index: int, unsafe: bool=False, block_type: str='') -> bytes:
        assert unsafe or not self.free_map[block_index], f"read_block({block_index}) on free block"
        self._access_log.append(AccessLogEntry('r', block_index, block_type))
        start = block_index * block_size + self.skip
        return self.mm[start:start+block_size]

    def write_typed_block(self, block_index: int, block: AbstractBlock):
        self.write_block(block_index, block.pack(), block_type=type(block).__name__)

    def write_block(self, block_index: int, data: bytes, block_type: str=''):
        self.free_map[block_index] = False
        self._access_log.append(AccessLogEntry('w', block_index, block_type))
        start = block_index*block_size + self.skip
        self.mm[start:start+block_size] = data

    def allocate_block(self) -> int:
        block_index = self._next_free_block()
        assert block_index is not None, "allocate_block: Device full!"
        self.free_map[block_index] = False
        self._access_log.append(AccessLogEntry('a', block_index, ''))
        return block_index

    def free_block(self, block_index: int):
        assert not self.free_map[block_index], f"free_block({block_index}): already free"
        self.write_block(block_index, bytes(block_size))
        self.free_map[block_index] = True
        self._access_log.append(AccessLogEntry('f', block_index, ''))

    def reset_free_map(self, block_index: int):
        self.bit_map_pointer = block_index
        k = block_size_bits + 3
        for i in range(self.bitmap_blocks):
            b = self.read_typed_block(i + block_index, BitmapBlock, unsafe=True)
            self.free_map[i<<k : (i+1)<<k] = b.free_map
        logging.debug(f"Read {self.bitmap_blocks} bitmask blocks with {len(self.free_map)} bits covering {self.total_blocks} volume blocks")
        assert self.total_blocks <= len(self.free_map) < self.total_blocks + (block_size << 3), \
            f"reset_free_map: unexpected free_map length {len(self.free_map)} for {self.total_blocks} blocks"
        if any(self.free_map[:block_index+self.bitmap_blocks]):
            logging.warning("bitmap shows free space in volume prologue")
        if any(self.free_map[self.total_blocks:]):
            logging.warning("bitmap shows free space past end of volume")

    def write_free_map(self):
        assert self.bit_map_pointer is not None, "Device bit_map_pointer not set"
        start = self.bit_map_pointer
        self.free_map[start:start+self.bitmap_blocks] = False    # mark self used
        bits_per_block = 1 << (block_size_bits + 3)
        for i in range(self.bitmap_blocks):
            start = i*bits_per_block
            blk = BitmapBlock(free_map=self.free_map[start:start+bits_per_block])
            self.write_typed_block(i + self.bit_map_pointer, blk)

    def _next_free_block(self) -> Optional[int]:
        return next(
            (i for (i, free) in enumerate(self.free_map) if free),
            None
        )
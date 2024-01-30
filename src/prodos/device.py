from typing import Tuple, List, Literal, Optional, Type, TypeVar
import logging
from bitarray import bitarray
from mmap import mmap, ACCESS_READ, ACCESS_WRITE
from os import path
import struct
import atexit
from enum import Enum

from .globals import block_size, block_size_bits
from .blocks import AbstractBlock, BitmapBlock


class DeviceFormat(str, Enum):
    prodos = "prodos"
    two2mg = "2mg"


BlockT = TypeVar('BlockT', bound=AbstractBlock)
AccessT = Literal['r', 'w', 'a', 'f']


class BlockDevice:
    _struct_2mg = "<4s4sHHI48x"

    def __init__(self, fname: str, mode: Literal['ro', 'rw']='ro', bit_map_pointer: Optional[int]=None):
        self.fname = fname
        access = ACCESS_WRITE if mode == 'rw' else ACCESS_READ
        f = open(fname, 'r+b' if mode == 'rw' else 'rb')
        self.mm = mmap(f.fileno(), 0, access=access)
        #TODO mmap
        self.skip = 0
        self._access_log: List[Tuple[AccessT, int]] = []

        # see https://gswv.apple2.org.za/a2zine/Docs/DiskImage_2MG_Info.txt
        if path.splitext(fname)[1].lower() == '.2mg':
            (ident, creator, size, version, format) = struct.unpack_from(self._struct_2mg, self.mm)
            assert ident == b'2IMG' and format == 1, "Can't handle non-prodos .2mg volume"
            self.skip = size

        n = len(self.mm)
        n -= self.skip
        assert n & (block_size - 1) == 0,\
            f"Expected volume {fname} size {n} excluding {self.skip} byte prefix to be multiple of {block_size} bytes"
        self.total_blocks = n >> block_size_bits

        self.bit_map_pointer = bit_map_pointer     # updated via set_free_map below
        k = block_size_bits + 3
        bit_map_blocks =  ((self.total_blocks-1) >> k) + 1

        self.free_map = bitarray(bit_map_blocks << k)
        self.free_map[:self.total_blocks] = 1

        atexit.register(self.flush)

    def flush(self):
        if self.get_access_log('af'):
            self.write_free_map()

    def __repr__(self):
        used = 1 - self.blocks_free/self.total_blocks
        return f"BlockDevice on {self.fname} contains {self.total_blocks} total blocks, {self.blocks_free} free ({used:.0%} used)"

    @classmethod
    def create(kls,
            fname: str,
            total_blocks: int,
            bit_map_pointer: int,
            format: DeviceFormat = DeviceFormat.prodos,
        ):
        if format == '2mg':
            prefix = struct.pack(kls._struct_2mg, b'2IMG', b'PYP8', 64, 1, 1)
        else:
            prefix = bytes()

        assert not path.exists(fname), f"Device.create: {fname} already exists!"
        open(fname, 'wb').write(prefix + bytes([0]*total_blocks*block_size))
        return BlockDevice(fname, mode='rw', bit_map_pointer=bit_map_pointer)

    @property
    def blocks_free(self) -> int:
        return sum(self.free_map)

    def mark_session(self) -> int:
        return len(self._access_log)

    def get_access_log(self, access_types: str, mark=0):
        return [i for (t, i) in self._access_log[mark:] if t in access_types]

    def read_block_type(self, block_index: int, factory: Type[BlockT]) -> BlockT:
        return factory.unpack(self.read_block(block_index))

    def read_block(self, block_index: int) -> bytes:
        self._access_log.append(('r', block_index))
        start = block_index * block_size + self.skip
        return self.mm[start:start+block_size]

    def write_block(self, block_index: int, data: bytes):
        self.free_map[block_index] = False
        self._access_log.append(('w', block_index))
        start = block_index*block_size + self.skip
        self.mm[start:start+block_size] = data

    def allocate_block(self) -> int:
        block_index = self._next_free_block()
        assert block_index is not None, "allocate_block: Device full!"
        self.free_map[block_index] = False
        self._access_log.append(('a', block_index))
        return block_index

    def free_block(self, block_index):
        self.free_map[block_index] = True
        self._access_log.append(('f', block_index))

    def reset_free_map(self, block_index):
        self.bit_map_pointer = block_index
        k = block_size_bits + 3
        n = len(self.free_map) >> k
        for i in range(n):
            b = self.read_block_type(i + block_index, BitmapBlock)
            self.free_map[i<<k : (i+1)<<k] = b.free_map
        logging.debug(f"Read {n} bitmask blocks with {len(self.free_map)} bits covering {self.total_blocks} volume blocks")
        assert self.total_blocks <= len(self.free_map) < self.total_blocks + (block_size << 3)
        if any(self.free_map[:block_index+n]):
            logging.warn("bitmap shows free space in volume prologue")
        if any(self.free_map[self.total_blocks:]):
            logging.warn("bitmap shows free space past end of volume")

    def write_free_map(self):
        assert self.bit_map_pointer is not None, "Device bit_map_pointer not set"
        start = self.bit_map_pointer
        n = len(self.free_map) >> (block_size_bits + 3)
        self.free_map[start:start+n] = False    # mark self used
        bits_per_block = 1 << (block_size_bits + 3)
        for i in range(n):
            start = i*bits_per_block
            blk = BitmapBlock(free_map=self.free_map[start:start+bits_per_block])
            self.write_block(i + self.bit_map_pointer, blk.pack())

    def _next_free_block(self) -> Optional[int]:
        return next(
            (i for (i, free) in enumerate(self.free_map) if free),
            None
        )
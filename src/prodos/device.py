from typing import Tuple, List, Literal, Optional, Type, TypeVar
import logging
from bitstring import BitArray
from os import path
import struct

from .globals import block_size, block_size_bits
from .blocks import AbstractBlock, BitmapBlock


BlockT = TypeVar('BlockT', bound=AbstractBlock)

AccessT = Literal['r', 'w', 'a', 'f']

class BlockDevice:
    def __init__(self, fname: str):
        self.fname = fname
        self.f = open(fname,'rb')
        #TODO mmap
        self.skip = 0
        self.free_map = BitArray()
        self.access_log: List[Tuple[AccessT, int]] = []

        # see https://gswv.apple2.org.za/a2zine/Docs/DiskImage_2MG_Info.txt
        if path.splitext(fname)[1].lower() == '.2mg':
            prefix = self.f.read(16)
            (ident, creator, size, version, format) = struct.unpack("<4s4sHHI", prefix)
            assert ident == b'2IMG' and format == 1, "Can't handle non-prodos .2mg volume"
            self.skip = size

        n = path.getsize(fname)
        n -= self.skip
        assert n & (block_size - 1) == 0,\
            "Expected volume {fname} size {n} excluding {self.skip} byte prefix to be multiple of {block_size} bytes"
        self.total_blocks = n >> block_size_bits

    def __del__(self):
        if self.get_access_log('af'):
            #TODO write free_map
            pass

    def __repr__(self):
        used = 1 - self.blocks_free/self.total_blocks
        return f"BlockDevice on {self.fname} contains {self.total_blocks} total blocks, {self.blocks_free} free ({used:.0%} used)"

    @classmethod
    def create(kls,
            fname: str,
            total_blocks=65535,
            format: Literal['prodos', '2mg'] = 'prodos',
            #TODO mmap access readonly|write
            loader: Optional[bytes]=None ):
        #TODO other options
        open(fname, 'wb').write(bytes([0]*total_blocks*block_size))
        return BlockDevice(fname)

    @property
    def blocks_free(self) -> int:
        return sum(self.free_map)

    def mark_session(self) -> int:
        return len(self.access_log)

    def get_access_log(self, access_types: str, mark=0):
        return [i for (t, i) in self.access_log[mark:] if t in access_types]

    def read_block_type(self, block_index: int, factory: Type[BlockT]) -> BlockT:
        return factory.unpack(self.read_block(block_index))

    def read_block(self, block_index: int) -> bytes:
        self.f.seek(block_index * block_size + self.skip)
        self.access_log.append(('r', block_index))
        return self.f.read(block_size)

    def write_block(self, block_index: int, data: bytes):
        #TODO mmap write
        self.access_log.append(('w', block_index))

    def allocate_block(self) -> int:
        block_index = self._next_free_block()
        self.free_map[block_index] = False
        self.access_log.append(('a', block_index))
        return block_index

    def free_block(self, block_index) -> int:
        self.free_map[block_index] = True
        self.access_log.append(('f', block_index))

    def init_free_map(self, block_index) -> BitArray:
        n = ((self.total_blocks-1) >> (block_size_bits + 3)) + 1
        bits = BitArray()
        for i in range(block_index, block_index+n):
            b = self.read_block_type(i, BitmapBlock)
            bits += b.free_map
        logging.debug(f"Read {n} bitmask blocks with {bits.length} bits covering {self.total_blocks} volume blocks")
        assert self.total_blocks <= bits.length < self.total_blocks + (block_size << 3)
        if any(bits[:block_index+n]):
            logging.warn("bitmap shows free space in volume prologue")
        if any(bits[self.total_blocks:]):
            logging.warn("bitmap shows free space past end of volume")
        self.free_map = bits

    def _next_free_block(self) -> Optional[int]:
        return next(
            (i for (i, free) in enumerate(self.free_map) if free),
            None
        )
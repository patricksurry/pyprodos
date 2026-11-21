"""The volume bit map, which records which blocks are free."""
from typing import Self

from bitarray import bitarray

from .blocks import BitmapBlock
from .device import BlockDevice
from .errors import ProDOSError
from .globals import block_size

bits_per_block = block_size * 8     # each bit map block covers 4096 volume blocks


class Bitmap:
    """
    The volume bit map has one bit per block, 1 meaning free and 0 meaning used,
    stored most significant bit first in consecutive blocks starting at the
    volume header's bit_map_pointer.  Bits past the end of the volume are 0.

    It's a volume-level structure: the volume directory header says where it
    lives and how many blocks it covers.  Changes are kept in memory until flush().
    """
    def __init__(self, device: BlockDevice, pointer: int, total_blocks: int, free_map: bitarray):
        self.device = device
        self.pointer = pointer
        self.total_blocks = total_blocks
        self.free_map = free_map
        self._dirty = False

    @staticmethod
    def blocks_needed(total_blocks: int) -> int:
        return (total_blocks + bits_per_block - 1) // bits_per_block

    @classmethod
    def read(cls, device: BlockDevice, pointer: int, total_blocks: int) -> Self:
        free_map = bitarray()
        for i in range(cls.blocks_needed(total_blocks)):
            free_map += device.read_typed_block(pointer + i, BitmapBlock).free_map
        return cls(device, pointer, total_blocks, free_map)

    @classmethod
    def create(cls, device: BlockDevice, pointer: int, total_blocks: int) -> Self:
        """A bit map with every block free; the caller marks its system blocks used"""
        free_map = bitarray(cls.blocks_needed(total_blocks) * bits_per_block)
        free_map.setall(0)
        free_map[:total_blocks] = 1
        bitmap = cls(device, pointer, total_blocks, free_map)
        bitmap._dirty = True
        return bitmap

    @property
    def blocks(self) -> list[int]:
        """The blocks holding the bit map itself"""
        return list(range(self.pointer, self.pointer + self.blocks_needed(self.total_blocks)))

    @property
    def free_count(self) -> int:
        return self.free_map.count(1, 0, self.total_blocks)

    def is_free(self, block_index: int) -> bool:
        return bool(self.free_map[block_index])

    def mark_used(self, block_index: int):
        self.free_map[block_index] = 0
        self._dirty = True

    def allocate(self) -> int:
        """Claim the lowest numbered free block"""
        block_index = self.free_map.find(1, 0, self.total_blocks)
        if block_index < 0:
            raise ProDOSError("Volume is full")
        self.mark_used(block_index)
        self.device.log_access('a', block_index)
        return block_index

    def free(self, block_index: int):
        """
        Release a block.  ProDOS leaves the old contents in place,
        but we zero it so images stay clean and easy to compare.
        """
        assert not self.is_free(block_index), f"Bitmap.free: block {block_index} is already free"
        self.device.write_block(block_index, bytes(block_size))
        self.free_map[block_index] = 1
        self._dirty = True
        self.device.log_access('f', block_index)

    def flush(self):
        if not self._dirty:
            return
        for i, block_index in enumerate(self.blocks):
            chunk = self.free_map[i * bits_per_block:(i + 1) * bits_per_block]
            self.device.write_typed_block(block_index, BitmapBlock(free_map=chunk))
        self._dirty = False

from typing import List, Self
import logging
from dataclasses import dataclass, field

from .globals import block_size_bits
from .metadata import FileEntry
from .blocks import IndexBlock
from .device import BlockDevice


@dataclass(kw_only=True)
class SimpleFile:
    data: bytes
    block_list: List[int] = field(default_factory=list)

    def export(self, dst: str):
        open(dst, 'wb').write(self.data)

    @classmethod
    def read(kls, device: BlockDevice, entry: FileEntry) -> Self:
        assert entry.is_simple_file, f"read_simple_file: not simple file {entry}"

        mark = device.mark_session()
        data = kls._read_simple_file(
            device,
            block_index=entry.key_pointer,
            level=entry.storage_type,
            length=entry.eof
        )
        return kls(data=data, block_list=device.get_access_log('r', mark))

    @classmethod
    def _read_simple_file(kls, device: BlockDevice, block_index: int, level: int, length: int) -> bytes:
        assert level > 0
        # Each level adds 8 bits to the addressable file length
        level_bits = block_size_bits + ((level-1) << 3)
        assert length <= 1 << level_bits

        if block_index == 0:
            logging.debug("read_simple_file: sparse block")
            return bytes([0]*length)

        if level == 1:
            logging.debug(f"read_simple_file block {block_index} -> {length} bytes")
            return device.read_block(block_index)[:length]

        idx = device.read_block_type(block_index, IndexBlock)
        chunk_bits = level_bits - 8
        chunk_size = 1 << chunk_bits
        n = ((length-1) >> chunk_bits) + 1

        logging.debug(f"read_simple_file: reading {n} chunks of size {chunk_size} for level {level}")
        return b''.join(
            kls._read_simple_file(
                device,
                block_index=idx.block_pointers[j],
                level=level-1,
                length=min(length - j*chunk_size, chunk_size)
            )
            for j in range(0, n)
        )

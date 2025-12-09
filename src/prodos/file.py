from typing import Self
import logging
import re
import string
from dataclasses import dataclass, field

from .globals import block_size_bits, block_size
from .metadata import access_byte, FileEntry, StorageType
from .blocks import IndexBlock
from .device import BlockDevice
from .p8datetime import P8DateTime


def legal_path(path: str) -> str:
    return '/'.join([
        ('' if (part+'A')[0] in string.ascii_uppercase else 'A') +
        re.sub(r'[^./A-Z0-9]', '0', part)
        for part in path.upper().split('/')
    ])


@dataclass(kw_only=True)
class SimpleFile:
    """
    B.3.7 - Locating a Byte in a File

    Byte #        Byte 2             Byte 1            Byte 0

    bit #      7             0   7             0   7             0
              +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+
    MARK      |Index Number |Data Block Number|   Byte of Block   |
              +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+
    Used by:    Tree only    Tree and sapling      All three


    Figure B-9. A Sparse File

    Nil (0) block pointers represent blocks of zeros without allocating storage.

                       0 1 2
      key_pointer --> +--------------+
            Key_Block | | | |        |
                      +--------------+
                      |   |
            +---------+   +-------+                           EOF = $4000
            |                     |                                     |
            v Block $0   Block $1 v Block $2   Block $3       Block $1F v
       Data +-------------------------------------------+   +-----------+
     Blocks |          |  (nil)   |     | |  |  (nil)   |   |   (nil)   |
            +-------------------------------------------+   +-----------+
           $0         $1FF       $400    ^  $5FF
                                         |
                          Bytes $565..$568
    """
    device: BlockDevice
    file_name: str
    file_type: int = 0xff        #TODO needed for system file boot
    data: bytes
    block_list: list[int] = field(default_factory=list[int])

    def export(self, dst: str):
        open(dst, 'wb').write(self.data)

    def create_entry(self, header_pointer: int) -> FileEntry:
        n = len(self.data)
        if n <= block_size:
            t = StorageType.seedling
        elif n <= block_size << 8:
            t = StorageType.sapling
        else:
            t = StorageType.tree

        return FileEntry(
            storage_type = t,
            file_name = self.file_name,
            file_type = self.file_type,
            key_pointer = self.block_list[0],
            blocks_used = len(self.block_list),
            eof = n,
            date_time = P8DateTime.now(),
            version = 0,
            min_version = 0,
            access = access_byte(),
            aux_type = 0,
            last_mod = P8DateTime.now(),
            header_pointer = header_pointer,
        )

    def remove(self):
        assert self.block_list, "File.remove: can't remove unmapped file"
        while self.block_list:
            self.device.free_block(self.block_list.pop())

    def write(self) -> int:
        """
        write to a hierarchical file, returning storage level.
        Sparse files are handled with blocks of zeros encoded with block index 0.
        TODO this implementation writes completely empty sapling and tree files with
        no data blocks, whereas tech doc notes:

            The first data block of a standard file, be it a seedling,
            sapling, or tree file, is always allocated. Thus there is always
            a data block to be read in when the file is opened.

        This is probably a consequence of the create/set eof api.
        """
        if self.block_list:
            self.remove()

        level = 1
        chunk_size = block_size
        n = len(self.data)
        while chunk_size < n:
            chunk_size <<= 8
            level += 1

        self._write_simple_file(self.data, chunk_size)

        return level

    def _write_simple_file(self, data: bytes, chunk_size: int) -> int:
        # allocate block before writing sub-chunks
        index = self.device.allocate_block()
        self.block_list.append(index)

        n = len(data)
        assert n <= chunk_size, f"_write_simple_file: size {n} exceeds chunk {chunk_size}"
        if chunk_size == block_size:
            out = data + bytes(block_size-n)
        else:
            chunk_size >>= 8
            ixs: list[int] = []
            for off in range(0, n, chunk_size):
                blk = data[off:off+chunk_size]
                # sparse file skips write of empty blocks
                ixs.append(
                    self._write_simple_file(blk, chunk_size)
                    if any(blk)
                    else 0
                )
            out = IndexBlock(block_pointers=ixs).pack()
        self.device.write_block(index, out)
        return index

    @classmethod
    def from_entry(cls, device: BlockDevice, entry: FileEntry) -> Self:
        assert entry.is_simple_file, f"File.from_entry: not simple file {entry}"
        mark = device.mark_session()
        data = cls._read_simple_file(
            device,
            block_index=entry.key_pointer,
            level=entry.storage_type,
            length=entry.eof
        )
        return cls(
            device=device,
            file_name=entry.file_name,
            file_type=entry.file_type,
            data=data,
            block_list=device.get_access_log('r', mark)
        )

    @classmethod
    def _read_simple_file(cls, device: BlockDevice, block_index: int, level: int, length: int) -> bytes:
        assert level > 0, f"_read_simple_file: level {level} is not positive"
        # Each level adds 8 bits to the addressable file length
        level_bits = block_size_bits + ((level-1) << 3)
        assert length <= (1 << level_bits), f"_read_simple_file: length {length} exceeds chunk {1 << level_bits}"
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
            cls._read_simple_file(
                device,
                block_index=idx.block_pointers[j],
                level=level-1,
                length=min(length - j*chunk_size, chunk_size)
            )
            for j in range(0, n)
        )

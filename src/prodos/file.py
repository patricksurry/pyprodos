"""Files and the forks that store their contents."""
import re
import string
from dataclasses import dataclass, field, replace
from typing import Self

from .bitmap import Bitmap
from .blocks import ExtendedKeyBlock, IndexBlock
from .device import BlockDevice
from .errors import ProDOSError
from .globals import block_size, max_eof
from .metadata import FileEntry, FileType, StorageType, simple_file_types
from .p8datetime import P8DateTime


def legal_name(name: str) -> str:
    """Coerce a host file name to a legal ProDOS name"""
    name = re.sub(r'[^.A-Z0-9]', '0', name.upper())
    if name[:1] not in tuple(string.ascii_uppercase):
        name = 'A' + name
    return name[:15]


def legal_path(path: str) -> str:
    return '/'.join(legal_name(part) if part else '' for part in path.split('/'))


def guess_file_type(name: str) -> FileType:
    """ProDOS boots PRODOS and then the first *.SYSTEM file, both of type SYS"""
    name = name.upper()
    return FileType.SYS if name == 'PRODOS' or name.endswith('.SYSTEM') else FileType.BIN


def capacity(storage_type: StorageType) -> int:
    """Maximum bytes addressable by a seedling (512), sapling (128K) or tree (32M)"""
    return block_size << (8 * (storage_type - 1))


@dataclass(kw_only=True)
class Fork:
    """
    A sequence of bytes stored as a seedling, sapling or tree.

    A seedling is a single data block.  A sapling's key block is an index
    block pointing at up to 256 data blocks.  A tree's key block is a master
    index block pointing at up to 128 index blocks.

    B.3.7 - Locating a Byte in a File

    Byte #        Byte 2             Byte 1            Byte 0

    bit #      7             0   7             0   7             0
              +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+
    MARK      |Index Number |Data Block Number|   Byte of Block   |
              +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+ +-+-+-+-+-+-+-+-+
    Used by:    Tree only    Tree and sapling      All three


    Figure B-9. A Sparse File

    Nil (0) block pointers represent blocks of zeros without allocating storage.
    The first data block is always allocated.

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
    storage_type: StorageType
    key_pointer: int
    data: bytes
    index_blocks: list[int] = field(default_factory=list[int])
    data_blocks: list[int] = field(default_factory=list[int])

    @property
    def eof(self) -> int:
        return len(self.data)

    @property
    def blocks(self) -> list[int]:
        """Every block in the fork, which is what blocks_used counts"""
        return self.index_blocks + self.data_blocks

    @classmethod
    def read(cls, device: BlockDevice, storage_type: StorageType, key_pointer: int, eof: int) -> Self:
        if storage_type not in simple_file_types:
            raise ProDOSError(f"Unexpected storage type {storage_type:x} for a fork")
        # A damaged entry can claim more bytes than its storage type addresses; read what's there
        eof = min(eof, capacity(storage_type))
        index_blocks: list[int] = []
        data_blocks: list[int] = []

        def read_level(level: int, block_index: int, length: int) -> bytes:
            if block_index == 0:
                return bytes(length)        # sparse
            if level == StorageType.seedling:
                data_blocks.append(block_index)
                return device.read_block(block_index)[:length]
            index_blocks.append(block_index)
            pointers = device.read_typed_block(block_index, IndexBlock).block_pointers
            chunk = capacity(StorageType(level - 1))
            return b''.join(
                read_level(level - 1, pointers[j], min(chunk, length - j * chunk))
                for j in range((length + chunk - 1) // chunk)
            )

        data = read_level(storage_type, key_pointer, eof)
        return cls(storage_type=storage_type, key_pointer=key_pointer, data=data,
                   index_blocks=index_blocks, data_blocks=data_blocks)

    @classmethod
    def write(cls, device: BlockDevice, bitmap: Bitmap, data: bytes) -> Self:
        """Store data using the smallest storage type that fits, skipping zero blocks"""
        if len(data) > max_eof:
            raise ProDOSError(f"File size {len(data)} exceeds ProDOS maximum {max_eof}")
        storage_type = StorageType.seedling
        while capacity(storage_type) < len(data):
            storage_type = StorageType(storage_type + 1)
        index_blocks: list[int] = []
        data_blocks: list[int] = []

        def write_level(level: int, chunk: bytes, first: bool) -> int:
            if not first and not any(chunk):
                return 0                    # sparse
            block_index = bitmap.allocate()
            if level == StorageType.seedling:
                data_blocks.append(block_index)
                device.write_block(block_index, chunk.ljust(block_size, b'\0'))
            else:
                index_blocks.append(block_index)
                size = capacity(StorageType(level - 1))
                pointers = [
                    write_level(level - 1, chunk[off:off + size], first and off == 0)
                    for off in range(0, len(chunk), size)
                ]
                device.write_typed_block(block_index, IndexBlock(block_pointers=pointers))
            return block_index

        key_pointer = write_level(storage_type, data, True)
        return cls(storage_type=storage_type, key_pointer=key_pointer, data=data,
                   index_blocks=index_blocks, data_blocks=data_blocks)


@dataclass(kw_only=True)
class File:
    """
    A file is its directory entry plus the fork(s) holding its contents.

    A standard file (seedling, sapling or tree) has one fork, described by the
    entry itself.  An extended file (storage type 5, written by GS/OS) has an
    extended key block with a mini-entry for each of a data fork and a resource
    fork, see https://prodos8.com/docs/technote/25/
    """
    entry: FileEntry
    data_fork: Fork
    resource_fork: Fork | None = None
    extended_key: ExtendedKeyBlock | None = None

    @property
    def data(self) -> bytes:
        return self.data_fork.data

    @property
    def index_blocks(self) -> list[int]:
        """Index blocks of every fork, plus the extended key block if any"""
        blocks = [self.entry.key_pointer] if self.extended_key else []
        for fork in self.forks:
            blocks += fork.index_blocks
        return blocks

    @property
    def data_blocks(self) -> list[int]:
        return [b for fork in self.forks for b in fork.data_blocks]

    @property
    def blocks(self) -> list[int]:
        return self.index_blocks + self.data_blocks

    @property
    def forks(self) -> list[Fork]:
        return [self.data_fork] + ([self.resource_fork] if self.resource_fork else [])

    @classmethod
    def read(cls, device: BlockDevice, entry: FileEntry) -> Self:
        if entry.is_plain_file:
            fork = Fork.read(device, entry.storage_type, entry.key_pointer, entry.eof)
            return cls(entry=entry, data_fork=fork)
        if entry.storage_type == StorageType.extended:
            ext = device.read_typed_block(entry.key_pointer, ExtendedKeyBlock)
            data_fork, resource_fork = (
                Fork.read(device, f.storage_type, f.key_block, f.eof)
                for f in (ext.data_fork, ext.resource_fork)
            )
            return cls(entry=entry, data_fork=data_fork, resource_fork=resource_fork, extended_key=ext)
        raise ProDOSError(f"{entry.file_name} is not a file (storage type {entry.storage_type:x})")

    @classmethod
    def write(cls, device: BlockDevice, bitmap: Bitmap, entry: FileEntry, data: bytes) -> Self:
        """Write a standard file, filling in the entry's storage fields"""
        fork = Fork.write(device, bitmap, data)
        entry = replace(
            entry,
            storage_type=fork.storage_type,
            key_pointer=fork.key_pointer,
            blocks_used=len(fork.blocks),
            eof=fork.eof,
            last_mod=P8DateTime.now(),
        )
        return cls(entry=entry, data_fork=fork)

    def free(self, bitmap: Bitmap):
        for block_index in self.blocks:
            bitmap.free(block_index)

    def export(self, dst: str):
        """Write to a host file; an extended file becomes dst.data, dst.rsrc and dst.meta"""
        if not self.extended_key:
            with open(dst, 'wb') as f:
                f.write(self.data)
            return
        assert self.resource_fork
        for suffix, content in (
            ('.data', self.data),
            ('.rsrc', self.resource_fork.data),
            ('.meta', self.extended_key.pack()),
        ):
            with open(dst + suffix, 'wb') as f:
                f.write(content)

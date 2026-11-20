import pytest

from conftest import IMAGES
from prodos.errors import ProDOSError
from prodos.file import File, Fork, capacity, guess_file_type, legal_name, legal_path
from prodos.globals import block_size
from prodos.metadata import FileEntry, FileType, StorageType
from prodos.volume import Volume


@pytest.mark.parametrize('path,expected', [
    ('abc', 'ABC'),
    ('DEF', 'DEF'),
    ('0123_.f/7ab-,z', 'A01230.F/A7AB00Z'),
    ('/sys/x', '/SYS/X'),
])
def test_legal_path(path: str, expected: str):
    assert legal_path(path) == expected


def test_legal_name_truncates():
    assert legal_name('a_very_long_file_name.txt') == 'A0VERY0LONG0FIL'


def test_guess_file_type():
    assert guess_file_type('PRODOS') == FileType.SYS
    assert guess_file_type('basic.system') == FileType.SYS
    assert guess_file_type('README') == FileType.BIN


def test_capacity():
    assert capacity(StorageType.seedling) == 512
    assert capacity(StorageType.sapling) == 512 * 256
    assert capacity(StorageType.tree) == 512 * 256 * 256


@pytest.mark.parametrize('size,storage_type,index,data', [
    (0, StorageType.seedling, 0, 1),        # an empty file still has its first data block
    (1, StorageType.seedling, 0, 1),
    (512, StorageType.seedling, 0, 1),
    (513, StorageType.sapling, 1, 2),
    (512 * 256, StorageType.sapling, 1, 256),
    (512 * 256 + 1, StorageType.tree, 3, 257),
])
def test_fork_roundtrip(volume: Volume, size: int, storage_type: StorageType, index: int, data: int):
    content = bytes((i * 7 + 1) % 255 + 1 for i in range(size))   # no zero blocks
    fork = Fork.write(volume.device, volume.bitmap, content)
    assert fork.storage_type == storage_type
    assert (len(fork.index_blocks), len(fork.data_blocks)) == (index, data)
    again = Fork.read(volume.device, fork.storage_type, fork.key_pointer, fork.eof)
    assert again.data == content
    assert again.blocks == fork.blocks
    # free the blocks, which aren't referenced by any directory entry
    File(entry=FileEntry.new('X'), data_fork=fork).free(volume.bitmap)


def test_sparse_fork(volume: Volume):
    content = b'A' + bytes(10 * block_size) + b'Z'
    fork = Fork.write(volume.device, volume.bitmap, content)
    # index block, first data block (always allocated) and the last data block
    assert (len(fork.index_blocks), len(fork.data_blocks)) == (1, 2)
    assert Fork.read(volume.device, fork.storage_type, fork.key_pointer, fork.eof).data == content
    for b in fork.blocks:
        volume.bitmap.free(b)


def test_all_zero_fork_keeps_first_block(volume: Volume):
    fork = Fork.write(volume.device, volume.bitmap, bytes(4 * block_size))
    assert (len(fork.index_blocks), len(fork.data_blocks)) == (1, 1)
    for b in fork.blocks:
        volume.bitmap.free(b)


def test_fork_too_big(volume: Volume):
    with pytest.raises(ProDOSError, match="exceeds"):
        Fork.write(volume.device, volume.bitmap, bytes(0x1000000))


def test_extended_file():
    with Volume.open(IMAGES / "GSOSv6.0.1.po") as volume:
        entry = volume.root.find("GSHK")
        assert entry and entry.storage_type == StorageType.extended
        f = volume.read_file(entry)
        assert f.extended_key and f.resource_fork
        assert len(f.data) > 0 and len(f.resource_fork.data) > 0
        # blocks_used counts the extended key block plus both forks
        assert f.blocks[0] == entry.key_pointer
        assert len(f.blocks) == entry.blocks_used


def test_plain_file():
    with Volume.open(IMAGES / "GSOSv6.0.1.po") as volume:
        entry = volume.root.find("PRODOS")
        assert entry and entry.is_plain_file
        f = volume.read_file(entry)
        assert len(f.data) == entry.eof
        assert len(f.blocks) == entry.blocks_used
        assert f.resource_fork is None

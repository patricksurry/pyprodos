"""Tests for BlockDevice methods including access logging."""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from prodos.device import BlockDevice, DeviceFormat, AccessLogEntry
from prodos.blocks import BitmapBlock, DirectoryBlock
from prodos.volume import Volume
from prodos.globals import block_size


@pytest.fixture
def test_device() -> Iterator[BlockDevice]:
    """Create a test device with a basic volume structure."""
    with TemporaryDirectory() as tmpdir:
        img_path = Path(tmpdir) / "test.po"
        volume = Volume.create(img_path, "TEST", total_blocks=280)
        yield volume.device


@pytest.fixture
def empty_device() -> Iterator[BlockDevice]:
    """Create an empty device for low-level testing."""
    with TemporaryDirectory() as tmpdir:
        img_path = Path(tmpdir) / "empty.po"
        device = BlockDevice.create(
            dest=img_path,
            total_blocks=100,
            bit_map_pointer=6,
            format=DeviceFormat.prodos
        )
        yield device


def test_access_log_entry_namedtuple():
    """Test that AccessLogEntry is a proper namedtuple with correct fields."""
    entry = AccessLogEntry('r', 42, 'DirectoryBlock')

    # Test field access
    assert entry.access_type == 'r'
    assert entry.block_index == 42
    assert entry.block_type == 'DirectoryBlock'

    # Test tuple unpacking still works
    access_type, block_index, block_type_name = entry
    assert access_type == 'r'
    assert block_index == 42
    assert block_type_name == 'DirectoryBlock'

    # Test immutability
    with pytest.raises(AttributeError):
        entry.access_type = 'w'  # type: ignore


def test_read_typed_block_logs_block_type(test_device: BlockDevice):
    """Test that read_typed_block logs the block type in access log."""
    mark = test_device.mark_session()

    # Read a directory block
    blk = test_device.read_typed_block(2, DirectoryBlock, unsafe=True)
    assert isinstance(blk, DirectoryBlock)

    # Check the access log
    log_entries = test_device._access_log[mark:]
    assert len(log_entries) == 1
    assert log_entries[0].access_type == 'r'
    assert log_entries[0].block_index == 2
    assert log_entries[0].block_type == 'DirectoryBlock'


def test_write_typed_block_logs_block_type(empty_device: BlockDevice):
    """Test that write_typed_block logs the block type in access log."""
    mark = empty_device.mark_session()

    # Create and write a bitmap block
    from bitarray import bitarray
    bits = bitarray(block_size * 8)
    bits[:] = 1
    blk = BitmapBlock(free_map=bits)

    empty_device.write_typed_block(10, blk)

    # Check the access log
    log_entries = empty_device._access_log[mark:]
    assert len(log_entries) == 1
    assert log_entries[0].access_type == 'w'
    assert log_entries[0].block_index == 10
    assert log_entries[0].block_type == 'BitmapBlock'


def test_write_block_without_type(empty_device: BlockDevice):
    """Test that write_block without type logs empty string."""
    mark = empty_device.mark_session()

    # Write raw bytes
    data = bytes(block_size)
    empty_device.write_block(10, data)

    # Check the access log
    log_entries = empty_device._access_log[mark:]
    assert len(log_entries) == 1
    assert log_entries[0].access_type == 'w'
    assert log_entries[0].block_index == 10
    assert log_entries[0].block_type == ''


def test_write_block_with_type(empty_device: BlockDevice):
    """Test that write_block can accept an explicit block_type parameter."""
    mark = empty_device.mark_session()

    # Write raw bytes with explicit type
    data = bytes(block_size)
    empty_device.write_block(10, data, block_type='CustomBlock')

    # Check the access log
    log_entries = empty_device._access_log[mark:]
    assert len(log_entries) == 1
    assert log_entries[0].access_type == 'w'
    assert log_entries[0].block_index == 10
    assert log_entries[0].block_type == 'CustomBlock'


def test_allocate_block_logs_allocation(empty_device: BlockDevice):
    """Test that allocate_block logs allocation to access log."""
    mark = empty_device.mark_session()

    block_idx = empty_device.allocate_block()

    # Check the access log
    log_entries = empty_device._access_log[mark:]
    assert len(log_entries) == 1
    assert log_entries[0].access_type == 'a'
    assert log_entries[0].block_index == block_idx
    assert log_entries[0].block_type == ''


def test_free_block_logs_free(empty_device: BlockDevice):
    """Test that free_block logs free operation to access log."""
    # First allocate a block
    block_idx = empty_device.allocate_block()
    mark = empty_device.mark_session()

    # Now free it
    empty_device.free_block(block_idx)

    # Check the access log - should have write (zeroing) and free
    log_entries = empty_device._access_log[mark:]
    assert len(log_entries) >= 2

    # Last entry should be the free operation
    assert log_entries[-1].access_type == 'f'
    assert log_entries[-1].block_index == block_idx
    assert log_entries[-1].block_type == ''


def test_get_access_log_filters_by_type(empty_device: BlockDevice):
    """Test that get_access_log correctly filters by access type."""
    mark = empty_device.mark_session()

    # Perform various operations
    idx1 = empty_device.allocate_block()  # 'a'
    empty_device.write_block(idx1, bytes(block_size))  # 'w'
    empty_device.read_block(idx1, unsafe=True)  # 'r'
    idx2 = empty_device.allocate_block()  # 'a'
    empty_device.free_block(idx1)  # 'w', 'f'

    # Filter by different types
    reads = empty_device.get_access_log('r', mark)
    writes = empty_device.get_access_log('w', mark)
    allocations = empty_device.get_access_log('a', mark)
    frees = empty_device.get_access_log('f', mark)

    assert len(reads) == 1
    assert reads[0] == idx1

    assert len(allocations) == 2
    assert allocations == [idx1, idx2]

    assert len(frees) == 1
    assert frees[0] == idx1

    # Writes include explicit write plus write during free_block
    assert idx1 in writes


def test_get_typed_access_log_returns_block_types(test_device: BlockDevice):
    """Test that get_typed_access_log returns (block_index, block_type) tuples."""
    mark = test_device.mark_session()

    # Read different types of blocks
    test_device.read_typed_block(2, DirectoryBlock, unsafe=True)

    # Get typed log
    typed_reads = test_device.get_typed_access_log('r', mark)

    assert len(typed_reads) == 1
    assert typed_reads[0] == (2, 'DirectoryBlock')


def test_dump_access_log_format(empty_device: BlockDevice):
    """Test that dump_access_log produces correctly formatted output."""
    # Perform some operations
    idx = empty_device.allocate_block()
    empty_device.write_typed_block(idx, BitmapBlock(free_map=empty_device.free_map[:block_size*8]))

    dump = empty_device.dump_access_log()

    # Check that dump contains access types and block indices
    assert 'a' in dump  # allocate (lowercase)
    assert 'w' in dump  # write (lowercase)
    assert 'BitmapBlock' in dump  # block type

    # Check hex formatting (block indices appear as hex)
    # The format is like "a0    w0   :BitmapBlock"
    assert '0' in dump  # should contain block index in hex


def test_mark_session_tracks_position(empty_device: BlockDevice):
    """Test that mark_session allows filtering access log by time."""
    # Do some operations before mark
    idx1 = empty_device.allocate_block()

    mark = empty_device.mark_session()

    # Do operations after mark
    idx2 = empty_device.allocate_block()
    empty_device.write_block(idx2, bytes(block_size))

    # Get logs from mark
    allocations_from_mark = empty_device.get_access_log('a', mark)

    # Should only see allocations after the mark
    assert idx2 in allocations_from_mark
    assert idx1 not in allocations_from_mark


def test_write_typed_block_round_trip(empty_device: BlockDevice):
    """Test that data written with write_typed_block can be read back."""
    from bitarray import bitarray

    # Create a bitmap block with specific pattern
    bits = bitarray(block_size * 8)
    bits[:] = 0
    bits[0:100] = 1  # Mark first 100 bits as free

    original_block = BitmapBlock(free_map=bits)

    # Write it
    empty_device.write_typed_block(20, original_block)

    # Read it back
    read_block = empty_device.read_typed_block(20, BitmapBlock, unsafe=True)

    # Compare
    assert read_block.free_map == original_block.free_map


def test_device_create_formats(tmp_path: Path):
    """Test creating devices in different formats."""
    # Test ProDOS format
    prodos_path = tmp_path / "test.po"
    device_po = BlockDevice.create(
        dest=prodos_path,
        total_blocks=280,
        bit_map_pointer=6,
        format=DeviceFormat.prodos
    )
    assert prodos_path.exists()
    assert prodos_path.stat().st_size == 280 * block_size
    assert device_po.total_blocks == 280

    # Test 2MG format
    twomg_path = tmp_path / "test.2mg"
    device_2mg = BlockDevice.create(
        dest=twomg_path,
        total_blocks=280,
        bit_map_pointer=6,
        format=DeviceFormat.twomg
    )
    assert twomg_path.exists()
    assert twomg_path.stat().st_size == 280 * block_size + 64  # 2MG has 64-byte header
    assert device_2mg.total_blocks == 280


def test_free_map_operations(empty_device: BlockDevice):
    """Test that free map is correctly maintained."""
    initial_free = empty_device.blocks_free

    # Allocate a block
    idx = empty_device.allocate_block()
    assert empty_device.blocks_free == initial_free - 1
    assert not empty_device.free_map[idx]

    # Free the block
    empty_device.free_block(idx)
    assert empty_device.blocks_free == initial_free
    assert empty_device.free_map[idx]


def test_write_free_map_uses_typed_blocks(empty_device: BlockDevice):
    """Test that write_free_map uses write_typed_block for logging."""
    # Modify free map
    empty_device.allocate_block()
    empty_device.allocate_block()

    mark = empty_device.mark_session()

    # Write the free map
    empty_device.write_free_map()

    # Check that BitmapBlock types were logged
    typed_writes = empty_device.get_typed_access_log('w', mark)

    # Should have written bitmap blocks
    assert len(typed_writes) > 0
    for _, block_type in typed_writes:
        assert block_type == 'BitmapBlock'

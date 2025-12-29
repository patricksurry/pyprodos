"""Tests for ProDOS block types: Directory, Index, Bitmap, and Extended blocks."""
from pathlib import Path

from bitarray import bitarray

from prodos.blocks import (
    BitmapBlock,
    DirectoryBlock,
    ExtendedKeyBlock,
    IndexBlock
)
from prodos.metadata import (
    ExtendedForkEntry,
    FileEntry,
    StorageType,
    SubdirectoryHeaderEntry,
    VolumeDirectoryHeaderEntry
)

# ===== ExtendedKeyBlock Tests =====

def test_extended_key_block_round_trip():
    """Test pack/unpack round-trip with synthetic data."""
    data_fork = ExtendedForkEntry(
        storage_type=StorageType.sapling,
        key_block=100,
        blocks_used=10,
        eof=4096,
        finder_info=b'\x00' * 36
    )

    resource_fork = ExtendedForkEntry(
        storage_type=StorageType.seedling,
        key_block=200,
        blocks_used=1,
        eof=256,
        finder_info=b'\x00' * 36
    )

    ext_block = ExtendedKeyBlock(data_fork=data_fork, resource_fork=resource_fork)

    # Test pack
    packed = ext_block.pack()
    assert len(packed) == 512, "Packed block should be 512 bytes"

    # Test unpack
    unpacked = ExtendedKeyBlock.unpack(packed)
    assert unpacked.data_fork.storage_type == StorageType.sapling
    assert unpacked.data_fork.key_block == 100
    assert unpacked.data_fork.blocks_used == 10
    assert unpacked.data_fork.eof == 4096

    assert unpacked.resource_fork.storage_type == StorageType.seedling
    assert unpacked.resource_fork.key_block == 200
    assert unpacked.resource_fork.blocks_used == 1
    assert unpacked.resource_fork.eof == 256

    # Verify round-trip
    assert packed == unpacked.pack(), "Round-trip should produce identical data"


def test_extended_key_block_real_data():
    """Test with real extended key block from GS/OS disk image."""
    # This is block 478 from GSOSv6.0.1.po (file: FOCUSDRIVER)
    test_data_path = Path(__file__).parent / "data" / "extended_key_block_478.bin"

    with open(test_data_path, 'rb') as f:
        block_data = f.read()

    assert len(block_data) == 512

    # Unpack the real block
    ext_block = ExtendedKeyBlock.unpack(block_data)

    # Verify the known values from FOCUSDRIVER
    assert ext_block.data_fork.storage_type == StorageType.sapling
    assert ext_block.data_fork.key_block == 481
    assert ext_block.data_fork.blocks_used == 16
    assert ext_block.data_fork.eof == 7247

    assert ext_block.resource_fork.storage_type == StorageType.sapling
    assert ext_block.resource_fork.key_block == 496
    assert ext_block.resource_fork.blocks_used == 3
    assert ext_block.resource_fork.eof == 945

    # Test round-trip with real data
    repacked = ext_block.pack()
    assert repacked == block_data, "Round-trip should reproduce original block exactly"


def test_extended_fork_entry_eof_encoding():
    """Test that 3-byte EOF is correctly encoded/decoded."""
    # Test maximum EOF value (24-bit)
    max_eof = 0xFFFFFF
    entry = ExtendedForkEntry(
        storage_type=StorageType.tree,
        key_block=500,
        blocks_used=256,
        eof=max_eof,
        finder_info=b'\x00' * 36
    )

    packed = entry.pack()
    unpacked = ExtendedForkEntry.unpack(packed)

    assert unpacked.eof == max_eof, "Maximum EOF should round-trip correctly"


def test_extended_fork_entry_finder_info():
    """Test that finder info is preserved correctly."""
    finder_data = b'FOCUSBB \x00\x01\x00\x00\x00\x00\x00\x00' + b'\x00' * 20

    entry = ExtendedForkEntry(
        storage_type=StorageType.seedling,
        key_block=123,
        blocks_used=1,
        eof=512,
        finder_info=finder_data
    )

    packed = entry.pack()
    unpacked = ExtendedForkEntry.unpack(packed)

    assert unpacked.finder_info == finder_data, "Finder info should be preserved"


# ===== DirectoryBlock Tests =====

def test_directory_block_volume_real_data():
    """Test with real volume directory block."""
    test_data_path = Path(__file__).parent / "data" / "volume_directory_block_2.bin"

    with open(test_data_path, 'rb') as f:
        block_data = f.read()

    assert len(block_data) == 512

    # Unpack the real block
    dir_block = DirectoryBlock.unpack(block_data)

    # Should have a volume directory header
    assert dir_block.header_entry is not None
    assert isinstance(dir_block.header_entry, VolumeDirectoryHeaderEntry)
    assert dir_block.header_entry.file_name == "MDVOL2"
    assert dir_block.header_entry.storage_type == StorageType.voldirhdr

    # Test round-trip
    repacked = dir_block.pack()
    assert repacked == block_data, "Round-trip should reproduce original"


def test_directory_block_subdir_real_data():
    """Test with real subdirectory block."""
    test_data_path = Path(__file__).parent / "data" / "subdirectory_block_27.bin"

    with open(test_data_path, 'rb') as f:
        block_data = f.read()

    assert len(block_data) == 512

    # Unpack the real block
    dir_block = DirectoryBlock.unpack(block_data)

    # Should have a subdirectory header
    assert dir_block.header_entry is not None
    assert isinstance(dir_block.header_entry, SubdirectoryHeaderEntry)
    assert dir_block.header_entry.file_name == "ICONS"
    assert dir_block.header_entry.storage_type == StorageType.subdirhdr
    assert dir_block.header_entry.file_count == 2

    # Test round-trip
    repacked = dir_block.pack()
    assert repacked == block_data, "Round-trip should reproduce original"


def test_directory_block_synthetic():
    """Test DirectoryBlock with synthetic data."""
    # Create a simple directory block without a header (continuation block)
    file_entries = [FileEntry.empty] * 13

    dir_block = DirectoryBlock(
        prev_pointer=0,
        next_pointer=0,
        header_entry=None,
        file_entries=file_entries
    )

    packed = dir_block.pack()
    assert len(packed) == 512

    unpacked = DirectoryBlock.unpack(packed)
    assert unpacked.prev_pointer == 0
    assert unpacked.next_pointer == 0
    assert unpacked.header_entry is None
    assert len(unpacked.file_entries) == 13


# ===== IndexBlock Tests =====

def test_index_block_real_data():
    """Test with real index block from a sapling file."""
    test_data_path = Path(__file__).parent / "data" / "index_block_22.bin"

    with open(test_data_path, 'rb') as f:
        block_data = f.read()

    assert len(block_data) == 512

    # Unpack the real block
    index_block = IndexBlock.unpack(block_data)

    # Verify structure
    assert len(index_block.block_pointers) == 256
    non_zero = [p for p in index_block.block_pointers if p != 0]
    assert len(non_zero) == 4, "PRODOS file should have 4 data blocks"

    # Test round-trip
    repacked = index_block.pack()
    assert repacked == block_data, "Round-trip should reproduce original"


def test_index_block_synthetic():
    """Test IndexBlock with synthetic data."""
    # Create an index block with some pointers
    pointers = [100, 101, 102, 103] + [0] * 252

    index_block = IndexBlock(block_pointers=pointers)

    packed = index_block.pack()
    assert len(packed) == 512

    unpacked = IndexBlock.unpack(packed)
    assert unpacked.block_pointers[:4] == [100, 101, 102, 103]
    assert unpacked.block_pointers[4:] == [0] * 252

    # Test round-trip
    assert packed == unpacked.pack()


def test_index_block_max_pointers():
    """Test IndexBlock with maximum pointer values."""
    # ProDOS uses 16-bit block pointers
    max_pointer = 0xFFFF
    pointers = [max_pointer] * 256

    index_block = IndexBlock(block_pointers=pointers)

    packed = index_block.pack()
    unpacked = IndexBlock.unpack(packed)

    assert all(p == max_pointer for p in unpacked.block_pointers)


# ===== BitmapBlock Tests =====

def test_bitmap_block_real_data():
    """Test with real bitmap block."""
    test_data_path = Path(__file__).parent / "data" / "bitmap_block_6.bin"

    with open(test_data_path, 'rb') as f:
        block_data = f.read()

    assert len(block_data) == 512

    # Unpack the real block
    bitmap_block = BitmapBlock.unpack(block_data)

    # Verify structure
    assert len(bitmap_block.free_map) == 512 * 8  # 4096 bits
    free_count = bitmap_block.free_map.count(1)
    assert free_count > 0, "Should have some free blocks"

    # Test round-trip
    repacked = bitmap_block.pack()
    assert repacked == block_data, "Round-trip should reproduce original"


def test_bitmap_block_synthetic():
    """Test BitmapBlock with synthetic data."""
    # Create a bitmap with specific pattern
    bits = bitarray(512 * 8)
    bits.setall(0)
    # Mark some blocks as free
    for i in [0, 1, 10, 100, 1000]:
        bits[i] = 1

    bitmap_block = BitmapBlock(free_map=bits)

    packed = bitmap_block.pack()
    assert len(packed) == 512

    unpacked = BitmapBlock.unpack(packed)
    assert unpacked.free_map.count(1) == 5
    assert unpacked.free_map[0] == 1
    assert unpacked.free_map[1] == 1
    assert unpacked.free_map[10] == 1
    assert unpacked.free_map[100] == 1
    assert unpacked.free_map[1000] == 1

    # Test round-trip
    assert packed == unpacked.pack()


def test_bitmap_block_all_free():
    """Test BitmapBlock with all blocks free."""
    bits = bitarray(512 * 8)
    bits.setall(1)

    bitmap_block = BitmapBlock(free_map=bits)
    packed = bitmap_block.pack()
    unpacked = BitmapBlock.unpack(packed)

    assert unpacked.free_map.count(1) == 512 * 8
    assert packed == unpacked.pack()


def test_bitmap_block_all_used():
    """Test BitmapBlock with all blocks used."""
    bits = bitarray(512 * 8)
    bits.setall(0)

    bitmap_block = BitmapBlock(free_map=bits)
    packed = bitmap_block.pack()
    unpacked = BitmapBlock.unpack(packed)

    assert unpacked.free_map.count(1) == 0
    assert packed == unpacked.pack()

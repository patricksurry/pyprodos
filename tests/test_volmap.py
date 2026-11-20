"""Tests for volume block usage mapping and visualization."""
import logging
from collections import Counter

import pytest

from conftest import write
from prodos.volmap import BlockUsage, format_block_map, format_legend, walk_volume
from prodos.volume import Volume


@pytest.fixture
def populated(volume: Volume) -> Volume:
    """Seedling, sapling and tree files plus nested directories"""
    write(volume, "/SEED.TXT", b"Small seedling file\n" * 10)
    write(volume, "/SAPLING.TXT", b"Sapling file content\n" * 100)
    write(volume, "/TREE.BIN", b"T" * 150000)
    volume.root.make_directory("SUBDIR1")
    volume.root.make_directory("SUBDIR2")
    entry = volume.path_entry("/SUBDIR1")
    assert entry
    volume.read_directory(entry).make_directory("NESTED")
    write(volume, "/SUBDIR1/FILE1.TXT", b"File in subdir1\n")
    write(volume, "/SUBDIR1/NESTED/FILE2.TXT", b"Nested file\n")
    return volume


def test_empty_volume(volume: Volume):
    counts = Counter(walk_volume(volume).usage)
    bitmap_blocks = len(volume.bitmap.blocks)
    assert counts == {
        BlockUsage.LOADER: 2,
        BlockUsage.VOLDIR: 4,
        BlockUsage.BITMAP: bitmap_blocks,
        BlockUsage.FREE: 1600 - 6 - bitmap_blocks,
    }


def test_populated_volume(populated: Volume, caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        block_map = walk_volume(populated)
    assert not caplog.records
    counts = Counter(block_map.usage)
    assert counts[BlockUsage.SUBDIR] == 3
    # sapling: 1 index; tree: 1 master + 2 index blocks for 293 data blocks
    assert counts[BlockUsage.INDEX] == 1 + 3
    assert counts[BlockUsage.FILE] == 1 + 5 + 293 + 1 + 1
    assert block_map.usage[:7] == [BlockUsage.LOADER] * 2 + [BlockUsage.VOLDIR] * 4 + [BlockUsage.BITMAP]


def test_usage_agrees_with_bitmap(populated: Volume):
    block_map = walk_volume(populated)
    for i, usage in enumerate(block_map.usage):
        assert (usage == BlockUsage.FREE) == block_map.free_map[i], f"block {i}"


def test_format_block_map(populated: Volume):
    formatted = format_block_map(walk_volume(populated), width=64)
    assert "0000:" in formatted
    for symbol in "!%@/#+.":
        assert symbol in formatted


def test_format_shows_bitmap_errors(populated: Volume):
    block_map = walk_volume(populated)
    used = block_map.usage.index(BlockUsage.FILE)
    free = block_map.usage.index(BlockUsage.FREE)
    block_map.free_map = block_map.free_map.copy()
    block_map.free_map[used], block_map.free_map[free] = True, False
    assert format_block_map(block_map, width=64)


def test_format_legend():
    legend = format_legend()
    for word in ["loader", "voldir", "volmap", "subdir", "key", "data", "free", "Colors:"]:
        assert word in legend

from pathlib import Path

import pytest

from prodos.bitmap import Bitmap
from prodos.device import BlockDevice
from prodos.errors import ProDOSError
from prodos.globals import block_size


@pytest.fixture
def device(tmp_path: Path):
    d = BlockDevice.create(tmp_path / "blank.img", total_blocks=16)
    yield d
    d.close()


@pytest.mark.parametrize("total,expected", [(280, 1), (4096, 1), (4097, 2), (65535, 16)])
def test_blocks_needed(total: int, expected: int):
    assert Bitmap.blocks_needed(total) == expected


def test_allocate_lowest_free_and_log(device: BlockDevice):
    bitmap = Bitmap.create(device, pointer=0, total_blocks=16)
    bitmap.mark_used(0)
    mark = device.mark_session()
    assert [bitmap.allocate(), bitmap.allocate()] == [1, 2]
    assert device.get_access_log('a', mark) == [1, 2]
    assert bitmap.free_count == 13


def test_free_zeroes_block(device: BlockDevice):
    bitmap = Bitmap.create(device, pointer=0, total_blocks=16)
    b = bitmap.allocate()
    device.write_block(b, b'x' * block_size)
    bitmap.free(b)
    assert bitmap.is_free(b)
    assert device.read_block(b) == bytes(block_size)
    assert device.get_access_log('f') == [b]


def test_full(device: BlockDevice):
    bitmap = Bitmap.create(device, pointer=0, total_blocks=16)
    for _ in range(16):
        bitmap.allocate()
    with pytest.raises(ProDOSError, match="full"):
        bitmap.allocate()


def test_flush_and_read(device: BlockDevice):
    bitmap = Bitmap.create(device, pointer=2, total_blocks=16)
    for b in (0, 1, 2, 7):
        bitmap.mark_used(b)
    bitmap.flush()
    again = Bitmap.read(device, pointer=2, total_blocks=16)
    assert [b for b in range(16) if not again.is_free(b)] == [0, 1, 2, 7]
    # bits past the end of the volume are marked used
    assert not again.free_map[16:].any()

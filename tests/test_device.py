from pathlib import Path

import pytest
from bitarray import bitarray

from conftest import IMAGES
from prodos.blocks import BitmapBlock
from prodos.device import BlockDevice, DeviceFormat, TwoImgHeader
from prodos.errors import ProDOSError
from prodos.globals import block_size


@pytest.fixture
def device(tmp_path: Path):
    d = BlockDevice.create(tmp_path / "blank.img", total_blocks=16)
    yield d
    d.close()


def test_open_real_images():
    for name, blocks in [("ProDOS_2_4_3.po", 280), ("P8_SRC.2mg", 1600)]:
        d = BlockDevice(IMAGES / name)
        assert d.total_blocks == blocks
        d.close()


def test_read_write_roundtrip_and_log(device: BlockDevice):
    mark = device.mark_session()
    data = bytes(range(256)) * 2
    device.write_block(3, data)
    assert device.read_block(3) == data
    assert device.get_access_log('w', mark) == [3]
    assert device.get_access_log('r', mark) == [3]


def test_typed_blocks_are_logged_with_type(device: BlockDevice):
    bits = bitarray(block_size * 8)
    bits.setall(1)
    device.write_typed_block(5, BitmapBlock(free_map=bits))
    assert device.read_typed_block(5, BitmapBlock).free_map == bits
    assert device.get_typed_access_log('rw') == [(5, 'BitmapBlock'), (5, 'BitmapBlock')]


def test_access_log_dump_and_file(device: BlockDevice, tmp_path: Path):
    device.read_block(1)
    device.log_access('a', 2)
    assert device.dump_access_log() == "r1    a2   "
    log = tmp_path / "log.txt"
    device.write_access_log(log)
    assert log.read_text() == "r 0001 \na 0002 \n"


def test_block_out_of_range(device: BlockDevice):
    with pytest.raises(ProDOSError, match="outside the volume"):
        device.read_block(16)


def test_read_only(tmp_path: Path):
    BlockDevice.create(tmp_path / "ro.img", total_blocks=4).close()
    d = BlockDevice(tmp_path / "ro.img")
    with pytest.raises(ProDOSError, match="read-only"):
        d.write_block(0, bytes(block_size))
    d.close()


def test_create_refuses_existing(device: BlockDevice):
    with pytest.raises(ProDOSError, match="exists"):
        BlockDevice.create(device.source, total_blocks=4)


def test_bad_size(tmp_path: Path):
    p = tmp_path / "odd.img"
    p.write_bytes(bytes(1000))
    with pytest.raises(ProDOSError, match="multiple"):
        BlockDevice(p)


@pytest.mark.skip_volume_check
def test_2mg_header_is_complete(tmp_path: Path):
    p = tmp_path / "new.2mg"
    BlockDevice.create(p, total_blocks=280, format=DeviceFormat.twomg).close()
    h = TwoImgHeader.unpack(p.read_bytes())
    assert (h.blocks, h.data_offset, h.data_length) == (280, 64, 280 * block_size)
    assert p.stat().st_size == 64 + 280 * block_size


@pytest.mark.skip_volume_check
def test_2mg_legacy_header_and_trailing_data(tmp_path: Path):
    # earlier versions left blocks/offset/length zero; others append comment chunks
    legacy = tmp_path / "legacy.2mg"
    legacy.write_bytes(TwoImgHeader(data_offset=0).pack() + bytes(8 * block_size))
    d = BlockDevice(legacy)
    assert (d.offset, d.total_blocks) == (64, 8)
    d.close()

    trailing = tmp_path / "trailing.2mg"
    trailing.write_bytes(TwoImgHeader(data_length=8 * block_size).pack() + bytes(8 * block_size) + b"comment")
    d = BlockDevice(trailing)
    assert d.total_blocks == 8
    d.close()


@pytest.mark.skip_volume_check
def test_2mg_rejects_dos_order(tmp_path: Path):
    p = tmp_path / "dos.2mg"
    p.write_bytes(TwoImgHeader(image_format=0).pack() + bytes(block_size))
    with pytest.raises(ProDOSError, match="ProDOS-order"):
        BlockDevice(p)

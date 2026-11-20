from dataclasses import replace

import pytest

from conftest import IMAGES, write
from prodos.check import check_volume
from prodos.metadata import SubdirectoryHeader
from prodos.volume import Volume


@pytest.mark.parametrize("image", ["ProDOS_2_4_3.po", "GSOSv6.0.1.po", "P8_SRC.2mg"])
def test_real_images_are_clean(image: str):
    with Volume.open(IMAGES / image) as volume:
        assert check_volume(volume) == []


def test_new_volume_is_clean(volume: Volume):
    assert check_volume(volume) == []


@pytest.mark.skip_volume_check
def test_block_in_use_marked_free(volume: Volume):
    entry = write(volume, "/F", b"x")
    volume.bitmap.free_map[entry.key_pointer] = 1
    assert check_volume(volume) == [f"/F: block {entry.key_pointer} is in use but marked free"]


@pytest.mark.skip_volume_check
def test_unreferenced_block_marked_used(volume: Volume):
    volume.bitmap.mark_used(100)
    assert check_volume(volume) == ["block 100 is marked used but not part of any file"]


@pytest.mark.skip_volume_check
def test_cross_linked_files(volume: Volume):
    a = write(volume, "/A", b"x")
    root = volume.root
    i = root.slots.index(a)
    root.slots[i + 1] = replace(a, file_name="B")
    root.write()
    assert f"/B: block {a.key_pointer} is also used by /A" in check_volume(volume)


@pytest.mark.skip_volume_check
def test_wrong_blocks_used(volume: Volume):
    a = write(volume, "/A", b"x" * 600)
    root = volume.root
    root.slots[root.slots.index(a)] = replace(a, blocks_used=1)
    root.write()
    assert check_volume(volume) == ["/A: blocks_used 1 but file has 3 blocks"]


@pytest.mark.skip_volume_check
def test_bad_parent_entry_number(volume: Volume):
    volume.root.make_directory("SUB")
    entry = volume.path_entry("/SUB")
    assert entry
    sub = volume.read_directory(entry)
    assert isinstance(sub.header, SubdirectoryHeader)
    sub.header = replace(sub.header, parent_entry_number=1)
    sub.write()
    problems = check_volume(volume)
    assert len(problems) == 1 and "doesn't locate this directory's entry" in problems[0]

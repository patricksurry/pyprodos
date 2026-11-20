"""
Directory behaviour, especially the back pointers between subdirectory
headers and their entries.  The conftest check runs after each test too.
"""
import pytest

from conftest import IMAGES, write
from prodos.directory import Directory
from prodos.errors import ProDOSError
from prodos.metadata import (
    FileType,
    StorageType,
    SubdirectoryHeader,
    access_repr,
    parse_access,
    subdirectory_reserved,
)
from prodos.volume import Volume


def subdir(volume: Volume, path: str) -> Directory:
    entry = volume.path_entry(path)
    assert entry
    return volume.read_directory(entry)


def parent_location(d: Directory) -> tuple[int, int]:
    h = d.header
    assert isinstance(h, SubdirectoryHeader)
    return h.parent_pointer, h.parent_entry_number


def test_slot_location_matches_real_images():
    # ProDOS numbers entries from 1 within each block, with the header as entry 1
    with Volume.open(IMAGES / "GSOSv6.0.1.po") as volume:
        for _, d in volume.walk():
            for i, e in enumerate(d.slots):
                if e.is_active and e.is_dir:
                    assert d.slot_location(i) == parent_location(volume.read_directory(e))


def test_make_directory(volume: Volume):
    entry = volume.root.make_directory("SUB")
    assert entry.storage_type == StorageType.dir
    assert entry.file_type == FileType.DIR
    sub = subdir(volume, "/SUB")
    assert parent_location(sub) == (2, 2)       # first slot of the key block is entry 2
    assert sub.header.reserved == subdirectory_reserved
    assert sub.parent_key_block() == 2


def test_parent_pointer_in_later_blocks(volume: Volume):
    # slots 0-11 are in the key block, 12-24 in the second block of the volume directory
    for i in range(14):
        volume.root.make_directory(f"D{i}")
    assert parent_location(subdir(volume, "/D12")) == (3, 1)
    assert parent_location(subdir(volume, "/D13")) == (3, 2)


def test_delete_does_not_move_entries(volume: Volume):
    volume.root.make_directory("A")
    write(volume, "/A/X1", b"hello")
    subdir(volume, "/A").make_directory("S")
    before = parent_location(subdir(volume, "/A/S"))
    d = subdir(volume, "/A")
    x1 = d.find("X1")
    assert x1
    d.delete(x1)
    assert parent_location(subdir(volume, "/A/S")) == before
    # the empty slot is reused
    write(volume, "/A/X2", b"again")
    assert subdir(volume, "/A").slots[0].file_name == "X2"


def test_growing_directory_updates_parent_entry(volume: Volume):
    volume.root.make_directory("A")
    for i in range(13):
        write(volume, f"/A/F{i}", b"x")
    a = subdir(volume, "/A")
    assert len(a.blocks) == 2
    entry = volume.path_entry("/A")
    assert entry and entry.blocks_used == 2 and entry.eof == 1024


def test_volume_directory_is_fixed_size(volume: Volume):
    for i in range(51):
        write(volume, f"/F{i}", b"x")
    with pytest.raises(ProDOSError, match="full"):
        write(volume, "/ONE.TOO.MANY", b"x")


def test_rename_directory_renames_header(volume: Volume):
    volume.root.make_directory("OLD")
    root = volume.root
    old = root.find("OLD")
    assert old
    root.move(old, root, "NEW")
    assert subdir(volume, "/NEW").header.file_name == "NEW"


def test_move_directory_updates_back_pointers(volume: Volume):
    volume.root.make_directory("A")
    volume.root.make_directory("B")
    write(volume, "/B/INSIDE", b"data")
    a, root = subdir(volume, "/A"), volume.root
    b = root.find("B")
    assert b
    root.move(b, a)
    moved = subdir(volume, "/A/B")
    assert parent_location(moved) == a.slot_location(0)
    assert moved.find("INSIDE")


def test_move_directory_inside_itself(volume: Volume):
    volume.root.make_directory("A")
    subdir(volume, "/A").make_directory("B")
    root = volume.root
    a = root.find("A")
    assert a
    with pytest.raises(ProDOSError, match="inside itself"):
        root.move(a, subdir(volume, "/A/B"))


def test_delete_non_empty_directory(volume: Volume):
    volume.root.make_directory("A")
    write(volume, "/A/F", b"x")
    root = volume.root
    a = root.find("A")
    assert a
    with pytest.raises(ProDOSError, match="not empty"):
        root.delete(a)


def test_write_file_metadata_and_overwrite(volume: Volume):
    entry = write(volume, "/HELLO", b"hello", file_type=FileType.TXT)
    assert (entry.file_type, entry.eof, entry.header_pointer) == (FileType.TXT, 5, 2)
    with pytest.raises(ProDOSError, match="exists"):
        write(volume, "/HELLO", b"again")
    replaced = volume.root.write_file(entry, b"bye", overwrite=True)
    assert volume.read_file(replaced).data == b"bye"


def test_illegal_name(volume: Volume):
    with pytest.raises(ProDOSError, match="Illegal"):
        volume.root.make_directory("1BAD")


def test_set_info(volume: Volume):
    entry = write(volume, "/GAME", b"\x60")
    updated = volume.root.set_info(entry, file_type=FileType.BIN, aux_type=0x2000, access=parse_access("RW"))
    assert (updated.file_type, updated.aux_type, access_repr(updated.access)) == (FileType.BIN, 0x2000, "RW----")
    assert volume.path_entry("/GAME") == updated


def test_set_info_directory_type(volume: Volume):
    entry = volume.root.make_directory("SUB")
    with pytest.raises(ProDOSError, match="directory"):
        volume.root.set_info(entry, file_type=FileType.TXT)


def test_parse_access():
    assert access_repr(parse_access("rw-bnd")) == "RW-BND"
    with pytest.raises(ProDOSError, match="Unknown access flags X"):
        parse_access("RWX")

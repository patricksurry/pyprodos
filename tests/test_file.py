from pathlib import Path

import pytest

from prodos.file import ExtendedFile, PlainFile, legal_path
from prodos.globals import block_size
from prodos.metadata import StorageType
from prodos.volume import Volume


@pytest.mark.parametrize('path,expected', [
    ('abc', 'ABC'),
    ('DEF', 'DEF'),
    ('0123_.f/7ab-,z', 'A01230.F/A7AB00Z')
])
def test_legal_path(path: str, expected: str):
    assert legal_path(path) == expected


def test_extended_file_gshk():
    """Test reading GSHK extended file (storage type 5) from GS/OS disk image."""
    # Path to the GS/OS disk image
    gsos_image = Path(__file__).parent.parent / "images" / "GSOSv6.0.1.po"

    # Open the volume
    volume = Volume.from_file(gsos_image)

    # Read the root directory
    root = volume.root

    # Find the GSHK file entry
    gshk_entry = None
    for entry in root.entries:
        if entry.file_name == "GSHK":
            gshk_entry = entry
            break

    assert gshk_entry is not None, "GSHK file not found in root directory"
    assert gshk_entry.storage_type == StorageType.extended, \
        f"GSHK should be extended file, got {gshk_entry.storage_type}"

    # Read the extended file
    gshk_file = ExtendedFile.from_entry(volume.device, gshk_entry)

    # Verify basic properties
    assert gshk_file.file_name == "GSHK"
    assert gshk_file.storage_type == StorageType.extended

    # Verify both forks exist and have data
    assert gshk_file.data_fork is not None
    assert gshk_file.resource_fork is not None

    # Verify the forks have reasonable sizes
    assert gshk_file.data_fork.file_size > 0, "Data fork should have content"
    assert gshk_file.resource_fork.file_size > 0, "Resource fork should have content"

    # Verify total file size is sum of both forks
    assert gshk_file.file_size == block_size

    # Verify block list
    assert len(gshk_file.block_list) == 1, "Only includes key block"
    assert gshk_file.block_list[0] == gshk_entry.key_pointer, \
        "First block should be extended key block"

    # Verify the forks are PlainFile instances with correct names
    assert gshk_file.data_fork.file_name == "GSHK.data"
    assert gshk_file.resource_fork.file_name == "GSHK.rsrc"


def test_plain_file_prodos():
    """Test reading PRODOS simple file (sapling) from GS/OS disk image."""
    # Path to the GS/OS disk image
    gsos_image = Path(__file__).parent.parent / "images" / "GSOSv6.0.1.po"

    # Open the volume
    volume = Volume.from_file(gsos_image)

    # Read the root directory
    root = volume.root

    # Find the PRODOS file entry
    prodos_entry = None
    for entry in root.entries:
        if entry.file_name == "PRODOS":
            prodos_entry = entry
            break

    assert prodos_entry is not None, "PRODOS file not found in root directory"
    assert prodos_entry.is_plain_file, f"PRODOS should be plain file, got {prodos_entry.storage_type}"

    # Read the file
    prodos_file = PlainFile.from_entry(volume.device, prodos_entry)

    # Verify basic properties
    assert prodos_file.file_name == "PRODOS"
    assert prodos_file.storage_type in (StorageType.seedling, StorageType.sapling, StorageType.tree)

    # Verify file size matches directory entry
    assert prodos_file.file_size == prodos_entry.eof
    assert prodos_file.file_size == 1668  # Known size from directory listing

    # Verify block count matches
    assert len(prodos_file.block_list) == prodos_entry.blocks_used
    assert len(prodos_file.block_list) == 5  # Known from directory listing

    # Verify file has data
    assert len(prodos_file.data) == prodos_file.file_size
    assert prodos_file.data[:2] == b'L\xfc'  # ProDOS system file starts with JMP instruction (4C FC)

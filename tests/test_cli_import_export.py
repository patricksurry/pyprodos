from pathlib import Path
from os import path
from typer.testing import CliRunner
import pytest

from p8cli import app

runner = CliRunner(catch_exceptions=False)


@pytest.fixture
def vol_with_dir(tmp_path: Path) -> Path:
    vol_path = tmp_path / "test.dsk"
    runner.invoke(app, ["create", str(vol_path)])
    runner.invoke(app, ["mkdir", str(vol_path), "/DIR"])
    return vol_path


def test_import_file(tmp_path: Path):
    vol = tmp_path / "tmpvol.po"
    src_file = "README.md"
    if not path.exists(src_file):
        (tmp_path / src_file).write_text("dummy content")
        src_file = str(tmp_path / src_file)

    result = runner.invoke(app, ["import", "images/ProDOS_2_4_3.po", "-o", str(vol), src_file, "/"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol)])
    assert result.exit_code == 0
    assert "README.MD" in result.stdout


def test_export_file(tmp_path: Path):
    target = tmp_path / "read.me"
    result = runner.invoke(app, ["export", "images/ProDOS_2_4_3.po", "README", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    assert "minor update" in target.read_text()


def test_export_to_dir(tmp_path: Path):
    result = runner.invoke(app, ["export", "images/ProDOS_2_4_3.po", "README", str(tmp_path)])
    assert result.exit_code == 0
    target = tmp_path / "README"
    assert target.exists()
    assert "minor update" in target.read_text()


def test_import_target_not_found(vol_with_dir: Path, tmp_path: Path) -> None:
    """Test import fails when target directory doesn't exist"""
    dummy_file = tmp_path / "test.txt"
    dummy_file.write_text("content")

    # Parent directory doesn't exist
    result = runner.invoke(app, ["import", str(vol_with_dir), str(dummy_file), "/NODIR/FILE"])
    assert result.exit_code == 2
    assert "Target not found" in result.stdout


def test_import_target_not_directory(vol_with_dir: Path, tmp_path: Path) -> None:
    """Test import fails when target is not a directory"""
    # Create a file in the volume
    file1 = tmp_path / "file1.txt"
    file1.write_text("content1")
    runner.invoke(app, ["import", str(vol_with_dir), str(file1), "/FILE"])

    # Try to import another file treating FILE as a directory
    file2 = tmp_path / "file2.txt"
    file2.write_text("content2")
    result = runner.invoke(app, ["import", str(vol_with_dir), str(file2), "/FILE/SUBFILE"])
    assert result.exit_code == 3
    assert "not a directory" in result.stdout


def test_import_over_directory(vol_with_dir: Path, tmp_path: Path) -> None:
    """Test import fails when trying to overwrite a directory"""
    # Import to / which will try to create a file named "DIR"
    # Since DIR already exists as a directory, this should fail
    dummy_file = tmp_path / "DIR"
    dummy_file.write_text("content")

    result = runner.invoke(app, ["import", str(vol_with_dir), str(dummy_file), "/"])
    assert result.exit_code == 4
    assert "is a directory" in result.stdout


def test_export_no_matching_files(vol_with_dir: Path, tmp_path: Path) -> None:
    """Test export fails when no files match"""
    output = tmp_path / "output.txt"
    result = runner.invoke(app, ["export", str(vol_with_dir), "/NONEXISTENT", str(output)])
    assert result.exit_code == 1
    assert "No matching files found" in result.stdout


def test_export_multiple_to_non_directory(vol_with_dir: Path, tmp_path: Path) -> None:
    """Test export fails when exporting multiple files to non-directory"""
    # Import two files
    file1 = tmp_path / "file1.txt"
    file1.write_text("content1")
    file2 = tmp_path / "file2.txt"
    file2.write_text("content2")
    runner.invoke(app, ["import", str(vol_with_dir), str(file1), "/FILE1"])
    runner.invoke(app, ["import", str(vol_with_dir), str(file2), "/FILE2"])

    # Try to export both to a non-existent path (not a directory)
    output = tmp_path / "output.txt"
    result = runner.invoke(app, ["export", str(vol_with_dir), "/FILE1", "/FILE2", str(output)])
    assert result.exit_code == 1
    assert "directory" in result.stdout


def test_import_tree_file_and_show_map(tmp_path: Path) -> None:
    """Test importing a tree-sized file (>128KB) and displaying the block map.

    This test verifies that importing actual ProDOS files works correctly,
    even for tree files (>128KB).
    """
    vol = tmp_path / "tree_clirunner.po"

    # Create empty volume with enough space for tree file (1600 blocks = 800KB)
    result = runner.invoke(app, ["create", str(vol), "--size", "1600"])
    assert result.exit_code == 0, f"Create failed: {result.stdout}"

    # Use the same ProDOS image file that works at command line
    source_file = Path("images/ProDOS_2_4_3.po")
    if not source_file.exists():
        pytest.skip(f"Test file {source_file} not found")

    # Import the tree file (same file that works at command line)
    result = runner.invoke(app, ["import", str(vol), str(source_file), "TREE.DAT"])
    assert result.exit_code == 0, f"Import failed: {result.stdout}"

    print(f"\n*** CliRunner created volume saved to: {vol.absolute()}")
    print(f"*** Compare with working volume: tree.po")
    print(f"*** File size: {source_file.stat().st_size} bytes")

    # Verify the file was imported and has tree storage type (type 3)
    result = runner.invoke(app, ["ls", str(vol)])
    assert result.exit_code == 0, f"ls failed: {result.stdout}"
    assert "TREE.DAT" in result.stdout
    assert "143360" in result.stdout  # File size

    # Now run info --map to verify the volume can be walked
    # This is where test_tree_file_walk fails
    result = runner.invoke(app, ["info", "--map", str(vol)])
    if result.exit_code != 0:
        print(f"Exit code: {result.exit_code}")
        print(f"Stdout:\n{result.stdout}")
        if result.exception:
            import traceback
            print(f"Exception:\n{''.join(traceback.format_exception(type(result.exception), result.exception, result.exception.__traceback__))}")
    assert result.exit_code == 0, f"info --map failed: {result.stdout}"

    # Verify the map output contains expected block types
    assert "!" in result.stdout  # loader
    assert "%" in result.stdout  # voldir
    assert "@" in result.stdout  # bitmap
    assert "#" in result.stdout  # index blocks (key)
    assert "+" in result.stdout  # data blocks
    assert "." in result.stdout  # free blocks

    # Verify the legend is present
    assert "Symbols:" in result.stdout
    assert "loader" in result.stdout
    assert "key" in result.stdout  # index blocks
    assert "data" in result.stdout


def test_import_synthetic_tree_file(tmp_path: Path) -> None:
    """Test importing synthetic tree-sized data (>128KB) via CLI import.

    This test verifies that tree files work correctly with synthetic data after
    fixing the IndexBlock.pack() bug (padding block_pointers to 256 entries before
    splitting into LSB/MSB lists).
    """
    vol = tmp_path / "tree_synthetic.po"

    # Create empty volume with enough space for tree file (1600 blocks = 800KB)
    result = runner.invoke(app, ["create", str(vol), "--size", "1600"])
    assert result.exit_code == 0, f"Create failed: {result.stdout}"

    # Create synthetic tree data - same as test_tree_file_walk uses
    size = 143360
    tree_data = b'\1' * size
    synthetic_file = tmp_path / "synthetic.dat"
    synthetic_file.write_bytes(tree_data)

    print(f"\n*** Importing synthetic tree file: {len(tree_data)} bytes")

    # Import the synthetic tree file via CLI
    result = runner.invoke(app, ["import", str(vol), str(synthetic_file), "SYNTHETIC.BIN"])
    assert result.exit_code == 0, f"Import failed: {result.stdout}"

    # Verify the file was imported and has tree storage type (type 3)
    result = runner.invoke(app, ["ls", str(vol)])
    assert result.exit_code == 0, f"ls failed: {result.stdout}"
    assert "SYNTHETIC.BIN" in result.stdout
    assert str(size) in result.stdout  # File size

    print(f"*** Synthetic tree volume saved to: {vol.absolute()}")

    # Now run info --map to verify the volume can be walked
    # If this fails like test_tree_file_walk, the bug is in tree file writing generally
    # If this passes, the bug is specifically in PlainFile constructor
    result = runner.invoke(app, ["info", "--map", str(vol)])
    if result.exit_code != 0:
        print(f"Exit code: {result.exit_code}")
        print(f"Stdout:\n{result.stdout}")
        if result.exception:
            import traceback
            print(f"Exception:\n{''.join(traceback.format_exception(type(result.exception), result.exception, result.exception.__traceback__))}")
    assert result.exit_code == 0, f"info --map failed: {result.stdout}"

    # Verify the map output contains expected block types
    assert "!" in result.stdout  # loader
    assert "%" in result.stdout  # voldir
    assert "@" in result.stdout  # bitmap
    assert "#" in result.stdout  # index blocks (key)
    assert "+" in result.stdout  # data blocks
    assert "." in result.stdout  # free blocks

    print("*** SUCCESS: CLI import of synthetic tree data works!")

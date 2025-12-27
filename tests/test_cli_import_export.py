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

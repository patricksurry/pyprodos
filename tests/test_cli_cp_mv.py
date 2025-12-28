from pathlib import Path
from typer.testing import CliRunner
import pytest

from prodos.cli import app


runner = CliRunner(catch_exceptions=False)


@pytest.fixture
def vol_with_file(tmp_path: Path) -> Path:
    vol_path = tmp_path / "test.dsk"

    # Setup: Create volume and a file
    runner.invoke(app, ["create", str(vol_path)])

    # Create a dummy file to import
    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("HELLO WORLD")

    # Import file as /HELLO
    runner.invoke(app, ["import", str(vol_path), str(dummy_file), "/HELLO"])
    return vol_path


def test_cp_file_to_file(vol_with_file: Path) -> None:
    # 1. Test cp file to file (rename copy)
    result = runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/COPY"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol_with_file)])
    assert "HELLO" in result.stdout
    assert "COPY" in result.stdout


def test_cp_file_to_dir(vol_with_file: Path) -> None:
    # 2. Test cp file to dir
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])
    result = runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/DIR"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol_with_file), "/DIR"])
    assert "HELLO" in result.stdout


def test_mv_file_to_file(vol_with_file: Path) -> None:
    # Setup copy
    runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/COPY"])
    # 3. Test mv file to file (rename)
    result = runner.invoke(app, ["mv", str(vol_with_file), "/COPY", "/RENAMED"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol_with_file)])
    assert "COPY" not in result.stdout
    assert "RENAMED" in result.stdout


def test_mv_file_to_dir(vol_with_file: Path) -> None:
    runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/RENAMED"])
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])

    # 4. Test mv file to dir
    result = runner.invoke(app, ["mv", str(vol_with_file), "/RENAMED", "/DIR"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol_with_file), "/DIR"])
    assert "RENAMED" in result.stdout


def test_mv_dir_to_dir(vol_with_file: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])
    runner.invoke(app, ["mkdir", str(vol_with_file), "/SUB"])

    # 5. Test mv dir to dir (move subdirectory)
    result = runner.invoke(app, ["mv", str(vol_with_file), "/SUB", "/DIR"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol_with_file), "/DIR"])
    assert "SUB" in result.stdout

    # Verify subdirectory integrity (parent pointer)
    result = runner.invoke(app, ["ls", str(vol_with_file), "/DIR/SUB"])
    assert result.exit_code == 0


def test_mv_dir_rename(vol_with_file: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR/SUB"])

    # 6. Test mv dir to new name (rename directory)
    result = runner.invoke(app, ["mv", str(vol_with_file), "/DIR/SUB", "/DIR/MOVED"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", str(vol_with_file), "/DIR"])
    assert "SUB" not in result.stdout
    assert "MOVED" in result.stdout

    # Verify we can still access it
    result = runner.invoke(app, ["ls", str(vol_with_file), "/DIR/MOVED"])
    assert result.exit_code == 0


def test_mv_root_directory_error(vol_with_file: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])

    # 7. Test that moving root directory fails with error
    result = runner.invoke(app, ["mv", str(vol_with_file), "/", "/DIR"])
    assert result.exit_code == 1
    assert "Cannot move root directory" in result.stdout


def test_cp_no_matching_files(vol_with_file: Path) -> None:
    """Test cp fails when no files match the pattern"""
    result = runner.invoke(app, ["cp", str(vol_with_file), "/NONEXISTENT", "/DEST"])
    assert result.exit_code == 1
    assert "No matching files found" in result.stdout


def test_cp_multiple_to_non_directory(vol_with_file: Path) -> None:
    """Test cp fails when copying multiple files to a non-directory target"""
    runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/COPY"])
    result = runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/COPY", "/DEST"])
    assert result.exit_code == 1
    assert "not a directory" in result.stdout


def test_cp_to_nonexistent_parent(vol_with_file: Path) -> None:
    """Test cp fails when parent directory doesn't exist"""
    result = runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/NODIR/FILE"])
    assert result.exit_code == 1
    assert "Parent directory" in result.stdout
    assert "not found" in result.stdout


def test_cp_omit_directory(vol_with_file: Path) -> None:
    """Test cp skips directories with warning"""
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])
    result = runner.invoke(app, ["cp", str(vol_with_file), "/DIR", "/DEST"])
    assert result.exit_code == 0
    assert "Omitting directory" in result.stdout


def test_mv_no_matching_files(vol_with_file: Path) -> None:
    """Test mv fails when no files match the pattern"""
    result = runner.invoke(app, ["mv", str(vol_with_file), "/NONEXISTENT", "/DEST"])
    assert result.exit_code == 1
    assert "No matching files found" in result.stdout


def test_mv_multiple_to_non_directory(vol_with_file: Path) -> None:
    """Test mv fails when moving multiple files to a non-directory target"""
    runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/FILE1"])
    runner.invoke(app, ["cp", str(vol_with_file), "/HELLO", "/FILE2"])
    result = runner.invoke(app, ["mv", str(vol_with_file), "/FILE1", "/FILE2", "/DEST"])
    assert result.exit_code == 1
    assert "not a directory" in result.stdout
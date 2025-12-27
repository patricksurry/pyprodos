from pathlib import Path
from typer.testing import CliRunner
import pytest

from p8cli import app


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
from pathlib import Path

import pytest
from typer.testing import CliRunner

from prodos.cli import app

runner = CliRunner(catch_exceptions=False)


@pytest.fixture
def vol_with_file(tmp_path: Path) -> Path:
    vol_path = tmp_path / "test.dsk"
    runner.invoke(app, ["create", str(vol_path)])

    # Create and import a file
    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("test content")
    runner.invoke(app, ["import", str(vol_path), str(dummy_file), "/FILE"])
    return vol_path


def test_rm_wildcard(tmp_path: Path):
    vol = tmp_path / "tmpvol.po"
    result = runner.invoke(app, ["rm", "images/ProDOS_2_4_3.po", "--output", str(vol), "*.SYSTEM"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["ls", str(vol)])
    assert "14 files in PRODOS" in result.stdout
    assert "SYSTEM" not in result.stdout


def test_rm_no_matching_files(vol_with_file: Path) -> None:
    """Test rm fails when no files match the pattern"""
    result = runner.invoke(app, ["rm", str(vol_with_file), "/NONEXISTENT"])
    assert result.exit_code == 1
    assert "No matching files found" in result.stdout


def test_rm_directory_error(vol_with_file: Path) -> None:
    """Test rm fails when trying to remove a directory"""
    runner.invoke(app, ["mkdir", str(vol_with_file), "/DIR"])
    result = runner.invoke(app, ["rm", str(vol_with_file), "/DIR"])
    assert result.exit_code == 1
    assert "Not a simple file" in result.stdout




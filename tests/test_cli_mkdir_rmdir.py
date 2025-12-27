from pathlib import Path
from typer.testing import CliRunner
import pytest

from p8cli import app


runner = CliRunner(catch_exceptions=False)


@pytest.fixture
def vol_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.dsk"
    runner.invoke(app, ["create", str(p)])
    return p


def test_mkdir(vol_path: Path) -> None:
    # mkdir /TEST
    result = runner.invoke(app, ["mkdir", str(vol_path), "/TEST"])
    assert result.exit_code == 0

    # Verify with ls
    result = runner.invoke(app, ["ls", str(vol_path)])
    assert result.exit_code == 0
    assert "TEST" in result.stdout


def test_mkdir_nested(vol_path: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_path), "/TEST"])

    # mkdir nested /TEST/SUB
    result = runner.invoke(app, ["mkdir", str(vol_path), "/TEST/SUB"])
    assert result.exit_code == 0

    # Verify nested
    result = runner.invoke(app, ["ls", str(vol_path), "/TEST"])
    assert result.exit_code == 0
    assert "SUB" in result.stdout


def test_rmdir_non_empty(vol_path: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_path), "/TEST"])
    runner.invoke(app, ["mkdir", str(vol_path), "/TEST/SUB"])

    # Try rmdir non-empty
    result = runner.invoke(app, ["rmdir", str(vol_path), "/TEST"])
    assert result.exit_code != 0
    assert "not empty" in result.stdout


def test_rmdir_nested(vol_path: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_path), "/TEST"])
    runner.invoke(app, ["mkdir", str(vol_path), "/TEST/SUB"])

    # rmdir /TEST/SUB
    result = runner.invoke(app, ["rmdir", str(vol_path), "/TEST/SUB"])
    assert result.exit_code == 0

    # Verify removal
    result = runner.invoke(app, ["ls", str(vol_path), "/TEST"])
    assert "SUB" not in result.stdout


def test_rmdir(vol_path: Path) -> None:
    runner.invoke(app, ["mkdir", str(vol_path), "/TEST"])

    # rmdir /TEST
    result = runner.invoke(app, ["rmdir", str(vol_path), "/TEST"])
    assert result.exit_code == 0

    # Verify removal
    result = runner.invoke(app, ["ls", str(vol_path)])
    assert result.exit_code == 0
    assert "TEST" not in result.stdout
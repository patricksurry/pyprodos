from pathlib import Path

from typer.testing import CliRunner

from prodos.cli import app

runner = CliRunner(catch_exceptions=False)


def make_volume(tmp_path: Path) -> Path:
    vol = tmp_path / "vol.po"
    host = tmp_path / "game.bin"
    host.write_bytes(b"\x60")
    assert runner.invoke(app, ["create", str(vol), "--size", "280"]).exit_code == 0
    assert runner.invoke(app, ["import", str(vol), str(host), "/GAME"]).exit_code == 0
    return vol


def test_chinfo(tmp_path: Path):
    vol = make_volume(tmp_path)
    result = runner.invoke(app, ["chinfo", str(vol), "/GAME", "--type", "FF", "--aux", "$2000", "--access", "RW"])
    assert result.exit_code == 0, result.stdout
    listing = runner.invoke(app, ["ls", str(vol), "/GAME"]).stdout
    assert "1/FF RW----" in listing


def test_chinfo_needs_a_change(tmp_path: Path):
    vol = make_volume(tmp_path)
    result = runner.invoke(app, ["chinfo", str(vol), "/GAME"])
    assert result.exit_code == 1
    assert "Nothing to change" in result.stdout


def test_chinfo_bad_access(tmp_path: Path):
    vol = make_volume(tmp_path)
    result = runner.invoke(app, ["chinfo", str(vol), "/GAME", "--access", "RWQ"])
    assert result.exit_code == 1
    assert "Unknown access flags Q" in result.stdout

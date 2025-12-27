from pathlib import Path
from typer.testing import CliRunner

from p8cli import app


runner = CliRunner(catch_exceptions=False)


def test_create_2mg(tmp_path: Path):
    vol = tmp_path / "newvol.2mg"
    result = runner.invoke(app, ["create", str(vol), "--name", "floppy", "--size", "140", "--format", "2mg"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["info", str(vol)])
    assert result.exit_code == 0
    assert "FLOPPY" in result.stdout
    assert f"{140 - 2 - 4 - 1} free" in result.stdout
    assert vol.stat().st_size == 140*512 + 64

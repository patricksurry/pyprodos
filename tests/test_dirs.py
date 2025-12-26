from pathlib import Path
from typer.testing import CliRunner

from p8cli import app

runner = CliRunner(catch_exceptions=False)

def test_mkdir_rmdir(tmp_path: Path) -> None:
    vol_path = tmp_path / "test.dsk"

    # Create volume
    result = runner.invoke(app, ["create", str(vol_path)])
    assert result.exit_code == 0
    assert vol_path.exists()

    # mkdir /TEST
    result = runner.invoke(app, ["mkdir", str(vol_path), "/TEST"])
    assert result.exit_code == 0

    # Verify with ls
    result = runner.invoke(app, ["ls", str(vol_path)])
    assert result.exit_code == 0
    assert "TEST" in result.stdout

    # mkdir nested /TEST/SUB
    result = runner.invoke(app, ["mkdir", str(vol_path), "/TEST/SUB"])
    assert result.exit_code == 0

    # Verify nested
    result = runner.invoke(app, ["ls", str(vol_path), "/TEST"])
    assert result.exit_code == 0
    assert "SUB" in result.stdout

    # Try rmdir non-empty
    result = runner.invoke(app, ["rmdir", str(vol_path), "/TEST"])
    assert result.exit_code != 0
    assert "not empty" in result.stdout

    # rmdir /TEST/SUB
    result = runner.invoke(app, ["rmdir", str(vol_path), "/TEST/SUB"])
    assert result.exit_code == 0

    # rmdir /TEST
    result = runner.invoke(app, ["rmdir", str(vol_path), "/TEST"])
    assert result.exit_code == 0

    # Verify removal
    result = runner.invoke(app, ["ls", str(vol_path)])
    assert result.exit_code == 0
    assert "TEST" not in result.stdout
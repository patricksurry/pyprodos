from pathlib import Path
from typer.testing import CliRunner

from p8cli import app


runner = CliRunner()


def test_rm_wildcard(tmp_path: Path):
    vol = tmp_path / "tmpvol.po"
    result = runner.invoke(app, ["rm", "images/ProDOS_2_4_3.po", "--output", str(vol), "*.SYSTEM"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["ls", str(vol)])
    assert "14 files in PRODOS" in result.stdout
    assert "SYSTEM" not in result.stdout




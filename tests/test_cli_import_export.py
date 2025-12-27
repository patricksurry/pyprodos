from pathlib import Path
from os import path
from typer.testing import CliRunner

from p8cli import app

runner = CliRunner(catch_exceptions=False)


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

from typer.testing import CliRunner
from os import path, unlink

from p8cli import app


runner = CliRunner()


def test_info():
    result = runner.invoke(app, ["images/ProDOS_2_4_3.po", "info"])
    assert result.exit_code == 0
    assert "PRODOS.2.4.3" in result.stdout


def test_ls_glob():
    result = runner.invoke(app, ["images/ProDOS_2_4_3.po", "ls", "READ*"])
    assert result.exit_code == 0
    assert "README" in result.stdout


def test_2mg():
    result = runner.invoke(app, ["images/P8_SRC.2mg", "ls"])
    assert result.exit_code == 0
    assert "README.TXT" in result.stdout


def test_export():
    out = 'fubar'
    if path.exists(out):
        unlink(out)
    result = runner.invoke(app, ["images/ProDOS_2_4_3.po", "export", "README", out])
    assert result.exit_code == 0
    assert "minor update" in open(out).read()
    assert path.exists(out)
    unlink(out)


def test_export_to_dir():
    out = 'README'
    if path.exists(out):
        unlink(out)
    result = runner.invoke(app, ["images/ProDOS_2_4_3.po", "export", "README", "."])
    assert result.exit_code == 0
    assert "minor update" in open(out).read()
    assert path.exists(out)
    unlink(out)


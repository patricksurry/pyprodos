from typer.testing import CliRunner

from prodos.cli import app

runner = CliRunner()


def test_info_prodos():
    result = runner.invoke(app, ["info", "images/ProDOS_2_4_3.po"])
    assert result.exit_code == 0
    assert "PRODOS.2.4.3" in result.stdout


def test_ls_pattern():
    result = runner.invoke(app, ["ls", "images/ProDOS_2_4_3.po", "READ*"])
    assert result.exit_code == 0
    assert "README" in result.stdout


def test_ls_2mg():
    result = runner.invoke(app, ["ls", "images/P8_SRC.2mg"])
    assert result.exit_code == 0
    assert "README.TXT" in result.stdout

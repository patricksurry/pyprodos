from typer.testing import CliRunner
from os import path
from pathlib import Path

from p8cli import app


runner = CliRunner()


def cmp_vols(a: str, b: str) -> int:
    va = open(a, 'rb').read()
    vb = open(b, 'rb').read()
    return len([(x,y) for (x,y) in zip(va, vb) if x != y]) + abs(len(va) - len(vb))


def test_roundtrip(tmp_path: Path):
    vol = tmp_path / "vol.po"
    dup = tmp_path / "dup.po"

    src_file = "README.md"
    if not path.exists(src_file):
        (tmp_path / src_file).write_text("dummy content")
        src_file = str(tmp_path / src_file)

    # Create
    result = runner.invoke(app, ["create", str(vol), "--name", "roundtrip", "--size", "140"])
    assert result.exit_code == 0

    # Import
    result = runner.invoke(app, ["import", str(vol), "-o", str(dup), src_file, "README.md"])
    assert result.exit_code == 0

    # Rm
    result = runner.invoke(app, ["rm", str(dup), "README.md"])
    assert result.exit_code == 0

    # Compare
    diff = cmp_vols(str(vol), str(dup))
    assert diff <= 1

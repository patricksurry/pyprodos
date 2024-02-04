import pytest
from typer.testing import CliRunner
from os import path, unlink
import shutil

from p8cli import app


runner = CliRunner()


def check_export(args, result, _):
    target = args[-1]
    if path.isdir(args[-1]):
        target = path.join(args[-1], 'README')
    assert path.exists(target)
    assert "minor update" in open(target).read()


def check_create(args, result, _):
    target = args[1]
    assert path.exists(target)
    assert path.getsize(target) == 140*512+64
    assert "FLOPPY" in result.stdout
    assert f"{140 - 2 - 4 - 1} free" in result.stdout
    unlink(target)


def cmp_vols(a: str, b: str) -> int:
    va = open(a, 'rb').read()
    vb = open(b, 'rb').read()
    return len([(x,y) for (x,y) in zip(va, vb) if x != y]) + abs(len(va) - len(vb))


def compare_images(args, result, dir):
    diff = cmp_vols(path.join(dir, 'vol.po'), path.join(dir, 'dup.po'))
    assert diff <= 1


@pytest.mark.parametrize('cmdlines,exit_code,check', [
    (["prodos images/ProDOS_2_4_3.po info"], 0, "PRODOS.2.4.3"),
    (["prodos images/ProDOS_2_4_3.po ls READ*"], 0, "README"),
    (["prodos images/P8_SRC.2mg ls"], 0, "README.TXT"),
    ([
        "prodos --source images/ProDOS_2_4_3.po @@/tmpvol rm *.SYSTEM",
        "prodos @@/tmpvol ls",
    ], 0, "14 files in PRODOS"),
    (["prodos images/ProDOS_2_4_3.po export README @@/read.me"], 0, check_export),
    (["prodos images/ProDOS_2_4_3.po export README @@"], 0, check_export),
    ([
        "prodos @@/newvol.2mg create --name floppy --size 140 --format 2mg",
        "prodos @@/newvol.2mg info"
    ], 0, check_create),
    ([
        "prodos --source images/ProDOS_2_4_3.po @@/tmpvol import README.md",
        "prodos @@/tmpvol ls"
    ], 0, "README.md"),
    ([
        "prodos @@/vol.po create --name roundtrip --size 140",
        "prodos --source @@/vol.po @@/dup.po import README.md README.md",
        "prodos @@/dup.po rm README.md",
    ], 0, compare_images),
])
def test_cases(cmdlines, exit_code, check, tmp_path):
    assert isinstance(cmdlines, list) and isinstance(cmdlines[0], str)

    result = None
    for cmd in cmdlines:
        assert result is None or result.exit_code == 0
        args = [s.replace('@@', str(tmp_path)) for s in cmd.split()]
        assert args[0] == 'prodos'
        result = runner.invoke(app, args[1:])
    assert result.exit_code == exit_code, f"{result.exit_code}\n{result.stdout}\n"

    if isinstance(check, str):
        assert check in result.stdout
    elif callable(check):
        check(args, result, tmp_path)



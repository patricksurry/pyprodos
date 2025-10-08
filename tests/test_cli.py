import pytest
from typer.testing import CliRunner
from click.testing import Result
from os import path, unlink
from pathlib import Path
from typing import Callable, cast

from p8cli import app


runner = CliRunner()


def check_export(args: list[str], result: Result, _):
    target = args[-1]
    if path.isdir(args[-1]):
        target = path.join(args[-1], 'README')
    assert path.exists(target)
    assert "minor update" in open(target).read()


def check_create(args: list[str], result: Result, _):
    target = args[2]
    assert path.exists(target)
    assert path.getsize(target) == 140*512+64
    assert "FLOPPY" in result.stdout
    assert f"{140 - 2 - 4 - 1} free" in result.stdout
    unlink(target)


def cmp_vols(a: str, b: str) -> int:
    va = open(a, 'rb').read()
    vb = open(b, 'rb').read()
    return len([(x,y) for (x,y) in zip(va, vb) if x != y]) + abs(len(va) - len(vb))


def compare_images(args: list[str], result: Result, dir: Path):
    diff = cmp_vols(path.join(dir, 'vol.po'), path.join(dir, 'dup.po'))
    assert diff <= 1


Verifier = str | Callable[[list[str], Result, Path], None]

@pytest.mark.parametrize('cmdlines,exit_code,check', cast(list[Verifier], [
    (["prodos info images/ProDOS_2_4_3.po"], 0, "PRODOS.2.4.3"),
    (["prodos ls images/ProDOS_2_4_3.po READ*"], 0, "README"),
    (["prodos ls images/P8_SRC.2mg"], 0, "README.TXT"),
    ([
        "prodos rm images/ProDOS_2_4_3.po --output @@/tmpvol.po *.SYSTEM",
        "prodos ls @@/tmpvol.po",
    ], 0, "14 files in PRODOS"),
    (["prodos export images/ProDOS_2_4_3.po README @@/read.me"], 0, check_export),
    (["prodos export images/ProDOS_2_4_3.po README @@"], 0, check_export),
    ([
        "prodos create @@/newvol.2mg --name floppy --size 140 --format 2mg",
        "prodos info @@/newvol.2mg"
    ], 0, check_create),
    ([
        "prodos import images/ProDOS_2_4_3.po -o @@/tmpvol.po README.md /",
        "prodos ls @@/tmpvol.po"
    ], 0, "README.MD"),
    ([
        "prodos create @@/vol.po --name roundtrip --size 140",
        "prodos import @@/vol.po -o @@/dup.po README.md README.md",
        "prodos rm @@/dup.po README.md",
    ], 0, compare_images),
]))
def test_cases(cmdlines: list[str], exit_code: int, check: Verifier, tmp_path: Path):
    assert len(cmdlines) > 0
    for i, cmd in enumerate(cmdlines):
        args = [s.replace('@@', str(tmp_path)) for s in cmd.split()]
        assert args[0] == 'prodos'
        print(args)
        result = runner.invoke(app, args[1:])
        assert result.exit_code == (0 if i < len(cmdlines) else exit_code)

    if isinstance(check, str):
        assert check in result.stdout   # type: ignore  # result and args are bound in first loop iter
    elif callable(check):
        check(args, result, tmp_path)   # type: ignore



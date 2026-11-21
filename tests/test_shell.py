from collections.abc import Iterator
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from conftest import write
from prodos.cli import app
from prodos.shell import Shell
from prodos.volume import Volume


class Session:
    """Drive a Shell line by line, collecting its output"""

    def __init__(self, volume: Volume):
        self.buffer = StringIO()
        self.shell = Shell(volume, console=Console(file=self.buffer, width=200, highlight=False, soft_wrap=True))

    def __call__(self, line: str) -> str:
        self.buffer.seek(0)
        self.buffer.truncate()
        self.shell.onecmd(line)
        self.shell.postcmd(False, line)
        return self.buffer.getvalue()


@pytest.fixture
def sh(volume: Volume) -> Iterator[Session]:
    write(volume, '/HELLO', b'\xC8\xC9\x8D', file_type=0x04)
    volume.make_directory('/SUB')
    yield Session(volume)


def test_cd_and_relative_paths(sh: Session):
    assert sh('pwd').strip() == '/'
    assert sh('cd sub') == ''
    assert sh.shell.prompt == 'TEST:/SUB> '
    sh('cp ../hello copy')
    out = sh('ls')
    assert 'COPY' in out and 'HELLO' not in out
    sh('cd ..')
    assert sh.shell.cwd == '/'
    assert 'not a directory' in sh('cd HELLO')


def test_cat(sh: Session):
    assert sh('cat hello') == 'HI\n'


def test_errors_are_reported(sh: Session):
    assert 'Error: No matching files found' in sh('rm nothing')
    assert 'Error: Unknown command' in sh('frobnicate')
    assert 'Error: Usage' in sh('cp onlyone')
    assert 'is a directory' in sh('rm SUB')


def test_mkdir_mv_rmdir(sh: Session):
    sh('mkdir sub/deeper')
    sh('mv hello sub/deeper')
    assert 'HELLO' in sh('ls -r')
    sh('cd sub/deeper')
    assert "current directory" in sh('rmdir /sub/deeper')
    sh('rm hello')
    sh('cd /')
    sh('rmdir sub/deeper')
    assert 'DEEPER' not in sh('ls sub')


def test_chinfo(sh: Session):
    sh('chinfo -t SYS -a 2000 --access RWD hello')
    assert '1/FF 2000 RW---D' in sh('ls hello')
    assert 'Nothing to change' in sh('chinfo hello')


def test_put_get(sh: Session, tmp_path: Path):
    host = tmp_path / 'host'
    host.mkdir()
    (host / 'a.txt').write_text('a')
    (host / 'B#FF2000').write_text('b')
    sh('mkdir in')
    out = sh(f'put {host}/* in')
    assert 'A.TXT' in out and 'B ' in out
    assert '1/FF 2000' in sh('ls in/b')
    assert 'already exists' in sh(f'put {host}/a.txt in')
    sh(f'put -f -t TXT {host}/a.txt in')

    got = tmp_path / 'got'
    got.mkdir()
    sh(f'get -T in/* {got}')
    assert sorted(p.name for p in got.iterdir()) == ['A.TXT#040000', 'B#FF2000']


def test_put_get_recursive_and_loader(sh: Session, tmp_path: Path):
    tree = tmp_path / 'tree'
    (tree / 'sub').mkdir(parents=True)
    (tree / 'sub' / 'x').write_bytes(b'x')
    (tmp_path / 'loader.bin').write_bytes(b'\x01' * 10)
    sh(f'put -r -l {tmp_path}/loader.bin {tree}')
    assert 'X' in sh('ls tree/sub')
    out = tmp_path / 'out'
    out.mkdir()
    sh(f'get -r -l {out}/loader.bin tree {out}')
    assert (out / 'TREE' / 'SUB' / 'X').read_bytes() == b'x'
    assert (out / 'loader.bin').read_bytes()[:11] == b'\x01' * 10 + b'\0'
    assert 'Usage' in sh('get')


def test_completion(sh: Session):
    assert sh.shell.complete_prodos('h') == ['HELLO']
    assert sh.shell.complete_prodos('/s') == ['/SUB/']
    assert sh.shell.complete_prodos('nothing/x') == []


def test_info_and_check(sh: Session):
    assert 'free' in sh('info')
    assert 'No problems found' in sh('check')


def test_shell_command(tmp_path: Path):
    """prodos shell runs commands from stdin and flushes the volume on exit"""
    vol = tmp_path / 'shell.po'
    runner = CliRunner()
    runner.invoke(app, ['create', str(vol), '--size', '280'])
    result = runner.invoke(app, ['shell', str(vol)], input='mkdir games\ncd games\npwd\nexit\n')
    assert result.exit_code == 0, result.output
    assert '/GAMES' in result.output
    assert 'GAMES' in runner.invoke(app, ['ls', str(vol)]).stdout


def test_shell_read_only(tmp_path: Path):
    vol = tmp_path / 'ro.po'
    runner = CliRunner()
    runner.invoke(app, ['create', str(vol), '--size', '280'])
    result = runner.invoke(app, ['shell', '-r', str(vol)], input='mkdir games\n')
    assert 'Error' in result.output
    assert 'GAMES' not in runner.invoke(app, ['ls', str(vol)]).stdout

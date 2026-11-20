from pathlib import Path

import pytest

from conftest import write
from prodos.errors import ProDOSError
from prodos.host import export_files, import_files, parse_host_name, prodos_text, typed_host_name
from prodos.metadata import FileType, parse_file_type, parse_hex
from prodos.volume import Volume, resolve_path, split_path


@pytest.mark.parametrize('name, expected', [
    ('README', ('README', None, None)),
    ('BASIC.SYSTEM#FF2000', ('BASIC.SYSTEM', 0xFF, 0x2000)),
    ('notes.txt#04', ('notes.txt', 0x04, None)),
    ('odd#zz1234', ('odd#zz1234', None, None)),
])
def test_parse_host_name(name: str, expected: tuple[str, int | None, int | None]):
    assert parse_host_name(name) == expected


def test_parse_file_type():
    assert parse_file_type('sys') == FileType.SYS
    assert parse_file_type('$06') == 6
    assert parse_hex('0x2000') == 0x2000
    with pytest.raises(ProDOSError, match="Invalid file type"):
        parse_file_type('nope')


def test_prodos_text():
    assert prodos_text(bytes([0xC8, 0xC9, 0x8D, 0x41, 0x0D])) == "HI\nA\n"


@pytest.mark.parametrize('path, cwd, expected', [
    ('A', '/', '/A'),
    ('../c', '/A/B', '/A/C'),
    ('..', '/', '/'),
    ('/X/./Y/', '/A', '/X/Y'),
    ('*.SYSTEM', '/SYS', '/SYS/*.SYSTEM'),
])
def test_resolve_path(path: str, cwd: str, expected: str):
    assert resolve_path(path, cwd) == expected


def test_split_path():
    assert split_path('/A/B/C') == ('/A/B', 'C')
    assert split_path('/A') == ('/', 'A')
    assert split_path('/A/') == ('/', 'A')


def test_typed_roundtrip(volume: Volume, tmp_path: Path):
    """Exporting with types and importing again preserves file type and aux type"""
    e = write(volume, '/GAME', b'\x60', file_type=FileType.BIN)
    volume.set_info(['/GAME'], aux_type=0x2000)
    out = tmp_path / 'out'
    out.mkdir()
    assert export_files(volume, ['/GAME'], out, typed=True) == []
    host = out / 'GAME#062000'
    assert host.read_bytes() == b'\x60'
    assert typed_host_name(volume.path_entry('/GAME') or e) == host.name

    volume.make_directory('/COPY')
    [imported] = import_files(volume, [host], '/COPY')
    assert (imported.file_name, imported.file_type, imported.aux_type) == ('GAME', FileType.BIN, 0x2000)


def test_import_type_precedence(volume: Volume, tmp_path: Path):
    host = tmp_path / 'X.SYSTEM#04'
    host.write_bytes(b'hi')
    [e] = import_files(volume, [host], '/', file_type=0xFC)
    assert e.file_type == 0xFC                  # option beats the name suffix
    [e] = import_files(volume, [host], '/Y')
    assert (e.file_name, e.file_type) == ('Y', 0x04)  # suffix beats the guess


def test_import_errors(volume: Volume, tmp_path: Path):
    host = tmp_path / 'A'
    host.write_bytes(b'a')
    import_files(volume, [host], '/')
    with pytest.raises(ProDOSError, match="already exists"):
        import_files(volume, [host], '/')
    import_files(volume, [host], '/', overwrite=True)
    with pytest.raises(ProDOSError, match="Not regular host files"):
        import_files(volume, [tmp_path], '/')
    with pytest.raises(ProDOSError, match="not a directory"):
        import_files(volume, [host, host], '/A')

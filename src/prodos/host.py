"""
Moving files between the host and a volume.

Host file systems have no ProDOS file type or aux type, so we follow the
CiderPress / AppleCommander convention of appending them to the host file name
as #TTAAAA in hex.  For example BASIC.SYSTEM#FF2000 is a SYS file loaded at $2000.
Importing always understands this suffix; exporting adds it when asked.
"""
import re
from pathlib import Path

from .errors import ProDOSError
from .file import guess_file_type, legal_name
from .metadata import FileEntry
from .volume import Volume

_type_suffix = re.compile(r'#([0-9A-F]{2})([0-9A-F]{4})?$', re.IGNORECASE)


def parse_host_name(name: str) -> tuple[str, int | None, int | None]:
    """Split 'NAME#TTAAAA' into ('NAME', file_type, aux_type); missing parts are None"""
    m = _type_suffix.search(name)
    if not m:
        return name, None, None
    file_type, aux_type = m.groups()
    return name[:m.start()], int(file_type, 16), int(aux_type, 16) if aux_type else None


def typed_host_name(entry: FileEntry) -> str:
    """'NAME#TTAAAA' for entry"""
    return f"{entry.file_name}#{entry.file_type:02X}{entry.aux_type:04X}"


def prodos_text(data: bytes) -> str:
    """Apple II text as host text: clear the high bit and turn carriage returns into newlines"""
    return bytes(b & 0x7F for b in data).replace(b'\r', b'\n').decode('ascii', errors='replace')


def import_files(
        volume: Volume,
        host_paths: list[Path],
        dst: str,
        file_type: int | None = None,
        aux_type: int | None = None,
        overwrite: bool = False,
        recursive: bool = False,
    ) -> list[FileEntry]:
    """
    Import host files into directory dst, or a single file as dst.
    The file type comes from file_type, else the #TTAAAA name suffix, else a guess from the name.
    With recursive, host directories are imported as ProDOS directories, skipping hidden files.
    """
    bad = [str(p) for p in host_paths if not (p.is_file() or (recursive and p.is_dir()))]
    if bad:
        hint = '' if recursive else ' (import directories recursively)'
        raise ProDOSError(f"Not regular host files{hint}: {', '.join(bad)}")
    key, rename = volume.target(dst, len(host_paths))
    imported: list[FileEntry] = []
    for p in host_paths:
        imported += _import(volume, p, key, rename, file_type, aux_type, overwrite)
    return imported


def _import(volume: Volume, p: Path, key: int, rename: str | None,
        file_type: int | None, aux_type: int | None, overwrite: bool) -> list[FileEntry]:
    """Import host file or directory p into the directory at key"""
    base, name_type, name_aux = parse_host_name(p.name)
    name = rename or legal_name(base)
    d = volume.read_directory_at(key)
    existing = d.find(name)

    if p.is_dir():
        if existing and not existing.is_dir:
            raise ProDOSError(f"{name} already exists in {d.name} and is not a directory")
        subdir = existing or d.make_directory(name)
        entries = [subdir]
        for child in sorted(p.iterdir()):
            if not child.name.startswith('.'):
                entries += _import(volume, child, subdir.key_pointer, None, file_type, aux_type, overwrite)
        return entries

    if existing and existing.is_dir:
        raise ProDOSError(f"Target {name} is a directory")
    if existing and not overwrite:
        raise ProDOSError(f"{name} already exists in {d.name}")
    ftype = next((t for t in (file_type, name_type) if t is not None), None)
    entry = FileEntry.new(
        name,
        file_type=guess_file_type(name) if ftype is None else ftype,
        aux_type=next((a for a in (aux_type, name_aux) if a is not None), 0),
    )
    return [d.write_file(entry, p.read_bytes(), overwrite=overwrite)]


def export_files(volume: Volume, paths: list[str], host_dst: Path,
        typed: bool = False, recursive: bool = False) -> list[str]:
    """
    Export files to host directory host_dst, or a single file as host_dst.
    With typed, host names get a #TTAAAA suffix.  With recursive, directories are
    exported as host directories.  Returns notes about anything skipped.
    """
    entries = volume.find_entries(paths)
    to_dir = host_dst.is_dir()
    if len(entries) > 1 and not to_dir:
        raise ProDOSError(f"{host_dst} must be an existing directory to export several files")
    notes: list[str] = []
    for e in entries:
        name = volume.header.file_name if e.is_volume_dir else e.file_name
        if not e.is_dir and typed:
            name = typed_host_name(e)
        _export(volume, e, host_dst / name if to_dir else host_dst, typed, recursive, notes)
    return notes


def _export(volume: Volume, e: FileEntry, out: Path, typed: bool, recursive: bool, notes: list[str]):
    """Export entry e as host path out"""
    if e.is_dir:
        if not recursive:
            notes.append(f"Omitting directory {e.file_name}")
            return
        out.mkdir(exist_ok=True)
        for child in volume.read_directory(e).entries:
            name = typed_host_name(child) if typed and not child.is_dir else child.file_name
            _export(volume, child, out / name, typed, recursive, notes)
        return
    try:
        volume.read_file(e).export(str(out))
    except ProDOSError as ex:
        notes.append(f"Skipping {e.file_name}: {ex}")

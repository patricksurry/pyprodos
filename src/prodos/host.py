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
    ) -> list[FileEntry]:
    """
    Import host files into directory dst, or a single file as dst.
    The file type comes from file_type, else the #TTAAAA name suffix, else a guess from the name.
    """
    bad = [str(p) for p in host_paths if not p.is_file()]
    if bad:
        raise ProDOSError(f"Not regular host files: {', '.join(bad)}")
    key, rename = volume.target(dst, len(host_paths))
    imported: list[FileEntry] = []
    for p in host_paths:
        base, name_type, name_aux = parse_host_name(p.name)
        name = rename or legal_name(base)
        d = volume.read_directory_at(key)
        existing = d.find(name)
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
        imported.append(d.write_file(entry, p.read_bytes(), overwrite=overwrite))
    return imported


def export_files(volume: Volume, paths: list[str], host_dst: Path, typed: bool = False) -> list[str]:
    """
    Export files to host directory host_dst, or a single file as host_dst.
    With typed, host names get a #TTAAAA suffix.  Returns notes about anything skipped.
    """
    entries = volume.find_entries(paths)
    to_dir = host_dst.is_dir()
    if len(entries) > 1 and not to_dir:
        raise ProDOSError(f"{host_dst} must be an existing directory to export several files")
    notes: list[str] = []
    for e in entries:
        if e.is_dir:
            notes.append(f"Omitting directory {e.file_name}")
            continue
        out = host_dst / (typed_host_name(e) if typed else e.file_name) if to_dir else host_dst
        try:
            volume.read_file(e).export(str(out))
        except ProDOSError as ex:
            notes.append(f"Skipping {e.file_name}: {ex}")
    return notes

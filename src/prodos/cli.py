import logging
import os
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from os import path
from pathlib import Path
from typing import Annotated

import typer
from typer import Argument, Option
from typer_di import Depends, TyperDI

from prodos.check import check_volume
from prodos.device import DeviceFormat, DeviceMode
from prodos.directory import Directory
from prodos.errors import ProDOSError
from prodos.file import guess_file_type, legal_name
from prodos.metadata import FileEntry, parse_access
from prodos.volmap import format_block_map, format_legend, walk_volume
from prodos.volume import Volume

logging.basicConfig(level=logging.WARN)

app = TyperDI()

def get_force(force: Annotated[bool, typer.Option("--force", "-f", help="Force overwrite existing files")] = False):
    return force

def get_log(log: Annotated[Path|None, typer.Option("--log", help="Write access log to file")] = None):
    return log

def get_recursive(recursive: Annotated[bool, typer.Option("--recursive", "-r", help="Recursively list subdirectories")] = False):
    return recursive

def get_path(path: Annotated[str, Argument(help="ProDOS path (e.g., /DIR/FILE)")]) -> str:
    return path

def get_optional_path(path: Annotated[str | None, Argument(help="ProDOS path (e.g., /DIR/FILE)")] = None) -> str | None:
    return path

def get_optional_paths(paths: Annotated[list[str], Argument(help="ProDOS path(s) (e.g., /DIR/FILE)", default_factory=list)]) -> list[str]:
    return paths

def get_paths(paths: Annotated[list[str], Argument(help="ProDOS path(s) (e.g., /DIR/FILE)")]) -> list[str]:
    return paths

def get_volume_path(volume: Annotated[Path, Argument(help="Path to disk image file")]) -> Path:
    return volume

def get_output(target: Annotated[Path|None, Option("--output", "-o", help="Output to a copy of the volume")] = None) -> Path|None:
    return target

def get_host_paths(paths: Annotated[list[str], Argument(help="Host file path(s)", default_factory=list)]) -> list[str]:
    return paths

@contextmanager
def open_volume(source: Path, output: Path|None=None, mode: DeviceMode='ro', log: Path|None=None) -> Generator[Volume]:
    """Open a volume for a command, reporting any ProDOSError as a clean exit"""
    try:
        if output:
            shutil.copy(source, output)
            source = output
        volume = Volume.open(source, mode=mode)
        try:
            yield volume
        finally:
            volume.close()
            if log:
                volume.device.write_access_log(log)
    except ProDOSError as e:
        print(f"Error: {e}")
        raise typer.Exit(1) from None


def _split_path(path: str) -> tuple[str, str]:
    if '/' in path:
        parent, name = path.rsplit('/', 1)
        return parent or '/', name
    return '/', path


def _destination(volume: Volume, dst: str, dst_entry: FileEntry | None, name: str) -> tuple[Directory, str]:
    """Target directory and name for cp/mv: into dst if it's a directory, else as dst"""
    if dst_entry and dst_entry.is_dir:
        return volume.read_directory(dst_entry), name
    parent_path, new_name = _split_path(dst)
    parent_entry = volume.path_entry(parent_path)
    if not parent_entry or not parent_entry.is_dir:
        print(f"Parent directory {parent_path} not found")
        raise typer.Exit(1)
    return volume.read_directory(parent_entry), legal_name(new_name)


def _hex(value: str | None, what: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value.removeprefix('$').removeprefix('0x'), 16)
    except ValueError:
        print(f"Invalid {what} {value!r}, expected hex like FF or $2000")
        raise typer.Exit(1) from None


@app.command()
def create(
        dest: Path = Depends(get_volume_path),
        size: Annotated[int, Option("--size", "-s", help="Total blocks (512 bytes/block)")] = 65535,
        name: Annotated[str, Option("--name", "-n", help="Volume name (max 15 chars)")] = 'PYP8',
        format: Annotated[DeviceFormat, Option("--format", "-t", help="Disk image format")] = DeviceFormat.prodos,
        force: bool = Depends(get_force),
        log: Path|None = Depends(get_log),
    ):
    """
    Create an empty volume with BLOCKS total blocks (512 bytes/block)
    """
    if dest.suffix.lower() == '.' + DeviceFormat.twomg.value:
        format = DeviceFormat.twomg

    if dest.exists():
        if not force:
            print(f"Destination {dest} exists, use --force to override")
            raise typer.Exit(5)
        os.remove(dest)

    try:
        volume = Volume.create(dest=dest, volume_name=name, total_blocks=size, format=format)
    except ProDOSError as e:
        print(f"Error: {e}")
        raise typer.Exit(1) from None
    volume.close()
    if log:
        volume.device.write_access_log(log)


@app.command()
def info(
        source: Path = Depends(get_volume_path),
        show_map: Annotated[bool, Option("--map", "-m", help="Show visual block usage map")] = False,
        log: Path|None = Depends(get_log),
    ):
    """
    Show basic volume information
    """
    with open_volume(source, log=log) as volume:
        print(volume)

        if show_map:
            print("\nBlock usage map:")
            print()
            block_map = walk_volume(volume)
            print(format_block_map(block_map))
            print(format_legend())


@app.command()
def check(
        source: Path = Depends(get_volume_path),
        log: Path|None = Depends(get_log),
    ):
    """
    Check volume integrity: directory structure, block usage and the bit map
    """
    with open_volume(source, log=log) as volume:
        problems = check_volume(volume)
    for p in problems:
        print(p)
    if problems:
        print(f"{len(problems)} problem(s) found")
        raise typer.Exit(1)
    print("No problems found")


@app.command()
def ls(
        source: Path = Depends(get_volume_path),
        paths: list[str] = Depends(get_optional_paths),
        recursive: bool = Depends(get_recursive),
        log: Path|None = Depends(get_log),
    ):
    """
    Show volume listing for path like `/some/directory/some/file`

    Paths are case-insensitive, forward-slash separated (/) and start with a slash.
    """
    with open_volume(source, log=log) as volume:
        entries = volume.glob_paths(paths or ['/'])

        if not entries:
            print("No matching files found")
            raise typer.Exit(1)

        print(FileEntry.heading)
        print('-' * len(FileEntry.heading))

        while entries:
            e = entries.pop(0)
            if e.is_dir:
                d = volume.read_directory(e)
                print(d)
                if recursive:
                    entries += [e for e in d.entries if e.is_dir]
            else:
                print(e)
            print()


@app.command()
def cp(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        log: Path|None = Depends(get_log),
        ):
    """
    Copy single file (not directory) to target file,
    or one or more files to target directory.
    Directories are not copied: use globbing to expand as file lists.
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        entries = volume.glob_paths(src)
        if not entries:
            print("No matching files found")
            raise typer.Exit(1)

        dst_entry = volume.path_entry(dst)
        if len(entries) > 1 and not (dst_entry and dst_entry.is_dir):
            print(f"Target {dst} is not a directory")
            raise typer.Exit(1)

        for e in entries:
            if e.is_dir:
                print(f"Omitting directory {e.file_name}")
                continue
            f = volume.read_file(e)
            if f.resource_fork:
                print(f"Omitting extended file {e.file_name}")
                continue
            dest_dir, dest_name = _destination(volume, dst, dst_entry, e.file_name)
            dest_dir.write_file(replace(e, file_name=dest_name), f.data, overwrite=True)


@app.command()
def mv(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        log: Path|None = Depends(get_log),
    ):
    """
    Move single file to target file,
    or move one or more files (including directories) to target directory.
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        entries = volume.glob_paths(src)
        if not entries:
            print("No matching files found")
            raise typer.Exit(1)

        if any(e.is_volume_dir for e in entries):
            print("Cannot move root directory")
            raise typer.Exit(1)

        dst_entry = volume.path_entry(dst)
        if len(entries) > 1 and not (dst_entry and dst_entry.is_dir):
            print(f"Target {dst} is not a directory")
            raise typer.Exit(1)

        for e in entries:
            dest_dir, dest_name = _destination(volume, dst, dst_entry, e.file_name)
            volume.directory_of(e).move(e, dest_dir, dest_name)


@app.command()
def rm(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        output: Path|None = Depends(get_output),
        log: Path|None = Depends(get_log),
    ):
    """
    Remove file(s) at SRC
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        entries = volume.glob_paths(src)
        if not entries:
            print("No matching files found")
            raise typer.Exit(1)

        for e in entries:
            if e.is_dir:
                print(f"Not a file: {e.file_name} is a directory, use rmdir")
                raise typer.Exit(1)

        for e in entries:
            volume.directory_of(e).delete(e)


@app.command()
def mkdir(
        source: Path = Depends(get_volume_path),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        log: Path|None = Depends(get_log),
):
    """
    Create empty directory at DST
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        parent_path, name = _split_path(dst)

        if not name:
            print(f"Invalid directory name: {dst}")
            raise typer.Exit(1)

        parent_entry = volume.path_entry(parent_path)
        if not parent_entry:
            print(f"Parent directory not found: {parent_path}")
            raise typer.Exit(1)

        if not parent_entry.is_dir:
            print(f"Parent is not a directory: {parent_path}")
            raise typer.Exit(1)

        parent_dir = volume.read_directory(parent_entry)

        name = legal_name(name)
        if parent_dir.find(name):
            print(f"Entry already exists: {name}")
            raise typer.Exit(1)

        parent_dir.make_directory(name)


@app.command()
def rmdir(
        source: Path = Depends(get_volume_path),
        src: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        log: Path|None = Depends(get_log),
    ):
    """
    Remove empty directory at SRC
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        entry = volume.path_entry(src)
        if not entry:
            print(f"Directory not found: {src}")
            raise typer.Exit(1)

        if not entry.is_dir:
            print(f"Not a directory: {src}")
            raise typer.Exit(1)

        if not volume.read_directory(entry).is_empty:
            print(f"Directory not empty: {src}")
            raise typer.Exit(1)

        volume.directory_of(entry).delete(entry)


@app.command()
def chinfo(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        file_type: Annotated[str | None, Option("--type", "-t", help="New file type in hex, e.g. 04 or FF")] = None,
        aux_type: Annotated[str | None, Option("--aux", "-a", help="New aux type in hex, e.g. 2000")] = None,
        access: Annotated[str | None, Option("--access",
            help="New access flags, e.g. RWBND, from R=read W=write I=invisible B=backup N=rename D=destroy")] = None,
        output: Path|None = Depends(get_output),
        log: Path|None = Depends(get_log),
    ):
    """
    Change the file type, aux type or access flags of file(s) at SRC
    """
    ftype = _hex(file_type, 'file type')
    aux = _hex(aux_type, 'aux type')
    if ftype is None and aux is None and access is None:
        print("Nothing to change: use --type, --aux or --access")
        raise typer.Exit(1)

    with open_volume(source, output, mode='rw', log=log) as volume:
        flags = parse_access(access) if access is not None else None
        entries = volume.glob_paths(src)
        if not entries:
            print("No matching files found")
            raise typer.Exit(1)
        for e in entries:
            if e.is_volume_dir:
                print("Can't change info for the volume directory")
                raise typer.Exit(1)
            volume.directory_of(e).set_info(e, file_type=ftype, aux_type=aux, access=flags)


@app.command('import')
def host_import(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_host_paths),
        dst: str | None = Depends(get_optional_path),
        output: Path|None = Depends(get_output),
        loader: Annotated[Path | None, Option("--loader", "-l", help="Import boot loader from file")] = None,
        file_type: Annotated[str | None, Option("--type", "-t",
            help="File type in hex, e.g. 04 (TXT), 06 (BIN), FF (SYS); "
                 "default SYS for PRODOS and *.SYSTEM, otherwise BIN")] = None,
        aux_type: Annotated[str | None, Option("--aux", "-a",
            help="Aux type in hex, e.g. 2000 for a BIN load address")] = None,
        force: bool = Depends(get_force),
        log: Path|None = Depends(get_log),
    ):
    """
    Import host files to volume.

    Import single host file to target file, or one or more files to target directory.
    Directories are not imported: use host globbing to expand as file lists.
    Use --loader to import a boot loader to the volume.
    """
    ftype = _hex(file_type, 'file type')
    aux = _hex(aux_type, 'aux type') or 0

    with open_volume(source, output, mode='rw', log=log) as volume:
        if loader:
            volume.write_loader(loader.read_bytes())
            if not src:
                return

        if not src:
            print("Error: file paths required when not using --loader")
            raise typer.Exit(1)

        if dst is None:
            print("Error: destination path required when importing files")
            raise typer.Exit(1)

        bad = [f for f in src if not path.isfile(f)]
        if bad:
            print(f"Not regular host files: {', '.join(bad)}")
            raise typer.Exit(1)

        target = volume.path_entry(dst)
        renamed = ''
        if len(src) == 1 and (not target or not target.is_dir):
            # Possibly importing single file with a new name
            (dst, renamed) = path.split(dst)
            target = volume.path_entry(dst)

        if not target:
            print(f"Target not found: {dst}")
            raise typer.Exit(2)
        elif not target.is_dir:
            print(f"Target not a directory: {dst}")
            raise typer.Exit(3)

        d = volume.read_directory(target)

        for fname in src:
            name = legal_name(renamed or path.basename(fname))
            entry = d.find(name)
            if entry:
                if entry.is_dir:
                    print(f"Target {name} is a directory")
                    raise typer.Exit(4)
                elif not force:
                    print(f"Target file {name} exists, use --force to overwrite")
                    raise typer.Exit(5)
            metadata = FileEntry.new(name, file_type=guess_file_type(name) if ftype is None else ftype, aux_type=aux)
            d.write_file(metadata, Path(fname).read_bytes(), overwrite=force)


@app.command('export')
def host_export(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_optional_paths),
        loader: Annotated[Path | None, Option("--loader", "-l", help="Export boot loader to file")] = None,
        log: Path|None = Depends(get_log),
    ):
    """
    Export SRC to host DST, or SRC(s) to host DIRECTORY.
    Use --loader to export the boot loader blocks.
    """
    with open_volume(source, log=log) as volume:
        if loader:
            loader.write_bytes(volume.read_loader())
            if not src:
                return

        if not src:
            print("Error: paths required when not using --loader")
            raise typer.Exit(1)

        dst = src[0] if len(src) == 1 else src.pop()
        entries = volume.glob_paths(src)
        if not entries:
            print("No matching files found")
            raise typer.Exit(1)

        is_dir = path.isdir(dst)

        if len(entries) > 1 and not is_dir:
            print(f"{dst} must be an existing directory for multi file export")
            raise typer.Exit(1)

        for e in entries:
            if e.is_dir:
                print(f"Omitting directory {e.file_name}")
                continue
            out = dst if not is_dir else path.join(dst, e.file_name)
            try:
                volume.read_file(e).export(out)
            except ProDOSError as ex:
                print(f"Skipping {e.file_name}: {ex}")


if __name__ == "__main__":
    app()

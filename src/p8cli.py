from typing import Optional, Annotated
import logging
import typer
from typer import Option, Argument
from typer_di import TyperDI, Depends
import shutil
import os
from os import path
from pathlib import Path

from prodos.volume import Volume
from prodos.device import DeviceFormat, DeviceMode
from prodos.file import PlainFile, legal_path


logging.basicConfig(level=logging.WARN)

app = TyperDI()

def get_force(force: Annotated[bool, typer.Option("--force", "-f")] = False):
    return force

def get_recursive(recursive: Annotated[bool, typer.Option("--recursive", "-r")] = False):
    return recursive

def get_path(path: Annotated[str, Argument]) -> str:
    return path

def get_optional_paths(paths: Annotated[list[str], Argument(default_factory=list)]) -> list[str]:
    return paths

def get_paths(paths: Annotated[list[str], Argument]) -> list[str]:
    return paths

def get_volume_path(volume: Annotated[Path, Argument]) -> Path:
    return volume

def get_output(target: Annotated[Path|None, Option("--output", "-o")] = None) -> Path|None:
    return target

def open_volume(source: Path, output: Path|None=None, mode: DeviceMode= 'ro') -> Volume:
    if output:
        shutil.copy(source, output)
        source = output
    return Volume.from_file(source, mode=mode)


def _split_path(path: str) -> tuple[str, str]:
    if '/' in path:
        parent, name = path.rsplit('/', 1)
        return parent or '/', name
    return '/', path


@app.command()
def create(
        dest: Path = Depends(get_volume_path),
        size: int = 65535,
        name: str = 'PYP8',
        format: DeviceFormat = DeviceFormat.prodos,
        loader: Path | None = None,
        force: bool = Depends(get_force),
    ):
    """
    Create an empty volume with BLOCKS total blocks (512 bytes/block)
    """
    if path.splitext(dest)[1].upper() == '.' + DeviceFormat.twomg.value.upper():
        format = DeviceFormat.twomg

    if path.exists(dest):
        if not force:
            print(f"Destination {dest} exists, use --force to override")
            raise typer.Exit(5)
        os.remove(dest)

    Volume.create(
        dest=dest,
        volume_name=name,
        total_blocks=size,
        format=format,
        loader_path=loader,
    )


@app.command()
def info(source: Path = Depends(get_volume_path)):
    """
    Show basic volume information
    """
    print(open_volume(source))


@app.command()
def check(source: Path = Depends(get_volume_path),):
    """
    TODO Perform various volume integrity checks

    - validate parent_entry_number and parent_pointer for subdir header
    - validate header_pointer for file entry

    - check boot blocks, vol dir, block map marked used
    - volume total blocks matches volume size
    - recurse all files and directories
        - check known file type
        - read every file,
        - check file blocks used matches visited
        - check rest of index blocks are zero(?)
    - warn if read block not marked active
    - warn if used blocks not accessed
    """
    print("TODO: check")


def default_path(paths: Optional[list[str]]) -> list[str]:
    return paths or ['/']


@app.command()
def ls(
        source: Path = Depends(get_volume_path),
        paths: list[str] = Depends(get_optional_paths),
        recursive: bool = Depends(get_recursive),
    ):
    """
    Show volume listing for path like `/some/directory/some/file`

    Paths are case-insensitive, forward-slash separated (/) and start with a slash.
    """
    if not paths:
        paths = ['/']

    volume = open_volume(source)
    entries = volume.glob_paths(paths)

    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    while entries:
        e = entries.pop(0)
        if e.is_dir:
            dir = volume.read_directory(e)
            print(dir)
            if recursive:
                entries += [e for e in dir.entries if e.is_dir]
        else:
            print(e)
        print()


@app.command()
def cp(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        ):
    """
    Copy single file (not directory) to target file,
    or one or more files to target directory.
    Directories are not copied: use globbing to expand as file lists.
    """
    volume = open_volume(source, output, mode='rw')

    entries = volume.glob_paths(src)
    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    dst_entry = volume.path_entry(dst)
    is_dst_dir = dst_entry and dst_entry.is_dir

    if len(entries) > 1 and not is_dst_dir:
        print(f"Target {dst} is not a directory")
        raise typer.Exit(1)

    for e in entries:
        if e.is_dir:
            print(f"Omitting directory {e.file_name}")
            continue

        if is_dst_dir:
            assert dst_entry # for typing
            dest_dir = volume.read_directory(dst_entry)
            dest_name = e.file_name
        else:
            parent_path, name = _split_path(dst)
            parent_entry = volume.path_entry(parent_path)
            if not parent_entry or not parent_entry.is_dir:
                 print(f"Parent directory {parent_path} not found")
                 raise typer.Exit(1)
            dest_dir = volume.read_directory(parent_entry)
            dest_name = legal_path(name)

        f_src = volume.read_simple_file(e)
        f_dst = PlainFile(
            device=volume.device,
            file_name=dest_name,
            data=f_src.data
        )
        dest_dir.add_simple_file(f_dst)


@app.command()
def mv(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
    ):
    """
    Move single file to target file,
    or move one or more files (including directories) to target directory.
    """
    volume = open_volume(source, output, mode='rw')

    entries = volume.glob_paths(src)
    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    # Check for attempting to move root directory
    for e in entries:
        if e.header_pointer == 0:
            print("Cannot move root directory")
            raise typer.Exit(1)

    dst_entry = volume.path_entry(dst)
    is_dst_dir = dst_entry and dst_entry.is_dir

    if len(entries) > 1 and not is_dst_dir:
        print(f"Target {dst} is not a directory")
        raise typer.Exit(1)

    for e in entries:
        if is_dst_dir:
            assert dst_entry # for typing
            dest_dir = volume.read_directory(dst_entry)
            dest_name = e.file_name
        else:
            parent_path, name = _split_path(dst)
            parent_entry = volume.path_entry(parent_path)
            if not parent_entry or not parent_entry.is_dir:
                 print(f"Parent directory {parent_path} not found")
                 raise typer.Exit(1)
            dest_dir = volume.read_directory(parent_entry)
            dest_name = legal_path(name)

        src_dir = volume.parent_directory(e)

        # Use the appropriate move method based on file type
        try:
            if e.is_dir:
                src_dir.move_directory(e, dest_dir, dest_name)
            else:
                src_dir.move_simple_file(e, dest_dir, dest_name)
        except ValueError as ex:
            print(str(ex))
            raise typer.Exit(1)


@app.command()
def rm(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        output: Path|None = Depends(get_output),
    ):
    """
    Remove simple file(s) at SRC
    """
    volume = open_volume(source, output, mode='rw')

    entries = volume.glob_paths(src)
    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    for e in entries:
        if not e.is_plain_file:
            print(f"Not a simple file: {e.file_name}")
            raise typer.Exit(1)

    for e in entries:
        dir = volume.parent_directory(e)
        dir.remove_simple_file(e)


@app.command()
def mkdir(
        source: Path = Depends(get_volume_path),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
):
    """
    Create empty directory at DST
    """
    volume = open_volume(source, output, mode='rw')

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

    name = legal_path(name)
    if parent_dir.file_entry(name):
        print(f"Entry already exists: {name}")
        raise typer.Exit(1)

    parent_dir.add_directory(file_name=name)


@app.command()
def rmdir(
        source: Path = Depends(get_volume_path),
        src: str = Depends(get_path),
        output: Path|None = Depends(get_output),
    ):
    """
    Remove empty directory at SRC
    """
    volume = open_volume(source, output, mode='rw')

    entry = volume.path_entry(src)
    if not entry:
        print(f"Directory not found: {src}")
        raise typer.Exit(1)

    if not entry.is_dir:
        print(f"Not a directory: {src}")
        raise typer.Exit(1)

    directory = volume.read_directory(entry)
    if not directory.is_empty:
        print(f"Directory not empty: {src}")
        raise typer.Exit(1)

    parent = volume.parent_directory(entry)
    parent.remove_directory(entry)


@app.command('import')
def host_import(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        force: bool = Depends(get_force),
    ):
    """
    Import host files to volume.

    Import single host file to target file, or one or more files to target directory.
    Directories are not imported: use host globbing to expand as file lists.
    """
    volume = open_volume(source, output, mode='rw')

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

    # Now we have a single entry and possibly a target_name
    dir = volume.read_directory(target)

    for fname in src:
        name = legal_path(renamed or path.basename(fname))
        entry = dir.file_entry(name)
        if entry:
            if entry.is_dir:
                print(f"Target {name} is a directory")
                raise typer.Exit(4)
            elif not force:
                print(f"Target file {name} exists, use --force to overwrite")
                raise typer.Exit(5)
            else:
                dir.remove_simple_file(entry)
        f = PlainFile(
            device=volume.device,
            file_name=name,
            data=open(fname, 'rb').read()
        )
        dir.add_simple_file(f)


@app.command('export')
def host_export(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        output: Path|None = Depends(get_output),
    ):
    """
    Export SRC to host DST, or SRC(s) to host DIRECTORY
    """
    dst = src[0] if len(src) == 1 else src.pop()
    volume = open_volume(source, output)

    entries = volume.glob_paths(src)
    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    is_dir = path.isdir(dst)

    if len(entries) > 1 and not is_dir:
        print(f"{dst} must be an existing directory for multi file export")
        raise typer.Exit(1)

    for e in entries:
        out = dst if not is_dir else path.join(dst, e.file_name)
        volume.read_simple_file(e).export(out)


if __name__ == "__main__":
    app()

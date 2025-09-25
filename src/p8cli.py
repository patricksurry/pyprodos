from typing import Literal, Optional, List, Annotated
from dataclasses import dataclass
import logging
import typer
import shutil
from os import path
from prodos.volume import Volume
from prodos.device import DeviceFormat
from prodos.file import SimpleFile

logging.basicConfig(level=logging.WARN)


@dataclass
class State:
    volume_filename: str = ''


app = typer.Typer()
state = State()


@app.command()
def create(
        size: int = 65535,
        name: str = 'PYP8',
        format: DeviceFormat = DeviceFormat.prodos,
        loader: str = ''):
    """
    Create an empty volume with BLOCKS total blocks (512 bytes/block)
    """
    Volume.create(
        file_name=state.volume_filename,
        volume_name=name,
        total_blocks=size,
        format=format,
        loader_file_name=loader
    )


@app.command()
def info():
    """
    Show basic volume information
    """
    print(Volume.from_file(state.volume_filename))


@app.command()
def check():
    """
    TODO Perform various volume integrity checks
    """
    print("TODO: check")


def default_path(paths: Optional[list[str]]) -> list[str]:
    return paths or ['/']


@app.command()
def ls(paths: Annotated[Optional[list[str]], typer.Argument(callback=default_path)] = None):
    """
    Show volume listing for path like `/some/directory/some/file`

    Paths are case-insensitive, forward-slash separated (/) and start with a slash.
    """
    assert paths is not None, "ls: No paths"

    volume = Volume.from_file(state.volume_filename)
    entries = volume.glob_paths(paths)

    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    for e in entries:
        if e.is_dir:
            print(volume.read_directory(e))
        else:
            print(e)
        print()


@app.command()
def cp(src: list[str], dst: str):
    """
    TODO Copy SOURCE to DEST, or multiple SOURCE(s) to DIRECTORY
    """

    #TODO: glob rules and DST dir or target

    print("TODO: cp")


@app.command()
def mv(src: list[str], dst: str):
    """
    TODO Move from SRC to DST
    """
    print("TODO: mv")


@app.command()
def rm(src: list[str]):
    """
    Remove simple file(s) at SRC
    """
    volume = Volume.from_file(state.volume_filename, mode='rw')

    entries = volume.glob_paths(src)
    if not entries:
        print("No matching files found")
        raise typer.Exit(1)

    for e in entries:
        if not e.is_simple_file:
            print(f"Not a simple file: {e.file_name}")
            raise typer.Exit(1)

    for e in entries:
        dir = volume.parent_directory(e)
        dir.remove_simple_file(e)


@app.command()
def rmdir(src: list[str]):
    """
    TODO Remove empty directory at SRC
    """
    print("TODO: rmdir")


@app.command('import')
def host_import(src: list[str]):
    """
    Import host files at SRC to DST

    Copy SRC to DEST, or multiple SRC(s) to DIRECTORY

    Note SRC globbing happens in the host shell so nothing is expanded here
    """
    volume = Volume.from_file(state.volume_filename, mode='rw')

    dst = src[0] if len(src) == 1 else src.pop()
    base, target_name = dst, ''

    entries = volume.glob_paths([base])
    if len(entries) == 0:
        # e.g. import foo /somewhere/bar
        (base, target_name) = path.split(dst)
        entries = volume.glob_paths([base])

    if len(entries) != 1:
        if len(entries) == 0:
            print(f"Destination {dst} not found")
        elif len(entries) > 1:
            print(f"Destination {dst} matched multiple files!")
        raise typer.Exit(1)

    target = entries[0]
    if not target.is_dir:
        # existing target
        if len(entries) > 1:
            print("Destination for multiple files must be a directory")
            raise typer.Exit(1)
        dir = volume.parent_directory(target)
        dir.remove_simple_file(target)
    else:
        if target_name and len(entries) > 1:
            print("Destination for multiple files must be a directory")
            raise typer.Exit(1)
        dir = volume.read_directory(target)

    for fname in src:
        f = SimpleFile(
            device=volume.device,
            file_name=target_name or fname,
            data=open(fname, 'rb').read()
        )
        dir.write_simple_file(f)


@app.command('export')
def host_export(src: list[str]):
    """
    Export SRC to host DST, or SRC(s) to host DIRECTORY
    """
    dst = src[0] if len(src) == 1 else src.pop()
    volume = Volume.from_file(state.volume_filename)

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


@app.callback()
def shared(volume_filename: str, source: str=''):
    """
    prodos-pyfs CLI

    Simple prodos volume management from python
    """
    if source:
        shutil.copy(source, volume_filename)

    state.volume_filename = volume_filename


if __name__ == "__main__":
    app()



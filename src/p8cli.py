from typing import Literal, Optional, List, Annotated
from dataclasses import dataclass
import logging
import typer
from os import path
from prodos.volume import Volume

logging.basicConfig(level=logging.INFO)


@dataclass
class State:
    volume_filename: str = ''
    mode: Literal['readonly', 'update'] = 'readonly'


app = typer.Typer()
state = State()


@app.command()
def create(blocks: Annotated[int, typer.Option("--blocks", "-n")] = 65535):
    """
    Create an empty volume with BLOCKS total blocks (512 bytes/block)
    """
    if path.exists(state.volume_filename):
        print(f"Volume file {state.volume_filename} already exists!")
        raise typer.Exit(1)

    print("TODO: create")
    # create and write an empty volume


@app.command()
def info():
    """
    Show basic volume information
    """
    print(Volume.from_file(state.volume_filename))


@app.command()
def check():
    """
    Perform various volume integrity checks
    """
    print("TODO: check")


def default_path(paths: Optional[List[str]]) -> List[str]:
    return paths or ['/']


@app.command()
def ls(paths: Annotated[List[str], typer.Argument(callback=default_path)] = None):
    """
    Show volume listing for path like `/some/directory/some/file`

    Paths are case-insensitive, forward-slash separated (/) and start with a slash.
    """

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
def cp(src: List[str], dst: str):
    """
    Copy SOURCE to DEST, or multiple SOURCE(s) to DIRECTORY

    TODO: glob rules and DST dir or target
    """
    print("TODO: cp")


@app.command()
def mv(src: List[str], dst: str):
    """
    Move from SRC to DST
    TODO: glob rules and DST dir or target
    """
    print("TODO: mv")


@app.command()
def rm(src: List[str]):
    """
    Remove simple file(s) at SRC
    """
    print("TODO: rm")


@app.command()
def rmdir(src: List[str]):
    """
    Remove empty directory at SRC
    """
    print("TODO: rmdir")


@app.command('import')
def host_import(src: List[str], dst: str):
    """
    Import host files at SRC to DST
    """
    print("TODO: import")


@app.command('export')
def host_export(src: List[str], dst: str):
    """
    Export SOURCE to host DEST, or multiple SOURCE(s) to host DIRECTORY
    """
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
def shared(
        volume_filename: str,
        update: Annotated[bool, typer.Option("--update", "-u")] = False,
    ):
    """
    prodos-pyfs CLI

    Simple prodos volume management from python
    """
    state.volume_filename = volume_filename
    state.mode = 'write' if update else 'readonly'


if __name__ == "__main__":
    app()



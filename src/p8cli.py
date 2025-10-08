from typing import Optional, Annotated
import logging
import typer
from typer import Option, Argument
from typer_di import TyperDI, Depends
import shutil
from os import path
from pathlib import Path

from prodos.volume import Volume
from prodos.device import DeviceFormat, DeviceMode
from prodos.file import SimpleFile, legal_path


logging.basicConfig(level=logging.WARN)

app = TyperDI()

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


@app.command()
def create(
        dest: Path = Depends(get_volume_path),
        size: int = 65535,
        name: str = 'PYP8',
        format: DeviceFormat = DeviceFormat.prodos,
        loader: str = '',       #TODO path
        #TODO force
    ):
    """
    Create an empty volume with BLOCKS total blocks (512 bytes/block)
    """
    Volume.create(
        dest=dest,
        volume_name=name,
        total_blocks=size,
        format=format,
        loader_file_name=loader
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

    - check boot blocks, vol dir, block map marked used
    - volume total blocks matches volume size
    - walk and read every file, check file type
    - check file blocks used
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

    for e in entries:
        if e.is_dir:
            print(volume.read_directory(e))
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
    TODO Copy SOURCE to DEST, or multiple SOURCE(s) to DIRECTORY
    """
    #TODO: glob rules and DST dir or target

    print("TODO: cp")
    volume = open_volume(source, output, mode='rw')


@app.command()
def mv(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
    ):
    """
    TODO Move from SRC to DST
    """
    print("TODO: mv")
    volume = open_volume(source, output, mode='rw')


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
        if not e.is_simple_file:
            print(f"Not a simple file: {e.file_name}")
            raise typer.Exit(1)

    for e in entries:
        dir = volume.parent_directory(e)
        dir.remove_simple_file(e)


@app.command()
def rmdir(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        output: Path|None = Depends(get_output),
    ):
    """
    TODO Remove empty directory at SRC
    """
    print("TODO: rmdir")
    volume = open_volume(source, output)


@app.command('import')
def host_import(
        source: Path = Depends(get_volume_path),
        src: list[str] = Depends(get_paths),
        dst: str = Depends(get_path),
        output: Path|None = Depends(get_output),
        force: bool = False
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
        if renamed and (entry := dir.file_entry(name)):
            if entry.is_dir:
                print(f"Target {name} is a directory")
                raise typer.Exit(4)
            elif not force:
                print(f"Target file {name} exists, use --force to overwrite")
                raise typer.Exit(5)
            else:
                dir.remove_simple_file(entry)
        f = SimpleFile(
            device=volume.device,
            file_name=name,
            data=open(fname, 'rb').read()
        )
        dir.write_simple_file(f)


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



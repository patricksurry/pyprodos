"""
The prodos command line: each command opens a volume, calls the core and reports ProDOSError cleanly.
`prodos shell` mounts a volume for an interactive session with the same commands.
"""
import logging
import os
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer import Argument, Option

from prodos.check import check_volume
from prodos.device import DeviceFormat, DeviceMode
from prodos.errors import ProDOSError
from prodos.host import export_files, import_files, prodos_text
from prodos.listing import listing
from prodos.metadata import parse_access, parse_file_type, parse_hex
from prodos.shell import Shell
from prodos.volmap import format_block_map, format_legend, walk_volume
from prodos.volume import Volume

logging.basicConfig(level=logging.WARN)

app = typer.Typer()
console = Console(highlight=False, soft_wrap=True)

# arguments and options shared by several commands
VolumeArg = Annotated[Path, Argument(help="Path to disk image file")]
PathArg = Annotated[str, Argument(help="ProDOS path (e.g., /DIR/FILE)")]
PathsArg = Annotated[list[str], Argument(help="ProDOS path(s) (e.g., /DIR/FILE)")]
OptionalPathsArg = Annotated[list[str] | None, Argument(help="ProDOS path(s) (e.g., /DIR/FILE)")]
OutputOpt = Annotated[Path | None, Option("--output", "-o", help="Output to a copy of the volume")]
LogOpt = Annotated[Path | None, Option("--log", help="Write access log to file")]
ForceOpt = Annotated[bool, Option("--force", "-f", help="Force overwrite existing files")]
FileTypeOpt = Annotated[str | None, Option("--type", "-t",
    help="File type as a name (TXT, BIN, BAS, SYS) or hex, e.g. 04 or FF")]
AuxTypeOpt = Annotated[str | None, Option("--aux", "-a", help="Aux type in hex, e.g. 2000 for a BIN load address")]


@contextmanager
def reporting_errors() -> Generator[None]:
    """Report a ProDOSError as a clean exit"""
    try:
        yield
    except ProDOSError as e:
        print(f"Error: {e}")
        raise typer.Exit(1) from None


@contextmanager
def open_volume(source: Path, output: Path | None = None, mode: DeviceMode = 'ro',
        log: Path | None = None) -> Generator[Volume]:
    """Open a volume for a command, optionally working on a copy at output"""
    with reporting_errors():
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


def print_notes(notes: list[str]):
    for note in notes:
        print(note)


@app.command()
def create(
        dest: VolumeArg,
        size: Annotated[int, Option("--size", "-s", help="Total blocks (512 bytes/block)")] = 65535,
        name: Annotated[str, Option("--name", "-n", help="Volume name (max 15 chars)")] = 'PYP8',
        format: Annotated[DeviceFormat, Option("--format", "-t", help="Disk image format")] = DeviceFormat.prodos,
        force: ForceOpt = False,
        log: LogOpt = None,
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

    with reporting_errors():
        volume = Volume.create(dest=dest, volume_name=name, total_blocks=size, format=format)
    volume.close()
    if log:
        volume.device.write_access_log(log)


@app.command()
def info(
        source: VolumeArg,
        show_map: Annotated[bool, Option("--map", "-m", help="Show visual block usage map")] = False,
        log: LogOpt = None,
    ):
    """
    Show basic volume information
    """
    with open_volume(source, log=log) as volume:
        print(volume)
        if show_map:
            print("\nBlock usage map:\n")
            print(format_block_map(walk_volume(volume)))
            print(format_legend())


@app.command()
def check(source: VolumeArg, log: LogOpt = None):
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
        source: VolumeArg,
        paths: OptionalPathsArg = None,
        recursive: Annotated[bool, Option("--recursive", "-r", help="Recursively list subdirectories")] = False,
        log: LogOpt = None,
    ):
    """
    Show volume listing for path like `/some/directory/some/file`

    Paths are case-insensitive, forward-slash separated (/) and start with a slash.
    """
    with open_volume(source, log=log) as volume:
        for line in listing(volume, paths or ['/'], recursive):
            console.print(line)


@app.command()
def cat(source: VolumeArg, paths: PathsArg, log: LogOpt = None):
    """
    Show the contents of text file(s), converting Apple II text to host text
    """
    with open_volume(source, log=log) as volume:
        for e in volume.find_entries(paths):
            if e.is_dir:
                raise ProDOSError(f"{e.file_name} is a directory")
            print(prodos_text(volume.read_file(e).data), end='')


@app.command()
def cp(source: VolumeArg, src: PathsArg, dst: PathArg, output: OutputOpt = None, log: LogOpt = None):
    """
    Copy single file (not directory) to target file,
    or one or more files to target directory.
    Directories are not copied: use globbing to expand as file lists.
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        print_notes(volume.copy(src, dst))


@app.command()
def mv(source: VolumeArg, src: PathsArg, dst: PathArg, output: OutputOpt = None, log: LogOpt = None):
    """
    Move single file to target file,
    or move one or more files (including directories) to target directory.
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        volume.move(src, dst)


@app.command()
def rm(source: VolumeArg, src: PathsArg, output: OutputOpt = None, log: LogOpt = None):
    """
    Remove file(s) at SRC; use rmdir for directories
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        volume.remove(src)


@app.command()
def mkdir(source: VolumeArg, dst: PathArg, output: OutputOpt = None, log: LogOpt = None):
    """
    Create empty directory at DST
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        volume.make_directory(dst)


@app.command()
def rmdir(source: VolumeArg, src: PathArg, output: OutputOpt = None, log: LogOpt = None):
    """
    Remove empty directory at SRC
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        volume.remove_directory(src)


@app.command()
def chinfo(
        source: VolumeArg,
        src: PathsArg,
        file_type: FileTypeOpt = None,
        aux_type: Annotated[str | None, Option("--aux", "-a", help="New aux type in hex, e.g. 2000")] = None,
        access: Annotated[str | None, Option("--access",
            help="New access flags, e.g. RWBND, from R=read W=write I=invisible B=backup N=rename D=destroy")] = None,
        output: OutputOpt = None,
        log: LogOpt = None,
    ):
    """
    Change the file type, aux type or access flags of file(s) at SRC
    """
    if file_type is None and aux_type is None and access is None:
        print("Nothing to change: use --type, --aux or --access")
        raise typer.Exit(1)
    with open_volume(source, output, mode='rw', log=log) as volume:
        volume.set_info(
            src,
            file_type=None if file_type is None else parse_file_type(file_type),
            aux_type=None if aux_type is None else parse_hex(aux_type, 'aux type'),
            access=None if access is None else parse_access(access),
        )


@app.command('import')
def host_import(
        source: VolumeArg,
        src: Annotated[list[Path] | None, Argument(help="Host file path(s)")] = None,
        dst: Annotated[str | None, Argument(help="ProDOS path (e.g., /DIR/FILE)")] = None,
        output: OutputOpt = None,
        loader: Annotated[Path | None, Option("--loader", "-l", help="Import boot loader from file")] = None,
        file_type: FileTypeOpt = None,
        aux_type: AuxTypeOpt = None,
        force: ForceOpt = False,
        log: LogOpt = None,
    ):
    """
    Import host files to volume.

    Import single host file to target file, or one or more files to target directory.
    Host names like NAME#FF2000 set the file type and aux type (here SYS at $2000);
    otherwise the type defaults to SYS for PRODOS and *.SYSTEM and BIN for anything else.
    Directories are not imported: use host globbing to expand as file lists.
    Use --loader to import a boot loader to the volume.
    """
    with open_volume(source, output, mode='rw', log=log) as volume:
        if loader:
            volume.write_loader(loader.read_bytes())
            if not src:
                return
        if not src or dst is None:
            raise ProDOSError("Host file path(s) and a ProDOS destination are required, unless using --loader")
        import_files(
            volume, src, dst,
            file_type=None if file_type is None else parse_file_type(file_type),
            aux_type=None if aux_type is None else parse_hex(aux_type, 'aux type'),
            overwrite=force,
        )


@app.command('export')
def host_export(
        source: VolumeArg,
        src: OptionalPathsArg = None,
        loader: Annotated[Path | None, Option("--loader", "-l", help="Export boot loader to file")] = None,
        typed: Annotated[bool, Option("--typed", "-T",
            help="Add the file type and aux type to host names, like NAME#FF2000")] = False,
        log: LogOpt = None,
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
            raise ProDOSError("Paths required when not using --loader")
        dst = src[0] if len(src) == 1 else src.pop()
        print_notes(export_files(volume, src, Path(dst), typed=typed))


@app.command()
def shell(
        source: VolumeArg,
        read_only: Annotated[bool, Option("--read-only", "-r", help="Open the volume read-only")] = False,
        output: OutputOpt = None,
        log: LogOpt = None,
    ):
    """
    Mount a volume and work on it interactively, with cd, relative paths,
    tab completion, and put/get to move files to and from the host.
    """
    with open_volume(source, output, mode='ro' if read_only else 'rw', log=log) as volume:
        Shell(volume).cmdloop()


if __name__ == "__main__":
    app()

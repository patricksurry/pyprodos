"""
An interactive shell on a mounted volume, in the style of sftp.

ProDOS commands (ls, cd, cp, ...) work on the volume with paths relative to the
current directory, while lcd, lls and !command work on the host, and put/get
move files between the two.  The commands call the same core operations as the
one-shot command line.
"""
import argparse
import cmd
import glob
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from .check import check_volume
from .errors import ProDOSError
from .host import export_files, import_files, prodos_text
from .listing import entry_style, listing
from .metadata import parse_access, parse_file_type, parse_hex
from .volmap import format_block_map, format_legend, walk_volume
from .volume import Volume, resolve_path

try:
    import readline
except ImportError:     # e.g. Windows without pyreadline
    readline = None


def _parser(prog: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=prog, description=description, exit_on_error=False)


def _type_options(p: argparse.ArgumentParser):
    p.add_argument('-t', '--type', help="file type as a name (TXT, BIN, BAS, SYS) or hex")
    p.add_argument('-a', '--aux', help="aux type in hex, e.g. 2000")


class Shell(cmd.Cmd):
    intro = "Type help for a list of commands, or help <command>.  exit or ^D to quit."

    def __init__(self, volume: Volume, console: Console | None = None):
        super().__init__()
        self.volume = volume
        self.cwd = '/'
        self.console = console or Console(highlight=False, soft_wrap=True)
        self.update_prompt()

    # --- plumbing

    def update_prompt(self):
        prompt = f"{self.volume.header.file_name}:{self.cwd}"
        if self.console.is_terminal and readline and 'libedit' not in (readline.__doc__ or ''):
            # \001 and \002 tell GNU readline the color codes take no space (libedit mangles them)
            prompt = f"\001\033[1;34m\002{prompt}\001\033[0m\002"
        self.prompt = prompt + '> '

    def print(self, *objects: str | Text, style: str | None = None):
        self.console.print(*objects, style=style)

    def error(self, message: str):
        self.print(Text(f"Error: {message}", style='bold red'))

    def path(self, p: str) -> str:
        """Absolute ProDOS path from one relative to the current directory"""
        return resolve_path(p, self.cwd)

    def paths(self, ps: list[str]) -> list[str]:
        return [self.path(p) for p in ps]

    def preloop(self):
        if readline:
            readline.set_completer_delims(' \t\n')
            if 'libedit' in (readline.__doc__ or ''):
                readline.parse_and_bind('bind ^I rl_complete')

    def cmdloop(self, intro: str | None = None):
        while True:
            try:
                super().cmdloop(intro)
                return
            except KeyboardInterrupt:
                self.print('^C')
                intro = ''

    def onecmd(self, line: str) -> bool:
        try:
            return super().onecmd(line)
        except ProDOSError as e:
            self.error(str(e))
        except (OSError, ValueError, argparse.ArgumentError) as e:
            self.error(str(e))
        except SystemExit:
            pass    # argparse already printed usage or help
        return False

    def postcmd(self, stop: bool, line: str) -> bool:
        self.volume.flush()
        self.update_prompt()
        return stop

    def emptyline(self) -> bool:
        return False

    def default(self, line: str):
        self.error(f"Unknown command {line.split()[0]!r}, try help")

    # --- completion

    def complete_prodos(self, text: str) -> list[str]:
        """Complete a ProDOS path like SYS or /SYSTEM/FI"""
        if '/' in text:
            base, prefix = text.rsplit('/', 1)
            base += '/'
        else:
            base, prefix = '', text
        try:
            e = self.volume.path_entry(self.path(base or '.'))
            if not e or not e.is_dir:
                return []
            entries = self.volume.read_directory(e).entries
        except ProDOSError:
            return []
        return [
            base + x.file_name + ('/' if x.is_dir else '')
            for x in entries if x.file_name.startswith(prefix.upper())
        ]

    def complete_host(self, text: str) -> list[str]:
        return [p + ('/' if os.path.isdir(p) else '') for p in glob.glob(os.path.expanduser(text) + '*')]

    def completedefault(self, *ignored: Any) -> list[str]:
        text, _line, _begidx, _endidx = ignored
        return self.complete_prodos(text)

    def complete_put(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return self.complete_host(text)

    complete_lcd = complete_lls = complete_put

    # --- ProDOS commands

    def do_ls(self, arg: str):
        """ls [-r] [PATH...]: list files, by default in the current directory"""
        p = _parser('ls', "List files")
        p.add_argument('-r', '--recursive', action='store_true', help="list subdirectories too")
        p.add_argument('paths', nargs='*')
        a = p.parse_args(shlex.split(arg))
        for line in listing(self.volume, self.paths(a.paths or ['.']), a.recursive):
            self.print(line)

    def do_cd(self, arg: str):
        """cd [PATH]: change the current directory, by default to the volume directory"""
        path = self.path(arg.strip() or '/')
        e = self.volume.path_entry(path)
        if not e:
            raise ProDOSError(f"{path} not found")
        if not e.is_dir:
            raise ProDOSError(f"{path} is not a directory")
        self.cwd = path

    def do_pwd(self, arg: str):
        """pwd: show the current directory"""
        self.print(self.cwd)

    def do_cat(self, arg: str):
        """cat PATH...: show text file(s)"""
        for e in self.volume.find_entries(self.paths(shlex.split(arg))):
            if e.is_dir:
                raise ProDOSError(f"{e.file_name} is a directory")
            self.console.out(prodos_text(self.volume.read_file(e).data), end='', highlight=False)

    def do_cp(self, arg: str):
        """cp SRC... DST: copy file(s) to a new name or into a directory"""
        *srcs, dst = shlex.split(arg) or ['']
        if not srcs:
            raise ProDOSError("Usage: cp SRC... DST")
        for note in self.volume.copy(self.paths(srcs), self.path(dst)):
            self.print(note, style='yellow')

    def do_mv(self, arg: str):
        """mv SRC... DST: move or rename files and directories"""
        *srcs, dst = shlex.split(arg) or ['']
        if not srcs:
            raise ProDOSError("Usage: mv SRC... DST")
        self.volume.move(self.paths(srcs), self.path(dst))

    def do_rm(self, arg: str):
        """rm PATH...: remove file(s)"""
        paths = shlex.split(arg)
        if not paths:
            raise ProDOSError("Usage: rm PATH...")
        self.volume.remove(self.paths(paths))

    def do_mkdir(self, arg: str):
        """mkdir PATH: create a directory"""
        self.volume.make_directory(self.path(arg.strip()))

    def do_rmdir(self, arg: str):
        """rmdir PATH: remove an empty directory"""
        path = self.path(arg.strip())
        if self.cwd == path or self.cwd.startswith(path + '/'):
            raise ProDOSError("Can't remove the current directory")
        self.volume.remove_directory(path)

    def do_chinfo(self, arg: str):
        """chinfo [-t TYPE] [-a AUX] [--access FLAGS] PATH...: change file type, aux type or access"""
        p = _parser('chinfo', "Change file type, aux type or access flags")
        _type_options(p)
        p.add_argument('--access', help="access flags, e.g. RWBND")
        p.add_argument('paths', nargs='+')
        a = p.parse_args(shlex.split(arg))
        if a.type is None and a.aux is None and a.access is None:
            raise ProDOSError("Nothing to change: use -t, -a or --access")
        self.volume.set_info(
            self.paths(a.paths),
            file_type=None if a.type is None else parse_file_type(a.type),
            aux_type=None if a.aux is None else parse_hex(a.aux, 'aux type'),
            access=None if a.access is None else parse_access(a.access),
        )

    def do_info(self, arg: str):
        """info [-m]: show volume information, with -m a map of block usage"""
        self.print(repr(self.volume))
        if arg.strip() in ('-m', '--map'):
            self.console.out(format_block_map(walk_volume(self.volume)), end='')
            self.console.out(format_legend(), end='')

    def do_check(self, arg: str):
        """check: check volume integrity"""
        problems = check_volume(self.volume)
        for problem in problems:
            self.print(problem, style='red')
        self.print(f"{len(problems)} problem(s) found" if problems else "No problems found",
            style='bold red' if problems else 'green')

    # --- moving files between host and volume

    def do_put(self, arg: str):
        """
        put [-t TYPE] [-a AUX] [-f] HOSTFILE... [DST]: copy host file(s) to the volume.
        With one file it goes in the current directory, otherwise the last argument
        is the destination.  Host globs are expanded, and names like NAME#FF2000 set
        the file type and aux type.
        """
        p = _parser('put', "Copy host files to the volume")
        _type_options(p)
        p.add_argument('-f', '--force', action='store_true', help="overwrite existing files")
        p.add_argument('files', nargs='+')
        a = p.parse_args(shlex.split(arg))
        files: list[str] = a.files
        dst = files.pop() if len(files) > 1 else '.'
        hosts = [Path(m) for f in files for m in sorted(glob.glob(os.path.expanduser(f))) or [f]]
        for e in import_files(
            self.volume, hosts, self.path(dst),
            file_type=None if a.type is None else parse_file_type(a.type),
            aux_type=None if a.aux is None else parse_hex(a.aux, 'aux type'),
            overwrite=a.force,
        ):
            self.print(Text(repr(e), style=entry_style(e)))

    def do_get(self, arg: str):
        """
        get [-T] PATH... [HOSTDST]: copy file(s) from the volume to the host.
        With one path it goes in the host's current directory, otherwise the last
        argument is the host destination.  With -T host names get a #TTAAAA type suffix.
        """
        p = _parser('get', "Copy files from the volume to the host")
        p.add_argument('-T', '--typed', action='store_true', help="add #TTAAAA to host names")
        p.add_argument('paths', nargs='+')
        a = p.parse_args(shlex.split(arg))
        paths: list[str] = a.paths
        dst = paths.pop() if len(paths) > 1 else '.'
        for note in export_files(self.volume, self.paths(paths), Path(dst).expanduser(), typed=a.typed):
            self.print(note, style='yellow')

    # --- host commands

    def do_lcd(self, arg: str):
        """lcd [DIR]: change the host's current directory, by default to your home"""
        os.chdir(os.path.expanduser(arg.strip() or '~'))
        self.print(os.getcwd())

    def do_lpwd(self, arg: str):
        """lpwd: show the host's current directory"""
        self.print(os.getcwd())

    def do_lls(self, arg: str):
        """lls [PATTERN]: list host files"""
        pattern = os.path.expanduser(arg.strip() or '*')
        if os.path.isdir(pattern):
            pattern = os.path.join(pattern, '*')
        for p in sorted(glob.glob(pattern)):
            if os.path.isdir(p):
                self.print(Text(p + '/', style='bold blue'))
            else:
                self.print(f"{p:40s} {os.path.getsize(p):>10d}")

    def do_shell(self, arg: str):
        """!COMMAND: run a host shell command"""
        subprocess.run(arg, shell=True)

    # --- leaving

    def do_exit(self, arg: str) -> bool:
        """exit: unmount the volume and quit"""
        return True

    do_quit = do_exit

    def do_EOF(self, arg: str) -> bool:
        """^D: unmount the volume and quit"""
        self.print()
        return True

"""
Regenerate the terminal screenshots in the README by scripting real shell sessions:

    uv run python docs/screenshots.py

Each session is recorded with rich and saved as an SVG terminal window.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.text import Text

from prodos.shell import Shell
from prodos.volume import Volume

DOCS = Path(__file__).parent
IMAGE = DOCS.parent / 'images' / 'ProDOS_2_4_3.po'


class Recording:
    def __init__(self):
        self.console = Console(file=StringIO(), record=True, width=88, force_terminal=True,
            color_system='truecolor', highlight=False, soft_wrap=True)

    def host(self, command: str):
        """Show and run a host command like 'prodos create ...'"""
        self.console.print(Text.assemble(('% ', 'bold'), command))
        args = command.split()
        assert args[0] == 'prodos'
        out = subprocess.run([sys.executable, '-m', 'prodos.cli', *args[1:]],
            capture_output=True, text=True, check=True).stdout
        if out:
            self.console.print(out, end='')

    def shell(self, image: str, lines: list[str], read_only: bool = False):
        """Show and run a prodos shell session"""
        self.console.print(Text.assemble(('% ', 'bold'), f"prodos shell {'--read-only ' if read_only else ''}{image}"))
        with Volume.open(Path(image), mode='ro' if read_only else 'rw') as volume:
            sh = Shell(volume, console=self.console)
            self.console.print(sh.intro)
            for line in lines:
                prompt = f"{volume.header.file_name}:{sh.cwd}"
                self.console.print(Text.assemble((prompt, 'bold blue'), '> ' + line))
                sh.onecmd(line)
                sh.postcmd(False, line)

    def save(self, name: str, title: str):
        self.console.save_svg(str(DOCS / name), title=title)
        print(f"wrote {DOCS / name}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, 'images').mkdir()
        shutil.copy(IMAGE, Path(tmp, 'images', IMAGE.name))
        cwd = Path.cwd()
        try:
            os.chdir(tmp)

            r = Recording()
            r.shell(f'images/{IMAGE.name}', [
                'ls',
                '!mkdir work',
                'get -T -l work/loader.bin PRODOS BASIC.SYSTEM work',
                'lls work',
                'exit',
            ], read_only=True)
            r.save('shell-explore.svg', 'Exploring the ProDOS 2.4.3 boot disk')

            r = Recording()
            r.host('prodos create boot.po --name MYVOL --size 280')
            r.shell('boot.po', [
                'put -l work/loader.bin work/*#FF*',
                'mkdir games',
                'ls',
                'check',
                'exit',
            ])
            r.save('shell-boot.svg', 'Building a boot disk')
        finally:
            os.chdir(cwd)


if __name__ == '__main__':
    main()

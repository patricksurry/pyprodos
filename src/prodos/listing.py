"""Directory listings for ls, styled for rich (plain text when the output isn't a terminal)."""
from rich.text import Text

from .metadata import FileEntry, FileType, access_byte
from .volume import Volume


def entry_style(e: FileEntry) -> str:
    if e.is_dir:
        return 'bold blue'
    if not e.access & access_byte('W'):
        return 'red'            # locked
    if e.file_type == FileType.SYS:
        return 'green'
    if not e.is_plain_file:
        return 'magenta'        # extended (GS/OS) file
    return ''


def listing(volume: Volume, paths: list[str], recursive: bool = False) -> list[Text]:
    """Lines listing the entries matching paths, showing the contents of directories"""
    entries = volume.find_entries(paths)
    lines = [Text(FileEntry.heading), Text('-' * len(FileEntry.heading))]
    while entries:
        e = entries.pop(0)
        if e.is_dir:
            d = volume.read_directory(e)
            lines += [Text(repr(x), style=entry_style(x)) for x in d.entries]
            lines.append(Text(repr(d.header), style='dim'))
            if recursive:
                entries += [x for x in d.entries if x.is_dir]
        else:
            lines.append(Text(repr(e), style=entry_style(e)))
        lines.append(Text())
    return lines

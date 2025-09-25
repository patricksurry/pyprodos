from typing import Optional, cast
from dataclasses import dataclass, field
import logging
from fnmatch import fnmatch

from .globals import entries_per_block
from .metadata import FileEntry, DirectoryHeaderEntry, VolumeDirectoryHeaderEntry
from .blocks import DirectoryBlock
from .device import BlockDevice
from .file import SimpleFile
from .p8datetime import P8DateTime


@dataclass(kw_only=True)
class Directory:
    r"""
    Figure B-2. Directory File Format

               Key Block    Any Block         Last Block
             / +-------+    +-------+         +-------+
            |  |   0   |<---|Pointer|<--...<--|Pointer|     Blocks of a directory:
            |  |-------|    |-------|         |-------|     Not necessarily contiguous,
            |  |Pointer|--->|Pointer|-->...-->|   0   |     linked by pointers.
            |  |-------|    |-------|         |-------|
            |  |Header |    | Entry |   ...   | Entry |
            |  |-------|    |-------|         |-------|     Header describes the
            |  | Entry |    | Entry |   ...   | Entry |     directory file and its
            |  |-------|    |-------|         |-------|     contents.
      One  /   / More  /    / More  /         / More  /
     Block \   /Entries/    /Entries/         /Entries/
            |  |-------|    |-------|         |-------|     Entry describes
            |  | Entry |    | Entry |   ...   | Entry |     and points to a file
            |  |-------|    |-------|         |-------|     (subdirectory or
            |  | Entry |    | Entry |   ...   | Entry |     standard) in that
            |  |-------|    |-------|         |-------|     directory.
            |  |Unused |    |Unused |   ...   |Unused |
             \ +-------+    +-------+         +-------+
    """
    device: BlockDevice
    header: DirectoryHeaderEntry
    entries: list[FileEntry]
    block_list: list[int] = field(default_factory=list[int])

    def __repr__(self):
        s = '\n'.join([repr(e) for e in self.entries if e.is_active])
        return s + '\n' + repr(self.header)

    def __post_init__(self):
        active_count = len([e for e in self.entries if e.is_active])
        if self.header.file_count != active_count:
            logging.warning(f"Directory file_count {self.header.file_count} != {active_count} active entries")

    def file_glob(self, pattern: str) -> list[FileEntry]:
        return [
            e for e in self.entries if e.is_active and fnmatch(e.file_name, pattern)
        ]

    def path_glob(self, patterns: list[str]) -> list[FileEntry]:
        pattern = patterns.pop(0)

        entries = self.file_glob(pattern)

        if not patterns:
            return entries

        return sum(
            (
                Directory.read(self.device, e.key_pointer).path_glob(patterns)
                for e in entries
                if e.is_dir
            ),
            cast(list[FileEntry], [])
        )

    def add_entry(self, entry: FileEntry):
        i = next((i for i, e in enumerate(self.entries) if not e.is_active), None)
        if i is None:
            i = len(self.entries)
            self.entries += [FileEntry.empty] * entries_per_block
        self.entries[i] = entry
        self.header.file_count += 1
        self.header.date_time = P8DateTime.now()
        self.write()

    def remove_entry(self, entry: FileEntry):
        i = next((i for i, e in enumerate(self.entries) if e == entry), None)
        assert i is not None, f"Directory.remove_entry {entry} not found in {self}"
        self.entries[i] = FileEntry.empty
        self.header.file_count -= 1
        self.header.date_time = P8DateTime.now()
        self.write()

    def remove_simple_file(self, entry: FileEntry):
        self.remove_entry(entry)
        f = SimpleFile.from_entry(self.device, entry)
        f.remove()

    def write_simple_file(self, f: SimpleFile):
        entries = self.file_glob(f.file_name)
        assert len(entries) < 2, f"Directory.write_simple_file {f.file_name} matched multiple entries!"
        if entries:
            self.remove_simple_file(entries[0])
        f.write()
        self.add_entry(f.create_entry(self.block_list[0]))

    def write(self):
        assert (len(self.entries) + 1) % entries_per_block == 0, \
            f"Directory: header plus {len(self.entries)} entries isn't a multiple of {entries_per_block}"

        # shrink if not root
        if not isinstance(self.header, VolumeDirectoryHeaderEntry):
            while all(e == FileEntry.empty for e in self.entries[-entries_per_block:]):
                self.entries = self.entries[:entries_per_block]

        n = (len(self.entries) + 1) // entries_per_block
        while len(self.block_list) > n:
            self.device.free_block(self.block_list.pop())
        while len(self.block_list) < n:
            self.block_list.append(self.device.allocate_block())

        offset = entries_per_block-1
        key = DirectoryBlock(
            prev_pointer=0, next_pointer=self.block_list[1],
            header_entry=self.header,
            file_entries=self.entries[:offset]
        )
        self.device.write_block(self.block_list[0], key.pack())
        for i in range(1, n):
            blk = DirectoryBlock(
                prev_pointer=self.block_list[i-1],
                next_pointer=self.block_list[i+1] if i+1 < n else 0,
                file_entries=self.entries[offset:offset + entries_per_block]
            )
            offset += entries_per_block
            self.device.write_block(self.block_list[i], blk.pack())
        assert offset == len(self.entries), f"Directory.write: unexpected offset {offset} != {len(self.entries)}"

    @classmethod
    def read(cls, device: BlockDevice, block_index: int):
        entries: list[FileEntry] = []
        prev = 0
        mark = device.mark_session()
        header: Optional[DirectoryHeaderEntry] = None
        while True:
            data = device.read_block(block_index)
            db = DirectoryBlock.unpack(data)
            if prev == 0:
                assert db.header_entry, "Directory.read: Expected DirectoryHeaderEntry in key block"
                header = db.header_entry
            else:
                assert not db.header_entry, "Directory.read: Unexpected DirectoryHeaderEntry after key block"

            if db.prev_pointer != prev:
                logging.warning(f"Directory.read: block {block_index} has prev_pointer {db.prev_pointer} != {prev}")
            entries += db.file_entries
            if not db.next_pointer:
                break
            prev = block_index
            block_index = db.next_pointer

        assert header, "Directory.read: no header entry"
        return cls(
            device=device,
            header=header,
            entries=entries,
            block_list=device.get_access_log('r', mark)
        )



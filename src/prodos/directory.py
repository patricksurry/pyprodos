from typing import Optional, cast
from dataclasses import dataclass, field
import logging
from fnmatch import fnmatch

from .globals import entries_per_block, block_size
from .metadata import FileEntry, DirectoryEntry, VolumeDirectoryHeaderEntry, \
    StorageType, SubdirectoryHeaderEntry
from .blocks import DirectoryBlock
from .device import BlockDevice
from .file import PlainFile, FileBase


@dataclass(kw_only=True)
class DirectoryFile(FileBase):
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
    header: DirectoryEntry
    entries: list[FileEntry] = field(default_factory=list[FileEntry])

    def __repr__(self):
        s = '\n'.join([repr(e) for e in self.entries if e.is_active])
        return s + '\n' + repr(self.header)

    def __post_init__(self):
        active_count = len([e for e in self.entries if e.is_active])
        if self.header.file_count != active_count:
            logging.warning(f"Directory file_count {self.header.file_count} != {active_count} active entries")
        self.pad_entries()

    @property
    def file_size(self) -> int:
        return len(self.block_list) * block_size

    @property
    def storage_type(self) -> StorageType:
        return StorageType.dir

    @property
    def is_empty(self):
        return not any(e.is_active for e in self.entries)

    def pad_entries(self):
        # pad to multiple of entries_per_block, with header
        pad = -(len(self.entries)+1) % entries_per_block
        self.entries += [FileEntry.empty] * pad
        assert (len(self.entries) + 1) % entries_per_block == 0

    def file_entry(self, name: str) -> FileEntry | None:
        entries = self.glob_file(name)
        if len(entries) > 1:
            raise ValueError("file_entry: globbing not supported")
        return entries[0] if entries else None

    def glob_file(self, pattern: str) -> list[FileEntry]:
        return [
            e for e in self.entries if e.is_active and fnmatch(e.file_name, pattern.upper())
        ]

    def glob_path(self, parts: list[str]) -> list[FileEntry]:
        pattern = parts.pop(0)

        entries = self.glob_file(pattern)

        if not parts:
            return entries

        return sum(
            (
                DirectoryFile.read(self.device, e.key_pointer).glob_path(parts)
                for e in entries
                if e.is_dir
            ),
            cast(list[FileEntry], [])
        )

    def free_entry(self) -> int:
        i = next((i for i, e in enumerate(self.entries) if not e.is_active), None)
        if i is None:
            i = len(self.entries)
            self.entries += [FileEntry.empty] * entries_per_block
        return i

    def write_entry(self, i: int, entry: FileEntry):
        self.entries[i] = entry
        self.write()

    def add_entry(self, entry: FileEntry):
        self.write_entry(self.free_entry(), entry)

    def remove_entry(self, entry: FileEntry):
        #TODO test for directory
        i = next((i for i, e in enumerate(self.entries) if e == entry), None)
        assert i is not None, f"Directory.remove_entry {entry} not found in {self}"
        self.entries[i] = FileEntry.empty
        self.write()

    def remove_simple_file(self, entry: FileEntry):
        assert entry.is_plain_file, f"Directory.remove_simple_file: not simple file {entry}"
        self.remove_entry(entry)
        f = PlainFile.from_entry(self.device, entry)
        f.remove()

    def add_simple_file(self, f: PlainFile):
        entries = self.glob_file(f.file_name)
        assert len(entries) < 2, f"Directory.add_simple_file {f.file_name} matched multiple entries!"
        if entries:
            self.remove_simple_file(entries[0])
        f.write()
        self.add_entry(f.entry(self.block_list[0]))

    def remove_directory(self, entry: FileEntry):
        assert entry.is_dir, f"Directory.remove_directory: not directory {entry}"
        dir = self.read(self.device, entry.key_pointer)
        assert dir.is_empty, f"Directory.remove_directory: directory not empty {entry}"
        self.remove_entry(entry)
        dir.remove()

    def add_directory(self, file_name: str):
        entries = self.glob_file(file_name)
        assert len(entries) == 0, f"Directory.add_directory {file_name} already exists!"

        i = self.free_entry()

        subdir = self.__class__(
            device=self.device,
            header=SubdirectoryHeaderEntry(
                storage_type=StorageType.subdirhdr,
                file_name=file_name,
                parent_pointer=self.block_list[0],
                parent_entry_number=i
            ),
            file_name=file_name,  #TODO
            entries=[]
        )
        subdir.write()

        entry = subdir.entry(self.block_list[0])
        self.write_entry(i, entry)

    def remove(self):
        assert self.is_empty, f"Directory.remove: directory not empty {self}"
        super().remove()

    def write(self, compact: bool=True):
        assert (len(self.entries) + 1) % entries_per_block == 0, \
            f"Directory: header plus {len(self.entries)} entries isn't a multiple of {entries_per_block}"

        # root directory is fixed size
        if compact and not isinstance(self.header, VolumeDirectoryHeaderEntry):
            # keep all non-empty entries in the same order
            self.entries = [ e for e in self.entries if e != FileEntry.empty]
            self.pad_entries()

        n = (len(self.entries) + 1) // entries_per_block
        while len(self.block_list) > n:
            self.device.free_block(self.block_list.pop())
        while len(self.block_list) < n:
            self.block_list.append(self.device.allocate_block())

        self.header.file_count = sum(e.is_active for e in self.entries)
        offset = entries_per_block-1
        key = DirectoryBlock(
            prev_pointer=0, next_pointer=self.block_list[1] if n > 1 else 0,
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
        header: Optional[DirectoryEntry] = None
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
            block_list=device.get_access_log('r', mark),
            file_name=header.file_name,
        )

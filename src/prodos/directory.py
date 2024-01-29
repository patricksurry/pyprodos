from typing import List, Optional, Set
from dataclasses import dataclass
import logging
from fnmatch import fnmatch

from .globals import volume_key_block
from .metadata import FileEntry, DirectoryHeaderEntry
from .blocks import DirectoryBlock, VolumeDirectoryKeyBlock, SubdirectoryKeyBlock
from .device import BlockDevice


@dataclass(kw_only=True)
class Directory:
    header: DirectoryHeaderEntry
    entries: List[FileEntry]
    block_log: Set[int]

    def __repr__(self):
        s = '\n'.join([repr(e) for e in self.entries if e.is_active])
        return s + '\n' + repr(self.header)

    def __post_init__(self):
        active_count = len([e for e in self.entries if e.is_active])
        if self.header.file_count != active_count:
            logging.warn(f"Directory file_count {self.header.file_count} != {active_count} active entries")

    def file_glob(self, pattern: str) -> List[FileEntry]:
        return [
            e for e in self.entries if e.is_active and fnmatch(e.file_name, pattern)
        ]

    def path_glob(self, device: BlockDevice, patterns: List[str]) -> List[FileEntry]:
        pattern = patterns.pop(0)

        entries = self.file_glob(pattern)

        if not patterns:
            return entries

        return sum(
            (
                Directory.read(device, e).path_glob(patterns)
                for e in entries
                if e.is_dir
            ),
            []
        )

    @classmethod
    def read(kls, device: BlockDevice, entry: FileEntry):
        assert entry.is_dir, f"read_directory: not a directory {entry}"
        block_index = entry.key_pointer

        block_log: Set[int] = set()
        entries: List[FileEntry] = []
        prev = 0
        while True:
            if prev:
                typ = DirectoryBlock
            else:
                typ = VolumeDirectoryKeyBlock if not entry else SubdirectoryKeyBlock
            db = device.read_block_type(block_index, typ)

            block_log.add(block_index)
            if not prev:
                if typ is VolumeDirectoryKeyBlock:
                    header = db.volume_header
                else:
                    header = db.subdirectory_header

            if db.prev_pointer != prev:
                logging.warn(f"directory block {block_index} has prev_pointer {db.prev_pointer} expected {prev}")
            entries += db.file_entries
            if not db.next_pointer:
                break
            prev = block_index
            block_index = db.next_pointer

        return kls(header=header, entries=entries, block_log=block_log)



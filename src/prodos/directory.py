from typing import List, Type
from dataclasses import dataclass, field
import logging
from fnmatch import fnmatch

from .globals import entries_per_block
from .metadata import FileEntry, DirectoryHeaderEntry, VolumeDirectoryHeaderEntry, SubdirectoryHeaderEntry
from .blocks import DirectoryBlock
from .device import BlockDevice


@dataclass(kw_only=True)
class Directory:
    header: DirectoryHeaderEntry
    entries: List[FileEntry]
    block_list: List[int] = field(default_factory=list)

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

    def write(self, device: BlockDevice):
        assert (len(self.entries) + 1) % entries_per_block == 0, \
            f"Directory: header plus {len(self.entries)} entries isn't a multiple of {entries_per_block}"
        n = (len(self.entries) + 1) // entries_per_block
        while len(self.block_list) < n:
            self.block_list.append(device.allocate_block())

        offset = entries_per_block-1
        key = DirectoryBlock(
            prev_pointer=0, next_pointer=self.block_list[1],
            header_entry=self.header,
            file_entries=self.entries[:offset]
        )
        device.write_block(self.block_list[0], key.pack())
        for i in range(1, n):
            blk = DirectoryBlock(
                prev_pointer=self.block_list[i-1],
                next_pointer=self.block_list[i+1] if i+1 < n else 0,
                file_entries=self.entries[offset:offset + entries_per_block]
            )
            offset += entries_per_block
            device.write_block(self.block_list[i], blk.pack())
        assert offset == len(self.entries)

    @classmethod
    def read(kls, device: BlockDevice, entry: FileEntry):
        assert entry.is_dir, f"read_directory: not a directory {entry}"
        block_index = entry.key_pointer

        entries: List[FileEntry] = []
        prev = 0
        mark = device.mark_session()
        while True:
            data = device.read_block(block_index)
            if prev:
                db = DirectoryBlock.unpack(data)
            else:
                ht: Type[DirectoryHeaderEntry]
                if entry.is_volume_dir:
                    ht = VolumeDirectoryHeaderEntry
                else:
                    ht = SubdirectoryHeaderEntry
                db = DirectoryBlock.unpack_key_block(data, ht)
                assert db.header_entry
                header = db.header_entry

            if db.prev_pointer != prev:
                logging.warn(f"directory block {block_index} has prev_pointer {db.prev_pointer} expected {prev}")
            entries += db.file_entries
            if not db.next_pointer:
                break
            prev = block_index
            block_index = db.next_pointer

        return kls(header=header, entries=entries, block_list=device.get_access_log('r', mark))



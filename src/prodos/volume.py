from typing import Self
from pathlib import Path
import logging

from .globals import volume_key_block, volume_directory_length, \
    block_size, entries_per_block
from .device import BlockDevice, DeviceFormat, DeviceMode
from .metadata import P8DateTime, FileEntry, VolumeDirectoryHeaderEntry, \
    access_byte, StorageType
from .blocks import DirectoryBlock
from .directory import DirectoryFile
from .file import PlainFile


class Volume:
    """
    Figure B-1. Blocks on a Volume

    +-----------------------------------   ----------------------------------   -------------------
    |         |         |   Block 2   |     |   Block n    |  Block n + 1  |     |    Block p    |
    | Block 0 | Block 1 |   Volume    | ... |    Volume    |    Volume     | ... |    Volume     | Other
    | Loader  | Loader  |  Directory  |     |  Directory   |    Bit Map    |     |    Bit Map    | Files
    |         |         | (Key Block) |     | (Last Block) | (First Block) |     | (Last Block)  |
    +-----------------------------------   ----------------------------------   -------------------
    """

    def __init__(self, device: BlockDevice):
        self.device = device
        vkb = self.device.read_block_type(volume_key_block, DirectoryBlock, unsafe=True)
        assert isinstance(vkb.header_entry, VolumeDirectoryHeaderEntry), \
            f"Volume header entry has unexpected type {type(vkb.header_entry)}"
        vh = vkb.header_entry
        assert vh.total_blocks == device.total_blocks, \
            f"Volume directory header block count {vh.total_blocks} != device block count {device.total_blocks}"
        self.device.reset_free_map(vh.bit_map_pointer)

    @classmethod
    def from_file(cls, source: Path, mode: DeviceMode='ro') -> Self:
        return cls(BlockDevice(source, mode))

    @classmethod
    def create(cls,
            dest: Path,
            volume_name: str = 'PYP8',
            total_blocks: int = 65535,
            format: DeviceFormat = DeviceFormat.prodos,
            loader_path: Path | None = None
        ) -> Self:
        device = BlockDevice.create(dest, total_blocks, bit_map_pointer=6, format=format)
        # reserve two blocks for loader
        device.allocate_block()
        device.allocate_block()
        DirectoryFile(
            device=device,
            header=VolumeDirectoryHeaderEntry(
                storage_type = StorageType.voldirhdr,
                file_name = volume_name.upper(),
                created = P8DateTime.now(),
                version = 0,
                min_version = 0,
                access = access_byte(),
                file_count = 0,
                bit_map_pointer = 6,
                total_blocks = total_blocks,
            ),
            file_name = volume_name.upper(), #TODO
            entries=[FileEntry.empty] * (4 * entries_per_block - 1),
            block_list=list(range(volume_key_block, volume_key_block + volume_directory_length))
        ).write()
        device.write_free_map()
        volume = cls(device)
        if loader_path is not None:
            volume.write_loader(loader_path)
        return volume

    def __repr__(self):
        h = self.root.header
        return f"Volume {h.file_name} {h.created}\n" + repr(self.device)

    @property
    def root(self) -> DirectoryFile:
        return self.read_directory(FileEntry.root)

    def parent_directory(self, entry: FileEntry) -> DirectoryFile:
        assert entry.header_pointer >= 2, f"parent_directory: bad header_pointer {entry.header_pointer}"
        return DirectoryFile.read(self.device, entry.header_pointer)

    def read_directory(self, dir_entry: FileEntry) -> DirectoryFile:
        assert dir_entry.is_dir, f"read_directory: not a directory {dir_entry}"
        return DirectoryFile.read(self.device, dir_entry.key_pointer)

    def read_simple_file(self, entry: FileEntry) -> PlainFile:
        return PlainFile.from_entry(self.device, entry)

    def write_loader(self, loader_path: Path):
        data = open(loader_path, 'rb').read()
        if len(data) > 2 * block_size:
            logging.warning(f"Volume.write_loader truncating {loader_path} at {2*block_size} bytes")
        elif len(data) < 2 * block_size:
            logging.info(f"Volume.write_loader padding {loader_path} to {2*block_size} bytes")
            data += bytes(2*block_size-len(data))
        self.device.write_block(0, data[:block_size])
        self.device.write_block(1, data[block_size:2*block_size])

    def read_loader(self) -> bytes:
        """Read the boot loader from blocks 0 and 1."""
        block0 = self.device.read_block(0)
        block1 = self.device.read_block(1)
        return block0 + block1

    def path_entry(self, path: str) -> FileEntry|None:
        entries = self.glob_paths([path])
        if len(entries) > 1:
            raise ValueError("path_entry: globbing not supported")
        return entries[0] if entries else None

    def glob_paths(self, paths: list[str]) -> list[FileEntry]:
        entries: list[FileEntry] = []
        uniq = {p.strip('/') for p in paths}
        root = self.root
        for p in uniq:
            if not p:
                entries.append(FileEntry.root)
            else:
                entries += root.glob_path(p.split('/'))
        return entries


from typing import List, Self

from .globals import volume_key_block, volume_directory_length, block_size
from .blocks import VolumeDirectoryKeyBlock
from .device import BlockDevice
from .metadata import FileEntry
from .directory import Directory
from .file import SimpleFile


class Volume:
    def __init__(self, device: BlockDevice):
        self.device = device
        vkb = self.device.read_block_type(volume_key_block, VolumeDirectoryKeyBlock)
        vh = vkb.volume_header
        self.volume_name = vh.file_name
        assert vh.total_blocks == device.total_blocks, \
            "Volume directory header block count {vh.total_blocks} != device block count {device.total_blocks}"
        self.device.init_free_map(vh.bit_map_pointer)

        self.root_entry = FileEntry(
            storage_type = 0xf,
            file_name = '/',
            file_type = 0xff,
            key_pointer = volume_key_block,
            blocks_used = volume_directory_length,
            eof = volume_directory_length * block_size,
            #TODO
            date_time = bytes([0,0,0,0]),
            version = 1,
            min_version = 1,
            access = 0,
            aux_type = 0,
            last_mod = bytes([0,0,0,0]),
            header_pointer = 0,
        )

    @classmethod
    def from_file(kls, file_name: str) -> Self:
        return Volume(BlockDevice(file_name))

    def __repr__(self):
        return f"Volume {self.volume_name}\n" + repr(self.device)

    def read_directory(self, entry: FileEntry) -> Directory:
        return Directory.read(self.device, entry)

    def read_simple_file(self, entry: FileEntry) -> SimpleFile:
        return SimpleFile.read(self.device, entry)

    def glob_paths(self, paths: List[str]) -> List[FileEntry]:
        entries = []
        paths = {p.strip('/') for p in paths}
        root_dir = Directory.read(self.device, self.root_entry)
        for p in paths:
            if not p:
                entries.append(self.root_entry)
            else:
                entries += root_dir.path_glob(self.device, p.split('/'))
        return entries


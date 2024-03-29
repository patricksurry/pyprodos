from typing import Literal, List, Self
import logging

from .globals import volume_key_block, volume_directory_length, \
    block_size, entries_per_block
from .device import BlockDevice, DeviceFormat
from .metadata import P8DateTime, FileEntry, VolumeDirectoryHeaderEntry, \
    access_byte, storage_type_voldir
from .blocks import DirectoryBlock
from .directory import Directory
from .file import SimpleFile


class Volume:
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
    def from_file(kls, file_name: str, mode: Literal['ro', 'rw']='ro') -> Self:
        return kls(BlockDevice(file_name, mode))

    @classmethod
    def create(kls,
            file_name: str,
            volume_name: str = 'PYP8',
            total_blocks = 65535,
            format: DeviceFormat = DeviceFormat.prodos,
            loader_file_name = ''
        ) -> Self:
        device = BlockDevice.create(file_name, total_blocks, bit_map_pointer=6, format=format)
        # reserve two blocks for loader
        device.allocate_block()
        device.allocate_block()
        Directory(
            device=device,
            header=VolumeDirectoryHeaderEntry(
                storage_type = storage_type_voldir,
                file_name = volume_name.upper(),
                date_time = P8DateTime.now(),
                version = 0,
                min_version = 0,
                access = access_byte(),
                file_count = 0,
                bit_map_pointer = 6,
                total_blocks = total_blocks,
            ),
            entries=[FileEntry.empty] * (4 * entries_per_block - 1),
            block_list=list(range(volume_key_block, volume_key_block + volume_directory_length))
        ).write()
        device.write_free_map()
        volume = kls(device)
        if loader_file_name:
            volume.write_loader(loader_file_name)
        return volume

    def __repr__(self):
        h = self.root.header
        return f"Volume {h.file_name} {h.date_time}\n" + repr(self.device)

    @property
    def root(self) -> Directory:
        return self.read_directory(FileEntry.root)

    def parent_directory(self, entry: FileEntry) -> Directory:
        assert entry.header_pointer >= 2, f"parent_directory: bad header_pointer {entry.header_pointer}"
        return Directory.read(self.device, entry.header_pointer)

    def read_directory(self, dir_entry: FileEntry) -> Directory:
        assert dir_entry.is_dir, f"read_directory: not a directory {dir_entry}"
        return Directory.read(self.device, dir_entry.key_pointer)

    def read_simple_file(self, entry: FileEntry) -> SimpleFile:
        return SimpleFile.from_entry(self.device, entry)

    def write_loader(self, loader_file_name: str):
        data = open(loader_file_name, 'rb').read()
        if len(data) > 2 * block_size:
            logging.warn(f"Volume.write_loader truncating {loader_file_name} at {2*block_size} bytes")
        self.device.write_block(0, data[:block_size])
        self.device.write_block(1, data[block_size:2*block_size])

    def glob_paths(self, paths: List[str]) -> List[FileEntry]:
        entries = []
        uniq = {p.strip('/') for p in paths}
        root = self.root
        for p in uniq:
            if not p:
                entries.append(FileEntry.root)
            else:
                entries += root.path_glob(p.split('/'))
        return entries


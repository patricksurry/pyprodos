from typing import Literal, List, Self
import logging

from .globals import volume_key_block, volume_directory_length, \
    block_size, entries_per_block, access_flags
from .device import BlockDevice, DeviceFormat
from .metadata import P8DateTime, FileEntry, VolumeDirectoryHeaderEntry, \
    storage_type_voldir
from .blocks import DirectoryBlock
from .directory import Directory
from .file import SimpleFile


class Volume:
    def __init__(self, device: BlockDevice):
        self.device = device
        data = self.device.read_block(volume_key_block)
        vkb = DirectoryBlock.unpack_key_block(data, VolumeDirectoryHeaderEntry)
        assert isinstance(vkb.header_entry, VolumeDirectoryHeaderEntry)
        vh = vkb.header_entry
        self.volume_name = vh.file_name
        assert vh.total_blocks == device.total_blocks, \
            f"Volume directory header block count {vh.total_blocks} != device block count {device.total_blocks}"
        self.device.reset_free_map(vh.bit_map_pointer)
        self.root_entry = FileEntry(
            storage_type = storage_type_voldir,
            file_name = '/',
            file_type = 0xff,
            key_pointer = volume_key_block,
            blocks_used = volume_directory_length,
            eof = volume_directory_length * block_size,
            date_time = vh.date_time,
            version = 1,
            min_version = 1,
            access = 0,
            aux_type = 0,
            last_mod = vh.date_time,
            header_pointer = 0,
        )

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
            header=VolumeDirectoryHeaderEntry(
                storage_type = storage_type_voldir,
                file_name = volume_name.upper(),
                reserved = bytes([0x75, 0x23, 0x00, 0xc3, 0x27, 0x0d, 0x00]),
                date_time = P8DateTime.now(),
                version = 0,
                min_version = 0,
                access = sum(access_flags[c] for c in 'RWBN'),
                file_count = 0,
                bit_map_pointer = 6,
                total_blocks = total_blocks,
            ),
            entries=[FileEntry.empty] * (4 * entries_per_block - 1),
            block_list=[2,3,4,5]
        ).write(device)
        device.write_free_map()
        volume = kls(device)
        if loader_file_name:
            volume.write_loader(loader_file_name)
        return volume

    def __repr__(self):
        return f"Volume {self.volume_name} {self.root_entry.date_time}\n" + repr(self.device)

    def read_directory(self, entry: FileEntry) -> Directory:
        return Directory.read(self.device, entry)

    def read_simple_file(self, entry: FileEntry) -> SimpleFile:
        return SimpleFile.read(self.device, entry)

    def write_loader(self, loader_file_name: str):
        data = open(loader_file_name, 'rb').read()
        if len(data) > 2 * block_size:
            logging.warn(f"Volume.write_loader truncating {loader_file_name} at {2*block_size} bytes")
        self.device.write_block(0, data[:block_size])
        self.device.write_block(1, data[block_size:2*block_size])

    def glob_paths(self, paths: List[str]) -> List[FileEntry]:
        entries = []
        uniq = {p.strip('/') for p in paths}
        root_dir = Directory.read(self.device, self.root_entry)
        for p in uniq:
            if not p:
                entries.append(self.root_entry)
            else:
                entries += root_dir.path_glob(self.device, p.split('/'))
        return entries


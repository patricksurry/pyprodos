"""A ProDOS volume: boot loader, volume directory, bit map and files."""
import logging
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Self

from .bitmap import Bitmap
from .blocks import DirectoryBlock
from .device import BlockDevice, DeviceFormat, DeviceMode
from .directory import Directory
from .errors import ProDOSError
from .file import File
from .globals import block_size, entries_per_block, max_volume_blocks, volume_directory_length, volume_key_block
from .metadata import FileEntry, StorageType, VolumeDirectoryHeader, access_byte, is_legal_name
from .p8datetime import P8DateTime

loader_blocks = [0, 1]


class Volume:
    """
    Figure B-1. Blocks on a Volume

    +-----------------------------------   ----------------------------------   -------------------
    |         |         |   Block 2   |     |   Block n    |  Block n + 1  |     |    Block p    |
    | Block 0 | Block 1 |   Volume    | ... |    Volume    |    Volume     | ... |    Volume     | Other
    | Loader  | Loader  |  Directory  |     |  Directory   |    Bit Map    |     |    Bit Map    | Files
    |         |         | (Key Block) |     | (Last Block) | (First Block) |     | (Last Block)  |
    +-----------------------------------   ----------------------------------   -------------------

    Use as a context manager, or call close(), to write the bit map back to disk.
    """

    def __init__(self, device: BlockDevice, bitmap: Bitmap):
        self.device = device
        self.bitmap = bitmap

    @classmethod
    def open(cls, source: Path, mode: DeviceMode = 'ro') -> Self:
        device = BlockDevice(source, mode)
        try:
            key = device.read_typed_block(volume_key_block, DirectoryBlock)
            h = key.header_entry
            if not isinstance(h, VolumeDirectoryHeader):
                raise ProDOSError(f"{source} has no ProDOS volume directory at block {volume_key_block}")
            if h.total_blocks > device.total_blocks:
                raise ProDOSError(f"Volume claims {h.total_blocks} blocks but the image has {device.total_blocks}")
            if h.total_blocks < device.total_blocks:
                logging.warning(f"Volume uses {h.total_blocks} of {device.total_blocks} blocks in the image")
            bitmap = Bitmap.read(device, h.bitmap_pointer, h.total_blocks)
        except Exception:
            device.close()
            raise
        return cls(device, bitmap)

    @classmethod
    def create(cls,
            dest: Path,
            volume_name: str = 'PYP8',
            total_blocks: int = max_volume_blocks,
            format: DeviceFormat = DeviceFormat.prodos,
        ) -> Self:
        volume_name = volume_name.upper()
        if not is_legal_name(volume_name):
            raise ProDOSError(f"Illegal volume name {volume_name!r}")
        # the bit map follows the volume directory
        bitmap_pointer = volume_key_block + volume_directory_length
        first_free = bitmap_pointer + Bitmap.blocks_needed(total_blocks)
        if not first_free < total_blocks <= max_volume_blocks:
            raise ProDOSError(f"Volume size must be between {first_free + 1} and {max_volume_blocks} blocks")

        device = BlockDevice.create(dest, total_blocks, format=format)
        bitmap = Bitmap.create(device, bitmap_pointer, total_blocks)
        # the loader, volume directory and bit map are always in use
        for block_index in range(first_free):
            bitmap.mark_used(block_index)
        Directory(
            device=device,
            bitmap=bitmap,
            header=VolumeDirectoryHeader(
                storage_type=StorageType.voldirhdr,
                file_name=volume_name,
                reserved=bytes(8),
                created=P8DateTime.now(),
                access=access_byte('RWND'),
                bitmap_pointer=bitmap_pointer,
                total_blocks=total_blocks,
            ),
            slots=[FileEntry.empty] * (volume_directory_length * entries_per_block - 1),
            blocks=list(range(volume_key_block, bitmap_pointer)),
        ).write()
        bitmap.flush()
        return cls(device, bitmap)

    def flush(self):
        if self.device.mode == 'rw':
            self.bitmap.flush()

    def close(self):
        self.flush()
        self.device.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None):
        self.close()

    def __repr__(self):
        h = self.header
        used = 1 - self.bitmap.free_count / h.total_blocks
        return (
            f"Volume {h.file_name} {h.created}\n"
            f"{self.device!r}, {self.bitmap.free_count} free ({used:.0%} used)"
        )

    @property
    def header(self) -> VolumeDirectoryHeader:
        h = self.root.header
        assert isinstance(h, VolumeDirectoryHeader)
        return h

    @property
    def root(self) -> Directory:
        return Directory.read(self.device, self.bitmap, volume_key_block)

    def read_directory(self, entry: FileEntry) -> Directory:
        if not entry.is_dir:
            raise ProDOSError(f"{entry.file_name} is not a directory")
        return Directory.read(self.device, self.bitmap, entry.key_pointer)

    def read_file(self, entry: FileEntry) -> File:
        return File.read(self.device, entry)

    def directory_of(self, entry: FileEntry) -> Directory:
        """The directory containing entry"""
        if entry.is_volume_dir:
            raise ProDOSError("The volume directory has no parent")
        return Directory.read(self.device, self.bitmap, entry.header_pointer)

    def walk(self) -> Iterator[tuple[str, Directory]]:
        """Yield (path, directory) for every directory, starting with the root"""
        pending = [('/', self.root)]
        seen: set[int] = set()
        while pending:
            path, d = pending.pop(0)
            if d.key_block in seen:
                logging.warning(f"walk: {path} revisits directory at block {d.key_block}")
                continue
            seen.add(d.key_block)
            yield path, d
            for e in d.entries:
                if e.is_dir:
                    try:
                        pending.append((f"{path}{e.file_name}/", self.read_directory(e)))
                    except ProDOSError as ex:
                        logging.warning(f"walk: can't read {path}{e.file_name}/: {ex}")

    def path_entry(self, path: str) -> FileEntry | None:
        entries = self.glob_paths([path])
        if len(entries) > 1:
            raise ProDOSError(f"{path} matches more than one entry")
        return entries[0] if entries else None

    def glob_paths(self, paths: list[str]) -> list[FileEntry]:
        """Entries matching paths like /SYSTEM/*.SYSTEM, in order; / is the volume directory"""
        entries: list[FileEntry] = []
        root = self.root
        for p in dict.fromkeys(p.strip('/') for p in paths):
            entries += root.glob_path(p.split('/')) if p else [FileEntry.root]
        return entries

    def read_loader(self) -> bytes:
        """The boot loader in blocks 0 and 1"""
        return b''.join(self.device.read_block(i) for i in loader_blocks)

    def write_loader(self, data: bytes):
        size = len(loader_blocks) * block_size
        if len(data) > size:
            logging.warning(f"Volume.write_loader: truncating loader at {size} bytes")
        data = data[:size].ljust(size, b'\0')
        for k, i in enumerate(loader_blocks):
            self.device.write_block(i, data[k * block_size:(k + 1) * block_size])

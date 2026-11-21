"""Directories: chains of blocks holding a header and an array of entry slots."""
from dataclasses import dataclass, replace
from fnmatch import fnmatch
from typing import Self

from .bitmap import Bitmap
from .blocks import DirectoryBlock
from .device import BlockDevice
from .errors import ProDOSError
from .file import File
from .globals import block_size, entries_per_block, volume_key_block
from .metadata import (
    DirectoryHeader,
    FileEntry,
    FileType,
    StorageType,
    SubdirectoryHeader,
    VolumeDirectoryHeader,
    is_legal_name,
)
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

    A directory is a fixed array of slots: 12 in the key block after the header,
    then 13 in each following block.  Like ProDOS, we reuse empty slots, grow a
    subdirectory by one block when it's full, and never move or compact entries,
    since subdirectory headers refer back to their entry by position.
    The volume directory is fixed at four blocks (51 entries).

    A Directory is a snapshot of what's on disk.  Operations write through
    immediately, but may also update other directories on disk (e.g. a growing
    subdirectory updates its entry in the parent), so re-read a directory
    rather than holding it across operations on other directories.
    """
    device: BlockDevice
    bitmap: Bitmap
    header: DirectoryHeader
    slots: list[FileEntry]      # every entry slot in order, including empty ones
    blocks: list[int]           # the chain of directory blocks, starting with the key block

    def __repr__(self):
        s = '\n'.join(repr(e) for e in self.entries)
        return s + '\n' + repr(self.header)

    @property
    def key_block(self) -> int:
        return self.blocks[0]

    @property
    def name(self) -> str:
        return self.header.file_name

    @property
    def is_volume_directory(self) -> bool:
        return isinstance(self.header, VolumeDirectoryHeader)

    @property
    def entries(self) -> list[FileEntry]:
        return [e for e in self.slots if e.is_active]

    @property
    def is_empty(self) -> bool:
        return not self.entries

    def slot_location(self, i: int) -> tuple[int, int]:
        """The (block, entry number) of slot i, as used by parent_pointer and parent_entry_number"""
        n = i + 1   # position counting the header
        return self.blocks[n // entries_per_block], n % entries_per_block + 1

    def find(self, name: str) -> FileEntry | None:
        name = name.upper()
        return next((e for e in self.entries if e.file_name == name), None)

    def glob(self, pattern: str) -> list[FileEntry]:
        return [e for e in self.entries if fnmatch(e.file_name, pattern.upper())]

    def glob_path(self, parts: list[str]) -> list[FileEntry]:
        """Match a path of glob patterns like ['SYS*', '*.TXT'] below this directory"""
        pattern, rest = parts[0], parts[1:]
        entries = self.glob(pattern)
        if not rest:
            return entries
        return [
            match
            for e in entries if e.is_dir
            for match in self.read(self.device, self.bitmap, e.key_pointer).glob_path(rest)
        ]

    # --- reading and writing

    @classmethod
    def read(cls, device: BlockDevice, bitmap: Bitmap, key_block: int) -> Self:
        blocks: list[int] = []
        slots: list[FileEntry] = []
        header: DirectoryHeader | None = None
        block_index = key_block
        while block_index:
            if block_index in blocks:
                raise ProDOSError(f"Directory at block {key_block} has a loop in its block chain")
            db = device.read_typed_block(block_index, DirectoryBlock)
            if not blocks:
                if not db.header_entry:
                    raise ProDOSError(f"Block {key_block} is not a directory key block")
                header = db.header_entry
            elif db.header_entry:
                raise ProDOSError(f"Directory block {block_index} has an unexpected header")
            blocks.append(block_index)
            slots += db.file_entries
            block_index = db.next_pointer
        assert header
        return cls(device=device, bitmap=bitmap, header=header, slots=slots, blocks=blocks)

    def write(self):
        n = len(self.blocks)
        assert len(self.slots) == n * entries_per_block - 1, \
            f"Directory.write: {len(self.slots)} slots don't fit {n} blocks"
        self.header = replace(self.header, file_count=len(self.entries))
        for k, block_index in enumerate(self.blocks):
            start = max(0, k * entries_per_block - 1)
            stop = (k + 1) * entries_per_block - 1
            self.device.write_typed_block(block_index, DirectoryBlock(
                prev_pointer=self.blocks[k - 1] if k else 0,
                next_pointer=self.blocks[k + 1] if k + 1 < n else 0,
                header_entry=self.header if k == 0 else None,
                file_entries=self.slots[start:stop],
            ))

    def parent_key_block(self) -> int:
        """Key block of the parent directory, found via our entry in it"""
        return self._parent_entry()[1].header_pointer

    def _parent_entry(self) -> tuple[DirectoryBlock, FileEntry, int]:
        h = self.header
        if not isinstance(h, SubdirectoryHeader):
            raise ProDOSError("The volume directory has no parent")
        block = self.device.read_typed_block(h.parent_pointer, DirectoryBlock)
        i = block.entry_index(h.parent_entry_number)
        if not 0 <= i < len(block.file_entries) or block.file_entries[i].key_pointer != self.key_block:
            raise ProDOSError(f"Directory {self.name} has a bad parent pointer")
        return block, block.file_entries[i], i

    def _update_parent_entry(self):
        """After growing, record our new size in the parent's entry for us"""
        block, entry, i = self._parent_entry()
        block.file_entries[i] = replace(
            entry, blocks_used=len(self.blocks), eof=len(self.blocks) * block_size)
        h = self.header
        assert isinstance(h, SubdirectoryHeader)
        self.device.write_typed_block(h.parent_pointer, block)

    def _free_slot(self) -> int:
        """Index of the first empty slot, growing the directory if it's full"""
        i = next((i for i, e in enumerate(self.slots) if not e.is_active), None)
        if i is not None:
            return i
        if self.is_volume_directory:
            raise ProDOSError("Volume directory is full")
        self.blocks.append(self.bitmap.allocate())
        self.slots += [FileEntry.empty] * entries_per_block
        self.write()
        self._update_parent_entry()
        return len(self.slots) - entries_per_block

    def _slot_of(self, name: str) -> int:
        i = next((i for i, e in enumerate(self.slots) if e.is_active and e.file_name == name), None)
        if i is None:
            raise ProDOSError(f"{name} not found in {self.name}")
        return i

    def _check_new_name(self, name: str):
        if not is_legal_name(name):
            raise ProDOSError(f"Illegal ProDOS name {name!r}")
        if self.find(name):
            raise ProDOSError(f"{name} already exists in {self.name}")

    # --- operations

    def write_file(self, entry: FileEntry, data: bytes, overwrite: bool = False) -> FileEntry:
        """
        Write data as a standard file using entry's metadata (name, file_type, aux_type...).
        The storage fields are filled in from the written data.
        """
        existing = self.find(entry.file_name)
        if existing and overwrite and not existing.is_dir:
            self.delete(existing)
        self._check_new_name(entry.file_name)
        i = self._free_slot()
        f = File.write(self.device, self.bitmap, entry, data)
        self.slots[i] = replace(f.entry, header_pointer=self.key_block)
        self.write()
        return self.slots[i]

    def make_directory(self, name: str) -> FileEntry:
        self._check_new_name(name)
        i = self._free_slot()
        parent_pointer, parent_entry_number = self.slot_location(i)
        now = P8DateTime.now()
        subdir = Directory(
            device=self.device,
            bitmap=self.bitmap,
            header=SubdirectoryHeader(
                storage_type=StorageType.subdirhdr,
                file_name=name,
                created=now,
                parent_pointer=parent_pointer,
                parent_entry_number=parent_entry_number,
            ),
            slots=[FileEntry.empty] * (entries_per_block - 1),
            blocks=[self.bitmap.allocate()],
        )
        subdir.write()
        self.slots[i] = FileEntry(
            storage_type=StorageType.dir,
            file_name=name,
            file_type=FileType.DIR,
            key_pointer=subdir.key_block,
            blocks_used=1,
            eof=block_size,
            created=now,
            last_mod=now,
            header_pointer=self.key_block,
        )
        self.write()
        return self.slots[i]

    def set_info(self, entry: FileEntry, *,
            file_type: int | None = None, aux_type: int | None = None, access: int | None = None) -> FileEntry:
        """Change an entry's file type, aux type or access flags, like the ProDOS SET_FILE_INFO call"""
        i = self._slot_of(entry.file_name)
        entry = self.slots[i]
        if entry.is_dir and file_type not in (None, FileType.DIR):
            raise ProDOSError(f"Can't change the file type of directory {entry.file_name}")
        self.slots[i] = replace(
            entry,
            file_type=entry.file_type if file_type is None else file_type,
            aux_type=entry.aux_type if aux_type is None else aux_type,
            access=entry.access if access is None else access,
        )
        self.write()
        return self.slots[i]

    def delete(self, entry: FileEntry):
        """Delete a file, or an empty directory"""
        i = self._slot_of(entry.file_name)
        entry = self.slots[i]
        if entry.is_dir:
            subdir = self.read(self.device, self.bitmap, entry.key_pointer)
            if not subdir.is_empty:
                raise ProDOSError(f"Directory {entry.file_name} is not empty")
            blocks = subdir.blocks
        else:
            blocks = File.read(self.device, entry).blocks
        # remove the entry before freeing its blocks so it never points at free space
        self.slots[i] = FileEntry.empty
        self.write()
        for block_index in blocks:
            self.bitmap.free(block_index)

    def move(self, entry: FileEntry, dest: "Directory", new_name: str | None = None):
        """Move (and/or rename) a file or directory from this directory to dest"""
        new_name = new_name or entry.file_name
        i = self._slot_of(entry.file_name)
        entry = self.slots[i]
        same_dir = dest.key_block == self.key_block
        if same_dir and new_name == entry.file_name:
            return
        dest._check_new_name(new_name)

        if entry.is_dir and not same_dir:
            # refuse to move a directory inside itself
            key = dest.key_block
            while key != volume_key_block:
                if key == entry.key_pointer:
                    raise ProDOSError(f"Can't move {entry.file_name} inside itself")
                key = self.read(self.device, self.bitmap, key).parent_key_block()

        if same_dir:
            target, j = self, i
        else:
            self.slots[i] = FileEntry.empty
            self.write()
            target, j = dest, dest._free_slot()
        target.slots[j] = replace(entry, file_name=new_name, header_pointer=target.key_block)
        target.write()

        if entry.is_dir:
            # the subdirectory's header names it and points back at its entry
            subdir = self.read(self.device, self.bitmap, entry.key_pointer)
            h = subdir.header
            assert isinstance(h, SubdirectoryHeader)
            parent_pointer, parent_entry_number = target.slot_location(j)
            subdir.header = replace(h, file_name=new_name,
                parent_pointer=parent_pointer, parent_entry_number=parent_entry_number)
            subdir.write()

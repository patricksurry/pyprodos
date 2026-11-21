"""
Volume integrity checks.

Each check states an invariant of a well-formed ProDOS volume, so this module
doubles as a summary of how the on-disk structures fit together.
"""
from .blocks import DirectoryBlock
from .directory import Directory
from .errors import ProDOSError
from .file import capacity
from .globals import block_size
from .metadata import FileType, StorageType, SubdirectoryHeader, is_legal_name
from .volume import Volume, loader_blocks


def check_volume(volume: Volume) -> list[str]:
    """Return a list of problems found, empty if the volume is consistent"""
    problems: list[str] = []
    header = volume.header
    bitmap = volume.bitmap
    owner: dict[int, str] = {}      # which file or structure uses each block

    def claim(blocks: list[int], what: str):
        """Every block belongs to exactly one structure, and is marked used in the bit map"""
        for b in blocks:
            if not 0 <= b < header.total_blocks:
                problems.append(f"{what}: block {b} is outside the volume")
                continue
            if b in owner:
                problems.append(f"{what}: block {b} is also used by {owner[b]}")
            else:
                owner[b] = what
            if bitmap.is_free(b):
                problems.append(f"{what}: block {b} is in use but marked free")

    if header.total_blocks != volume.device.total_blocks:
        problems.append(f"volume header has {header.total_blocks} blocks, image has {volume.device.total_blocks}")

    claim(loader_blocks, 'boot loader')
    claim(bitmap.blocks, 'volume bit map')

    for path, d in volume.walk():
        claim(d.blocks, path)
        problems += check_directory(path, d)

        for e in d.entries:
            name = f"{path}{e.file_name}"
            if not is_legal_name(e.file_name):
                problems.append(f"{name}: illegal name")
            if e.header_pointer != d.key_block:
                problems.append(f"{name}: header_pointer {e.header_pointer} should be {d.key_block}")
            if e.is_dir:
                continue    # checked when walk() reaches it
            try:
                f = volume.read_file(e)
            except ProDOSError as ex:
                problems.append(f"{name}: unreadable: {ex}")
                continue
            claim(f.blocks, name)
            if e.blocks_used != len(f.blocks):
                problems.append(f"{name}: blocks_used {e.blocks_used} but file has {len(f.blocks)} blocks")
            if e.is_plain_file and e.eof > capacity(e.storage_type):
                kind = StorageType(e.storage_type).name
                problems.append(f"{name}: eof {e.eof} exceeds {kind} capacity {capacity(e.storage_type)}")

    for b in range(header.total_blocks):
        if not bitmap.is_free(b) and b not in owner:
            problems.append(f"block {b} is marked used but not part of any file")

    return problems


def check_directory(path: str, d: Directory) -> list[str]:
    problems: list[str] = []

    if d.header.file_count != len(d.entries):
        problems.append(f"{path}: file_count {d.header.file_count} but {len(d.entries)} active entries")

    # blocks are doubly linked: each prev_pointer names the block before it
    for k, block_index in enumerate(d.blocks):
        prev = d.device.read_typed_block(block_index, DirectoryBlock).prev_pointer
        expected = d.blocks[k - 1] if k else 0
        if prev != expected:
            problems.append(f"{path}: block {block_index} prev_pointer {prev} should be {expected}")

    # a subdirectory header points back at the entry in its parent that names it
    h = d.header
    if isinstance(h, SubdirectoryHeader):
        try:
            block = d.device.read_typed_block(h.parent_pointer, DirectoryBlock)
        except ProDOSError as ex:
            return problems + [f"{path}: bad parent_pointer: {ex}"]
        i = block.entry_index(h.parent_entry_number)
        entry = block.file_entries[i] if 0 <= i < len(block.file_entries) else None
        if not entry or entry.key_pointer != d.key_block:
            problems.append(
                f"{path}: parent_pointer {h.parent_pointer} / parent_entry_number "
                f"{h.parent_entry_number} doesn't locate this directory's entry")
        else:
            if entry.file_name != h.file_name:
                problems.append(f"{path}: header name {h.file_name} differs from entry name {entry.file_name}")
            if entry.blocks_used != len(d.blocks) or entry.eof != len(d.blocks) * block_size:
                problems.append(
                    f"{path}: entry says {entry.blocks_used} blocks / eof {entry.eof}, "
                    f"directory has {len(d.blocks)} blocks")
            if entry.file_type != FileType.DIR:
                problems.append(f"{path}: entry file_type {entry.file_type:02x} should be {FileType.DIR:02x}")

    return problems

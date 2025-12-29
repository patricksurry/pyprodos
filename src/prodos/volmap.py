"""Volume block usage mapping and visualization."""
import logging
from dataclasses import dataclass
from enum import Enum, auto
from io import StringIO
from math import ceil
from typing import NamedTuple

from bitarray import bitarray
from rich.console import Console
from rich.text import Text

from .globals import block_size
from .metadata import FileEntry, StorageType, VolumeDirectoryHeaderEntry
from .volume import Volume


class BlockUsage(Enum):
    """Categories of block usage on a ProDOS volume."""
    LOADER = auto()  # Boot loader blocks (0-1)
    VOLDIR = auto()  # Volume directory blocks (2-5)
    BITMAP = auto()  # Volume bitmap blocks
    SUBDIR = auto()  # Subdirectory blocks
    INDEX = auto()   # File index blocks (sapling/tree)
    FILE = auto()    # File data blocks
    FREE = auto()    # Free blocks

    @staticmethod
    def from_block_type(block_type: str, is_voldir: bool = False) -> 'BlockUsage':
        """
        Determine usage type from block type string.

        Args:
            block_type: Block type string from typed access log (may be empty for untyped reads)
            is_voldir: True if processing volume directory blocks (for DirectoryBlock types only)

        Returns:
            Appropriate BlockUsage enum value
        """
        match block_type:
            case 'DirectoryBlock':
                return BlockUsage.VOLDIR if is_voldir else BlockUsage.SUBDIR
            case 'ExtendedKeyBlock' | 'IndexBlock':
                return BlockUsage.INDEX
            case 'LoaderBlock':
                return BlockUsage.LOADER
            case 'BitmapBlock':
                return BlockUsage.BITMAP
            case '':
                return BlockUsage.FILE
            case _:
                raise ValueError(f"BlockUsage: Unknown block type '{block_type}'")


class BlockDisplay(NamedTuple):
    """Configuration for displaying a block type."""
    symbol: str
    type: str


# Central configuration for block usage display properties
BLOCK_CONFIG = {
    BlockUsage.LOADER: BlockDisplay('!', 'loader'),
    BlockUsage.VOLDIR: BlockDisplay('%', 'voldir'),
    BlockUsage.BITMAP: BlockDisplay('@', 'volmap'),
    BlockUsage.SUBDIR: BlockDisplay('/', 'subdir'),
    BlockUsage.INDEX: BlockDisplay('#', 'key'),
    BlockUsage.FILE: BlockDisplay('+', 'data'),
    BlockUsage.FREE: BlockDisplay('.', 'free'),
}

# Map from (is_free, marked_free) to style string
USAGE_STYLE = {
    (True, True): "on grey23",    # Correctly free
    (False, False): "on green",   # Correctly used
    (True, False): "on yellow",   # Unvisited but marked used (warning)
    (False, True): "on red",      # Visited but marked free (error)
}


@dataclass
class BlockMap:
    """Mapping of block usage across a volume."""
    usage: list[BlockUsage]
    free_map: bitarray      # Reference to the volume's free map for consistency checking

    @property
    def total_blocks(self) -> int:
        return len(self.usage)

    def __post_init__(self):
        # The free map can be slightly larger since it has whole blocks
        assert ceil(len(self.usage)/block_size/8)  == len(self.free_map)/block_size/8, \
            f"BlockMap: incompatible usage length {len(self.usage)} and bitmap length {len(self.free_map)}"


def walk_volume(volume: Volume) -> BlockMap:
    """
    Walk the entire volume to categorize how each block is used.

    Returns a BlockMap with usage information for each block.
    """
    device = volume.device
    total_blocks = device.total_blocks
    usage = [BlockUsage.FREE] * total_blocks

    # Helper to mark blocks with usage type and handle conflicts
    def mark_blocks(usage: list[BlockUsage], accessed: list[tuple[int, str]], cwd: str = '/', is_voldir: bool = False):
        """
        Mark blocks with usage type and log warnings for conflicts.

        Args:
            blocks_with_types: List of (block_idx, block_type) tuples from typed access log
            cwd: Current path for logging
            is_voldir: True if marking volume directory blocks
        """
        for block_idx, block_type in accessed:
            new_usage = BlockUsage.from_block_type(block_type, is_voldir)

            if usage[block_idx] != BlockUsage.FREE:
                logging.warning(
                    f"Block {block_idx} already marked as {usage[block_idx].name}, "
                    f"but '{cwd}' is also using it as {new_usage.name}"
                )
            usage[block_idx] = new_usage

    # Walk all files and directories recursively, tracking block access
    def walk_directory(dir_entry: FileEntry, cwd: str = "/"):
        """Recursively walk a directory and mark all blocks it accesses."""
        # Mark session before reading to track which blocks are accessed
        mark = device.mark_session()
        dir_file = volume.read_directory(dir_entry)

        # Get all blocks read during directory read (these are directory blocks)
        dir_blocks = device.get_typed_access_log('r', mark)
        mark_blocks(usage, dir_blocks, cwd, is_voldir=dir_entry.is_volume_dir)

        # Process each entry in the directory
        for entry in dir_file.entries:
            if not entry.is_active:
                continue

            # Build path for this entry
            entry_path = f"{cwd}{entry.file_name}/" if entry.is_dir else f"{cwd}{entry.file_name}"

            if entry.is_dir:
                # Recursively walk subdirectories
                walk_directory(entry, entry_path)
            elif entry.is_plain_file:
                # Mark plain file blocks
                walk_file(entry, entry_path)
            elif entry.storage_type == StorageType.extended:
                # Mark extended file blocks
                walk_extended_file(entry, entry_path)

    def walk_file(entry: FileEntry, cwd: str):
        """Walk a file and mark all its blocks by reading it."""
        # Mark session before reading to track which blocks are accessed
        mark = device.mark_session()
        try:
            volume.read_simple_file(entry)
        except (AssertionError, Exception) as e:
            logging.warning(f"Error reading file '{cwd}': {e}")
            return

        # Get all blocks read during file read with their types
        blocks_with_types = device.get_typed_access_log('r', mark)
        mark_blocks(usage, blocks_with_types, cwd)

    def walk_extended_file(entry: FileEntry, cwd: str):
        """Walk an extended file (storage type 5) and mark all its blocks."""
        # Mark session before reading to track which blocks are accessed
        mark = device.mark_session()
        try:
            volume.read_extended_file(entry)
        except (AssertionError, Exception) as e:
            logging.warning(f"Error reading extended file '{cwd}': {e}")
            return

        # Get all blocks read during file read with their types
        blocks_with_types = device.get_typed_access_log('r', mark)
        mark_blocks(usage, blocks_with_types, cwd)

    # Get header for bitmap info
    h = volume.root.header
    assert isinstance(h, VolumeDirectoryHeaderEntry)

    # Mark loader blocks (0-1)
    mark_blocks(
        usage,
        [(i, 'LoaderBlock') for i in range(2)]
        + [(i + h.bitmap_pointer, 'BitmapBlock') for i in range(device.bitmap_blocks)]
    )

    # Start walking from root
    walk_directory(FileEntry.root)

    return BlockMap(usage=usage, free_map=device.free_map)


def format_block_map(block_map: BlockMap, width: int = 64) -> str:
    """
    Create a visual ASCII representation of volume block usage.
    """

    lines: list[Text] = []
    i = 0
    last_collapsible: BlockUsage | None = None
    collapsed_count = 0

    def append_collapsed_lines():
        """Format a line representing collapsed identical rows."""
        assert last_collapsible
        type_name = BLOCK_CONFIG[last_collapsible].type

        # Create centered message
        message = f"+{collapsed_count*width} {type_name} blocks"
        centered_text = message.center(width)

        # Get style for this block type (collapsed lines are always consistent)
        is_free = last_collapsible == BlockUsage.FREE
        sample_style = USAGE_STYLE[(is_free, is_free)]

        line = Text(" ...  ", style="white")
        line.append(centered_text, style=sample_style)
        lines.append(line)


    while i < block_map.total_blocks:
        # Get the next line of blocks
        line_usage = block_map.usage[i:i+width]
        line_free = list(map(bool, block_map.free_map[i:i+width]))

        collapsible: BlockUsage | None = None
        if i+width <= block_map.total_blocks:
            if all(line_free) and all(u == BlockUsage.FREE for u in line_usage):
                collapsible = BlockUsage.FREE
            elif not(any(line_free)) and all(u == BlockUsage.FILE for u in line_usage):
                collapsible = BlockUsage.FILE

        if collapsible and collapsible == last_collapsible:
            collapsed_count += 1
        else:
            # Output collapsed lines if we have any
            if collapsed_count > 0:
                append_collapsed_lines()
                collapsed_count = 0

            # Format and output current line
            text = Text(f"{i:04X}: ", style="white")
            for j, usage in enumerate(line_usage):
                style = USAGE_STYLE[(usage == BlockUsage.FREE, bool(block_map.free_map[i+j]))]
                text.append(BLOCK_CONFIG[usage].symbol, style=style)
            lines.append(text)

        last_collapsible = collapsible
        i += width

    # Handle any remaining collapsed lines at the end
    if collapsed_count > 0:
        append_collapsed_lines()

    # Render to string
    buffer = StringIO()
    temp_console = Console(file=buffer, force_terminal=True)
    for line in lines:
        temp_console.print(line)
    return buffer.getvalue()


def format_legend() -> str:
    """Return a legend explaining the block usage symbols and colors."""
    # Build symbols line
    symbols_line = Text("Symbols: ", style="bold")

    # Add all block types including FREE
    symbol_parts: list[Text] = []
    for usage in BlockUsage:
        config = BLOCK_CONFIG[usage]
        part = Text()
        # Use the consistency style: free blocks get grey, used blocks get green
        bg_style = USAGE_STYLE[(usage == BlockUsage.FREE, usage == BlockUsage.FREE)]
        part.append(config.symbol, style=bg_style)
        part.append(f" {config.type}", style="")
        symbol_parts.append(part)

    # Join symbol parts with commas
    for i, part in enumerate(symbol_parts):
        symbols_line.append_text(part)
        if i < len(symbol_parts) - 1:
            symbols_line.append(", ")

    # Build colors line
    colors_line = Text("Colors: ", style="bold")
    colors_line.append("correctly marked ")
    colors_line.append("used", style=USAGE_STYLE[(False, False)])
    colors_line.append(", ")
    colors_line.append("free", style=USAGE_STYLE[(True, True)])
    colors_line.append("; incorrectly marked ")
    colors_line.append("used", style=USAGE_STYLE[(True, False)])
    colors_line.append(", ")
    colors_line.append("free", style=USAGE_STYLE[(False, True)])

    # Render to string
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True)
    console.print(symbols_line)
    console.print(colors_line)
    return buffer.getvalue()

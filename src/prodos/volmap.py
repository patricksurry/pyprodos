"""Volume block usage mapping and visualization."""
from typing import NamedTuple
from dataclasses import dataclass
from enum import Enum, auto
from bitarray import bitarray
import logging

from .volume import Volume
from .metadata import FileEntry, VolumeDirectoryHeaderEntry


class BlockUsage(Enum):
    """Categories of block usage on a ProDOS volume."""
    LOADER = auto()  # Boot loader blocks (0-1)
    VOLDIR = auto()  # Volume directory blocks (2-5)
    BITMAP = auto()  # Volume bitmap blocks
    SUBDIR = auto()  # Subdirectory blocks
    INDEX = auto()   # File index blocks (sapling/tree)
    FILE = auto()    # File data blocks
    FREE = auto()    # Free blocks


class BlockConfig(NamedTuple):
    """Configuration for displaying a block type."""
    symbol: str
    type: str


# Central configuration for block usage display properties
BLOCK_CONFIG = {
    BlockUsage.LOADER: BlockConfig('!', 'loader'),
    BlockUsage.VOLDIR: BlockConfig('%', 'voldir'),
    BlockUsage.BITMAP: BlockConfig('@', 'volmap'),
    BlockUsage.SUBDIR: BlockConfig('/', 'subdir'),
    BlockUsage.INDEX: BlockConfig('#', 'key'),
    BlockUsage.FILE: BlockConfig('+', 'data'),
    BlockUsage.FREE: BlockConfig('.', 'free'),
}


@dataclass
class BlockMap:
    """Mapping of block usage across a volume."""
    total_blocks: int
    usage: list[BlockUsage]
    free_map: bitarray      # Reference to the volume's free map for consistency checking

    def __post_init__(self):
        assert len(self.usage) == self.total_blocks, \
            f"BlockMap: usage length {len(self.usage)} != total_blocks {self.total_blocks}"


def walk_volume(volume: Volume) -> BlockMap:
    """
    Walk the entire volume to categorize how each block is used.

    Returns a BlockMap with usage information for each block.
    """
    device = volume.device
    total_blocks = device.total_blocks
    usage = [BlockUsage.FREE] * total_blocks

    # Mark loader blocks (0-1)
    usage[0] = BlockUsage.LOADER
    usage[1] = BlockUsage.LOADER

    # Get bitmap pointer for later
    h = volume.root.header
    assert isinstance(h, VolumeDirectoryHeaderEntry)

    # Mark bitmap blocks
    for i in range(device.bitmap_blocks):
        usage[h.bit_map_pointer + i] = BlockUsage.BITMAP

    # Walk all files and directories recursively, tracking block access
    def walk_directory(dir_entry: FileEntry, cwd: str = "/"):
        """Recursively walk a directory and mark all blocks it accesses."""
        # Mark session before reading to track which blocks are accessed
        mark = device.mark_session()
        dir_file = volume.read_directory(dir_entry)

        # Get all blocks read during directory read (these are directory blocks)
        dir_blocks = device.get_access_log('r', mark)
        new_usage = BlockUsage.VOLDIR if dir_entry.is_volume_dir else BlockUsage.SUBDIR
        for block_idx in dir_blocks:
            if usage[block_idx] != BlockUsage.FREE:
                logging.warning(
                    f"Block {block_idx} already marked as {usage[block_idx].name}, "
                    f"but directory '{cwd}' is also reading it"
                )
            usage[block_idx] = new_usage

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
                # Mark file blocks
                walk_file(entry, entry_path)

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

        for block_idx, block_type in blocks_with_types:
            # Determine usage based on block type
            new_usage = BlockUsage.INDEX if block_type == 'IndexBlock' else BlockUsage.FILE

            if usage[block_idx] != BlockUsage.FREE:
                logging.warning(
                    f"Block {block_idx} already marked as {usage[block_idx].name}, "
                    f"but file '{cwd}' is also using it as {new_usage.name}"
                )
            usage[block_idx] = new_usage

    # Start walking from root
    walk_directory(FileEntry.root, "/")

    return BlockMap(total_blocks=total_blocks, usage=usage, free_map=device.free_map)


def format_block_map(block_map: BlockMap, width: int = 64) -> str:
    """
    Format a block map as a visual ASCII representation with colors.

    Args:
        block_map: The BlockMap to visualize
        width: Number of blocks per line (default 64)

    Returns:
        Formatted string representation of the block map
    """
    from rich.console import Console
    from rich.text import Text
    from io import StringIO

    def get_style(usage: BlockUsage, marked_free: int) -> str:
        """Determine the style for a block based on usage and bitmap consistency."""
        actually_free = usage == BlockUsage.FREE

        # Determine background color based on consistency
        if actually_free and marked_free:
            # Correctly free - grey background
            return "on grey23"
        elif not actually_free and not marked_free:
            # Correctly used - use configured style for this block type
            return "on green"
        elif actually_free and not marked_free:
            # Unvisited but marked used - yellow background
            return "on yellow"
        else:  # not is_free_in_usage and is_free_in_bitmap
            # Visited but marked free - red background
            return "on red"

    def format_collapsed_line(num_blocks: int, usage_type: BlockUsage, marked_free: int) -> Text:
        """Format a line representing collapsed identical rows."""
        # Get type name from config
        type_name = BLOCK_CONFIG[usage_type].type

        # Create centered message
        message = f"+{num_blocks} {type_name}"
        centered_text = message.center(width)

        # Get style for this block type
        sample_style = get_style(usage_type, marked_free)

        line = Text(" ...  ", style="white")
        line.append(centered_text, style=sample_style)
        return line

    lines: list[Text] = []
    i = 0
    prev_line = None
    prev_usage_types = None
    collapsed_count = 0

    while i < block_map.total_blocks:
        # Get the next line of blocks
        end = min(i + width, block_map.total_blocks)
        line_usage = block_map.usage[i:end]
        line_str = ''.join(BLOCK_CONFIG[u].symbol for u in line_usage)

        # Check if this line is identical to the previous one
        if line_str == prev_line and i + width < block_map.total_blocks:
            collapsed_count += 1
            i += width
            continue

        # If we had collapsed lines, show the ellipsis with count and type
        if collapsed_count > 0:
            num_blocks = collapsed_count * width
            usage_type = prev_usage_types[0] if prev_usage_types else BlockUsage.FREE
            marked_free = block_map.free_map[i-width]
            lines.append(format_collapsed_line(num_blocks, usage_type, marked_free))
            collapsed_count = 0

        # Format the line with offset and usage
        text = Text(f"{i:04X}: ", style="white")
        for j, usage in enumerate(line_usage):
            style = get_style(usage, block_map.free_map[i+j])
            text.append(BLOCK_CONFIG[usage].symbol, style=style)
        lines.append(text)

        prev_line = line_str
        prev_usage_types = line_usage
        i += width

    # Handle any remaining collapsed lines at the end
    if collapsed_count > 0:
        num_blocks = collapsed_count * width
        usage_type = prev_usage_types[0] if prev_usage_types else BlockUsage.FREE
        sample_block_idx = i - width
        lines.append(format_collapsed_line(num_blocks, usage_type, sample_block_idx))

    # Render to string
    buffer = StringIO()
    temp_console = Console(file=buffer, force_terminal=True)
    for line in lines:
        temp_console.print(line)
    return buffer.getvalue()


def format_legend() -> str:
    """Return a legend explaining the block usage symbols and colors."""
    from rich.console import Console
    from rich.text import Text
    from io import StringIO

    # Build symbols line
    symbols_line = Text("Symbols: ", style="bold")

    # Add all block types including FREE
    symbol_parts: list[Text] = []
    for usage in BlockUsage:
        config = BLOCK_CONFIG[usage]
        part = Text()
        # Use green background for all except FREE (which gets grey)
        bg_style = "on grey23" if usage == BlockUsage.FREE else "on green"
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
    colors_line.append("used", style="on green")
    colors_line.append(", ")
    colors_line.append("free", style="on grey23")
    colors_line.append("; incorrectly marked ")
    colors_line.append("used", style="on yellow")
    colors_line.append(", ")
    colors_line.append("free", style="on red")

    # Render to string
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True)
    console.print(symbols_line)
    console.print(colors_line)
    return buffer.getvalue()

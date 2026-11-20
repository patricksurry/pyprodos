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

from .errors import ProDOSError
from .globals import block_size
from .volume import Volume, loader_blocks


class BlockUsage(Enum):
    """Categories of block usage on a ProDOS volume."""
    LOADER = auto()  # Boot loader blocks (0-1)
    VOLDIR = auto()  # Volume directory blocks (2-5)
    BITMAP = auto()  # Volume bitmap blocks
    SUBDIR = auto()  # Subdirectory blocks
    INDEX = auto()   # File index blocks (sapling/tree)
    FILE = auto()    # File data blocks
    FREE = auto()    # Free blocks


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
    total_blocks = volume.header.total_blocks
    usage = [BlockUsage.FREE] * total_blocks

    def mark(blocks: list[int], kind: BlockUsage, path: str):
        for b in blocks:
            if not 0 <= b < total_blocks:
                logging.warning(f"'{path}' uses block {b} outside the volume")
                continue
            if usage[b] != BlockUsage.FREE:
                logging.warning(
                    f"Block {b} already marked as {usage[b].name}, "
                    f"but '{path}' is also using it as {kind.name}"
                )
            usage[b] = kind

    mark(loader_blocks, BlockUsage.LOADER, 'loader')
    mark(volume.bitmap.blocks, BlockUsage.BITMAP, 'bitmap')

    for path, d in volume.walk():
        mark(d.blocks, BlockUsage.VOLDIR if d.is_volume_directory else BlockUsage.SUBDIR, path)
        for e in d.entries:
            if e.is_dir:
                continue
            try:
                f = volume.read_file(e)
            except ProDOSError as ex:
                logging.warning(f"Error reading file '{path}{e.file_name}': {ex}")
                continue
            mark(f.index_blocks, BlockUsage.INDEX, path + e.file_name)
            mark(f.data_blocks, BlockUsage.FILE, path + e.file_name)

    return BlockMap(usage=usage, free_map=volume.bitmap.free_map)


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

from typing import Final

block_size_bits: Final          = 9
block_size: Final               = 1 << block_size_bits     # 512 bytes per block
entry_length: Final             = 39        # $27, bytes per directory entry
entries_per_block: Final        = 13        # $0D, entries per directory block (4 + 13*39 = 511)
volume_key_block: Final         = 2         # blocks 0-1 hold the boot loader
volume_directory_length: Final  = 4         # the volume directory is always blocks 2-5
max_eof: Final                  = 0xFFFFFF  # EOF is a 3-byte field
max_volume_blocks: Final        = 0xFFFF    # block numbers are 2-byte fields

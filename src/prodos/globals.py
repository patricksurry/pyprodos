from typing import Final

# constants we can verify
block_size_bits: Final          = 9
block_size: Final               = 1 << block_size_bits
entry_length: Final             = 39
entries_per_block: Final        = 13
volume_key_block: Final         = 2
volume_directory_length: Final  = 4     # not sure why this needs to be fixed

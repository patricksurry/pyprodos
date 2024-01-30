from typing import Final

# constants we can verify
block_size_bits: Final          = 9
block_size: Final               = 1 << block_size_bits
entry_length: Final             = 39
entries_per_block: Final        = 13
volume_key_block: Final         = 2
volume_directory_length: Final  = 4     # not sure why this is fixed

access_flags: Final = dict(
    R = 1<<0,  # read
    W = 1<<1,  # write
    I = 1<<2,  # invisible
    # bits 3 and 4 reserved
    B = 1<<5,  # backup
    N = 1<<6,  # rename
    D = 1<<7,  # destroy
)

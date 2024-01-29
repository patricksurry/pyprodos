# constants we can verify
block_size_bits = 9
block_size = 1 << block_size_bits
entry_length = 39
entries_per_block = 13
volume_key_block = 2
volume_directory_length = 4     # not sure why this is fixed

access_flags = {1<<0: 'R', 1<<1: 'W', 1<<5: 'B', 1<<6: 'N', 1<<7: 'D'}


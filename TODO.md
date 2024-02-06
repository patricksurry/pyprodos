- check `prodos import X Y`  when Y already exists?

- why doesn't this work: `prodos boot.2mg create --name MYVOL --size 32678 --loader bootloader.bin`

- need file type $ff for system file boot
- implemnt: mv, rmdir, cp, check, chinfo, cat
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185
- add --verbose option to show access log (`device.dump_access_log()`)
- add short form options


- for `check`:
    - validate parent_entry_number and parent_pointer for subdir header
    - validate header_pointer for file entry
    - recurse all files and directories
    - check read activity matches used count
    - check file blocks used matches visited

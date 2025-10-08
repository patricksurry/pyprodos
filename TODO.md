- bug (because of fnmatch?): 
    prodos images/2018-01-23\ -\ ProDOS8.2mg ls games
    vs 
    prodos images/2018-01-23\ -\ ProDOS8.2mg ls GAMES


- wildcard import doesn't seem to work, e.g. `prodos <vol> import *.fs`

- directory import doesn't work, e.g. `prodos <vol> import examples`

- implement mkdir

- check `prodos <vol> import X Y`  when Y already exists?

- why doesn't this work: `prodos boot.2mg create --name MYVOL --size 32678 --loader bootloader.bin`

- need file type $ff for system file boot
- implement: mv, rmdir, cp, check, chinfo, cat
- easier way to extract loader or specific blocks
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185
- add --verbose option to show access log (`device.dump_access_log()`)
- add short form options


- for `check`:
    - validate parent_entry_number and parent_pointer for subdir header
    - validate header_pointer for file entry
    - recurse all files and directories
    - check read activity matches used count
    - check file blocks used matches visited

- storage type $4 (pascal area) and $5 (GS/OS extended) see https://prodos8.com/docs/technote/25/
package name py-prodos

todo:

- something wrong with import X Y  when Y already exists?

- import-blocks
- export-blocks
- could add a repl mode https://github.com/tiangolo/typer/issues/185
- *todo* writing changed directories if block count shrinks
- chmod/chtype


boot test:  export from prodos image, import to new image w/ bootloader, does it boot in emu?

- verbose option to show access log
        print(volume.device.dump_access_log())

chkdsk:
- validate parent_entry_number and parent_pointer for subdir header
- validate header_pointer for file entry
- recurse all files and directories
- check read activity matches used count
- check file blocks used matches visited

prodos image from emulator

hexdump -C ~/Downloads/snapshot.viisnapshot | grep 'f5 03 fb'
00036520  f5 03 fb 03 62 fa fa c3  00 00 00 00 00 00 00 01  |....b...........|

36520 - $fff8  = 25528


patch boot:

py65mon -l loader_plus_voldir.bin -a 0x800

load apple2o.rom top
load block7.bin 1e00
load PRODOS.bin 2000

; set Cn00: a0 20 a0 00 a0 03
f c300 a0 20 a0 00 a0 03 a9 00 18 60

; .a c306
; $c306  a9 00     LDA #$00
; $c308  18        CLC
; $c309  60        RTS

;TODO
; for status call A=0, CLC, X/Y = block count (lo/hi)

; set CnFF: 06 (for Cn06 entry)
; set CnFE: %11001111  (or just #$ff, not sure about vols)
; set CnFC/D: ff ff (max blocks)
f c3fc ff ff cf 06

; lda #1
; ldx #30    ; slot 3
registers a=1, x=30

; breakpoint on prodos entry
ab 2000

; launch bootloader
g 801

; breakpoint at Cn06
ab c306

; check command (0=status, 1=read, 2=write, 3=format)
m 42/6  (42=cmd, 44/45=bufp, 46/47=blk)

prodos rom entry:
fe84: SETNORM (video)


The MLI then searches the volume directory of the boot disk for the first file with the name XXX.SYSTEM and type $FF, loads it into memory starting at $2000, and executes it.


other entries from disass:

python ../pydisass6502/disass.py -i PRODOS.bin -s 0x2000 -o PRODOS.asm -c PRODOS.stats

https://6502disassembly.com/a2-rom/OrigF8ROM.html

    {"addr": "fb1e", "symbol": "PREAD", "comm": "read paddles"},
    {"addr": "fb2f", "symbol": "INIT",  "comm": "init gfx"},
    {"addr": "fbb3", "symbol": "MUL", "comm": "multiply?"},
    {"addr": "fbc0", "symbol": "MDRTS", "comm": "known rts"},
    {"addr": "fc58", "symbol": "HOME", "comm": "cls/home?"},
    {"addr": "fdf9", "symbol": "VIDOUT", "comm": "output acc as ascii"},
    {"addr": "fe1f", "symbol": "SETMODE_RTS", "comm": "another rts},
    {"addr": "fe84", "symbol": "SETNORM", "comm": "set normal video"},
    {"addr": "fe89", "symbol": "SETKBD", "comm": "setup keyboard"},
    {"addr": "fe93", "symbol": "SETVID", "comm": "setup video out"},
    {"addr": "fefe", "symbol": "$fefe", "comm": "?? bytes fa fa a9 - checks writable"},
    {"addr": "feff", "symbol": "$feff"},
    {"addr": "ff00", "symbol": "$ff00"},
    {"addr": "fffe", "symbol": "IRQL", "comm": "set to $fa86 in apple rom"},
    {"addr": "ffff", "symbol": "IRQH"}




python ../pydisass6502/disass.py -i prodos_loader.bin -o prodos_loader.asm -c prodos_loader.stats -e prodos_loader.map.json

loader blk0-1 @ 800-bff
vol dir blk 2-5 @ c00-1400
prodos @ 2000

blk 7 -> 1e00
blk 8 -> 2000



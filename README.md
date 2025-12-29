pyprodos
---

This is a simple Python implementation of the Apple ProDOS :tm: filesystem based on the
[technical reference manual](https://prodos8.com/docs/techref/file-organization/).

It provides a simple unix-style CLI for managing existing ProDOS images in 
`.po` and `.2mg` files and for creating new ones.
This provides an accessible file system for Apple // or other 8-bit hardware. 

As an example, let's recreate a ProDOS boot volume.  Grab the ProDOS 2.4.3
boot disk from https://prodos8.com/.  (There's a copy in `images/` here.)
Check what's on it:

    % prodos info images/ProDOS_2_4_3.po

    Volume PRODOS.2.4.3 23-12-29T19:07
    BlockDevice on images/ProDOS_2_4_3.po contains 280 total blocks, 26 free (91% used)

    % prodos ls images/ProDOS_2_4_3.po

    File name               EOF T/FT Access Created        Modified      Blocks @ Key
    ---------------------------------------------------------------------------------
    VIEW.README             512 1/FC RW-BND 18-02-13T09:09 18-02-13T09:09     1 @ 250
    ...
    BASIC.SYSTEM          10240 2/FF RW-BND 23-12-30T02:43 23-12-30T02:43    21 @ 42
    ...
    PRODOS                17128 2/FF RW-BND 23-12-30T02:43 23-12-30T02:43    34 @ 7
    README                  999 2/04 RW-BND 23-12-30T02:43 23-12-30T02:43     3 @ 251
        17 files in PRODOS.2.4.3 F RW--ND 23-12-29T19:07

Let's extract the `PRODOS` o/s and `BASIC.SYSTEM` files, plus the bootloader.
ProDOS should execute the first `.SYSTEM` file it finds after it boots.

    % prodos export images/ProDOS_2_4_3.po /PRODOS /BASIC.SYSTEM . --loader loader.bin

Now we'll make a new 140K (280 block) floppy boot disk:

    % prodos create boot.po --name MYVOL --size 280

then import the system files and bootloader and check the listing:

    % prodos import boot.po --loader loader.bin PRODOS BASIC.SYSTEM /

    % prodos ls boot.po

    File name               EOF T/FT Access Created        Modified      Blocks @ Key
    ---------------------------------------------------------------------------------
    PRODOS                17128 2/FF RW-BND 25-12-28T15:20 25-12-28T15:20    34 @ 7
    BASIC.SYSTEM          10240 2/FF RW-BND 25-12-28T15:20 25-12-28T15:20    21 @ 41
        2 files in MYVOL F RW-BND 25-12-28T15:19

Finally, test the image in your favorite emulator.  I used [VirtualII](https://www.virtualii.com/) and popped my volume in the virtual Disk ][ drive.   After a ProDOS splash screen, you you see the familiar Basic prompt:

                PRODOS BASIC 1.7
            COPYRIGHT APPLE  1983-92

    ]

My original goal was to learn how the on-disk representation worked and to manage
disk images for a 6502-based breadboard computer.
ProDOS is simple enough that a minimal kernel
can be very small.  For example I use a read-only
version that's only a couple hundred lines of TaliForth.
I also ported a version of the original 6502
ProDOS filestyem kernel: [p8fs](https://github.com/patricksurry/p8fs).


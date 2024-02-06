This is a inefficient but simple implementation of the
Apple ProDOS :tm: filesystem based on the
[technical reference manual](https://prodos8.com/docs/techref/file-organization/).

`pyprodos` aims to be compatible with existing `.po` and `.2mg` images used
for emulating Apple // series hardware.
It includes a simple command-line tool to create and manipulate ProDOS disk images
which currently supports `create`, `import`, `export`, `info`, `ls`, `rm` and
performs a number of volume integrity checks.  There's more [to do](TODO.md).

For example, let's recreate a ProDOS boot volume.  Grab the ProDOS 2.4.3
boot disk from https://prodos8.com/.  (There's a copy in `images/` here.)
Check what's on it:

    % prodos images/ProDOS_2_4_3.po ls

    BASIC.SYSTEM          10240 2/FF RW-BND 23-12-30T02:43 23-12-30T02:43 21 @ 42
    ...
    PRODOS                17128 2/FF RW-BND 23-12-30T02:43 23-12-30T02:43 34 @ 7
    README                  999 2/04 RW-BND 23-12-30T02:43 23-12-30T02:43 3 @ 251
        17 files in PRODOS.2.4.3 F RW--ND 23-12-29T19:07

Let's extract the `PRODOS` o/s and `BASIC.SYSTEM` files.  ProDOS should execute
the first `.SYSTEM` file it finds after it boots.

    % prodos images/ProDOS_2_4_3.po export PRODOS BASIC.SYSTEM .

We also need to grab the bootloader, which occupies the first two blocks on the disk.
We can use `dd` for that since `.po` disk images are just binary files with a 512 byte
block size. (The `.2mg` format just adds a 64 byte header.)

    % dd bs=512 count=2 if=images/ProDOS_2_4_3.po of=loader.bin

Now we'll make a new 140K (280 block) floppy boot disk:

    % prodos boot.po create --name MYVOL --size 280 --loader loader.bin

and then import our boot files and check the listing:

    % prodos boot.po import PRODOS BASIC.SYSTEM /

    % prodos boot.po ls

    PRODOS                17128 2/FF RW-BND 24-02-05T19:37 24-02-05T19:37 34 @ 7
    BASIC.SYSTEM          10240 2/FF RW-BND 24-02-05T19:37 24-02-05T19:37 21 @ 41
        2 files in MYVOL F RW-BND 24-02-05T19:37


Finally, test the image in your favorite emulator.  I used [VirtualII](https://www.virtualii.com/) and popped my volume in the virtual Disk ][ drive.   After a ProDOS splash screen, you you see the familiar Basic prompt:

                PRODOS BASIC 1.7
            COPYRIGHT APPLE  1983-92

    ]

My goal was to learn how the on-disk representation worked and manage
disk images for a 6502-based breadboard computer with a portable ProDOS
filestyem kernel I ported: [p8fs](https://github.com/patricksurry/p8fs).


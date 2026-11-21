pyprodos
---

This is a simple Python implementation of the Apple ProDOS :tm: filesystem based on the
[technical reference manual](https://prodos8.com/docs/techref/file-organization/).

It provides a simple unix-style CLI for managing existing ProDOS images in 
`.po` and `.2mg` files and for creating new ones.
This provides an accessible file system for Apple // or other 8-bit hardware.

Install it from PyPI:

    % pip install pyprodos
    % prodos --help

Commands
---

| Command | Does |
|---|---|
| `create` | Create an empty `.po` or `.2mg` volume |
| `info` | Show volume details, and with `--map` a picture of block usage |
| `check` | Validate the volume's structure |
| `ls` | List files and directories, optionally `--recursive` |
| `cp`, `mv`, `rm` | Copy, move/rename and remove files on the volume |
| `mkdir`, `rmdir` | Create and remove directories |
| `chinfo` | Change a file's type, aux type or access flags |
| `import`, `export` | Copy files (or the boot loader) between the host and the volume |

Paths on the volume are case-insensitive, start with `/` and can use wildcards like `/SYSTEM/*.SYSTEM`.
Commands that change a volume accept `--output copy.po` to write the result to a copy instead,
and every command accepts `--log access.log` to record each block it reads and writes.

Example: a boot disk
---

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
        2 files in MYVOL F RW--ND 25-12-28T15:19

Finally, test the image in your favorite emulator.  I used [VirtualII](https://www.virtualii.com/) and popped my volume in the virtual Disk ][ drive.   After a ProDOS splash screen, you see the familiar Basic prompt:

                PRODOS BASIC 1.7
            COPYRIGHT APPLE  1983-92

    ]

File types
---

Files imported from the host get type SYS (`$FF`) if they're named `PRODOS` or
`*.SYSTEM`, which is what ProDOS needs to boot them, and BIN (`$06`) otherwise.
Use `--type` and `--aux` to set them explicitly, e.g. a text file or a binary with
its load address:

    % prodos import boot.po --type 04 notes.txt /NOTES
    % prodos import boot.po --type 06 --aux 2000 game.bin /GAME

`cp` and `mv` preserve each file's type, aux type and dates, and `chinfo` changes them later:

    % prodos chinfo boot.po /GAME --aux 0800 --access RWBND

Checking a volume
---

Use `check` to validate a volume's structure: directory back pointers, block
counts, cross-linked blocks and the volume bit map:

    % prodos check boot.po
    No problems found

How the code is organized
---

The code mirrors the [technical reference](https://prodos8.com/docs/techref/file-organization/),
using one name per concept where the spec overloads "directory", "entry" and "header":

| Module | Concept |
|---|---|
| `device.py` | `BlockDevice`: a `.po` or `.2mg` image as numbered 512-byte blocks, with an access log |
| `bitmap.py` | `Bitmap`: the volume bit map recording free blocks |
| `blocks.py` | Block formats: directory, index, bit map and extended key blocks |
| `metadata.py` | Directory records: `VolumeDirectoryHeader`, `SubdirectoryHeader`, `FileEntry` (and a glossary) |
| `file.py` | `Fork`: bytes stored as a seedling, sapling or tree; `File`: an entry plus its fork(s) |
| `directory.py` | `Directory`: a chain of blocks holding a header and fixed entry slots |
| `volume.py` | `Volume`: loader, volume directory and bit map; path lookup and walking |
| `check.py` | The invariants of a well-formed volume |

Development
---

The project uses [uv](https://docs.astral.sh/uv/).  `uv sync` sets up `.venv` with the dev tools,
then run the same checks as CI:

    % uv run ruff check src tests
    % uv run pyright
    % uv run pytest

The tests use the real disk images in `images/`, and every image a test leaves behind is
checked with `check_volume`.

Background
---

My original goal was to learn how the on-disk representation worked and to manage
disk images for a 6502-based breadboard computer.
ProDOS is simple enough that a minimal kernel
can be very small.  For example I use a read-only
version that's only a couple hundred lines of TaliForth.
I also ported a version of the original 6502
ProDOS filesystem kernel: [p8fs](https://github.com/patricksurry/p8fs).


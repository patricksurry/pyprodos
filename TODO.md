- package for pypi
- support walk for gsos extended file
- support export for gsos extended file
- implement check CLI command, using walk with some additional checks, file size vs block count
- implement chinfo CLI command
- note pascal area (storage type 4) is not supported
- fix: hacked file type $ff everywhere, needed for system file boot
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185


# invalid file size example:
❯ prodos ls images/ProDOS8.2mg /GAMES/A.TO.B/BILLBUDGE/BUDGE.SYSTEM
BUDGE.SYSTEM            640 1/FF RW-BND 17-06-21T15:52 14-10-01T05:33 1 @ 1690

> prodos info --map ./images/GSOSv6.0.1.po
WARNING:root:FileEntry: unexpected storage type 5

GSHK                    512 5/B3 RW-BND 92-09-08T00:46 92-10-10T15:11   236 @ 1921


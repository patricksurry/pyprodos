

- storage type $4 (pascal area) and $5 (GS/OS extended) see https://prodos8.com/docs/technote/25/

- hacked file type $ff everywhere, needed for system file boot
- implement: check, chinfo, cat
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185


# invalid file size?
❯ prodos ls images/ProDOS8.2mg /GAMES/A.TO.B/BILLBUDGE/BUDGE.SYSTEM
BUDGE.SYSTEM            640 1/FF RW-BND 17-06-21T15:52 14-10-01T05:33 1 @ 1690

> prodos info --map ./images/GSOSv6.0.1.po
WARNING:root:FileEntry: unexpected storage type 5
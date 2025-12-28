- hacked file type $ff everywhere, needed for system file boot
- implement: check, chinfo, cat
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185


# invalid file size?
❯ prodos ls images/ProDOS8.2mg /GAMES/A.TO.B/BILLBUDGE/BUDGE.SYSTEM
BUDGE.SYSTEM            640 1/FF RW-BND 17-06-21T15:52 14-10-01T05:33 1 @ 1690

> prodos info --map ./images/GSOSv6.0.1.po
WARNING:root:FileEntry: unexpected storage type 5


## ProDOS Storage Types 4 and 5 Summary

**Storage Type $4 (Pascal Area)**
- Indicates a Pascal area on a ProFile hard disk
- Used by the Apple II Pascal system
- These files are created by the Apple Pascal ProFile Manager (PPM)
- The files are internally divided into pseudo-volumes by Apple II Pascal
- Typically named `PASCAL.AREA` (name length of 10) with file type $EF
- The files represent entire Pascal volumes stored within a ProDOS file structure

**Storage Type $5 (GS/OS Extended File)**
- Used by the ProDOS FST (File System Translator) in GS/OS
- Stores extended files with both a data fork and a resource fork
- The key block points to an extended key block entry
- The extended key block contains mini-directory entries for both forks:
  - Data fork mini-entry is at offset +$000
  - Resource fork mini-entry is at offset +$100 (+256 decimal)
- This is how GS/OS implements Mac-style resource/data fork files on ProDOS volumes

Both are considered **non-standard storage types** that extend ProDOS capabilities beyond the basic file types (seedling/sapling/tree files and directories).

References:
- https://prodos8.com/docs/technote/25/
- https://mirrors.apple2.org.za/apple.cabi.net/FAQs.and.INFO/A2.TECH.NOTES.ETC/A2.CLASSIC.TNTS/p8025.htm
- https://ciderpress2.com/formatdoc/ProDOS-notes.html
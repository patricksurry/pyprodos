## PyPI Publishing

When ready to publish to production PyPI 

1. **Update version in VERSION file** (e.g., to `0.4.0` or `1.0.0`)

2. **Rebuild the package:**
   ```bash
   rm -rf dist/ build/
   python -m build
   ```

3. **Create git commit and tag:**
   ```bash
   git commit -am "Release v0.4.0"       # sync with VERSION
   git tag -a v0.4.0 -m "Release version 0.4.0"
   git push origin
   git push origin v0.4.0
   ```

4. **Create GitHub release from the tag**

- Click on "Releases" (in the right sidebar or under the "Code" tab)
- Click "Draft a new release"
- In "Choose a tag" dropdown, select your existing tag (e.g., v0.0.3) or type a new one
- Fill in:
    - Release title: e.g., "Version 0.0.3" or "v0.0.3 - TestPyPI Release"
    - Description: Changelog, features, fixes, etc.
- Optionally attach files (like your built wheel/tarball from dist/)
- Click "Publish release"

5. **Upload to production PyPI:**
   ```bash
   python -m twine upload dist/*
   ```
   (Use PyPI API token, not TestPyPI)

6. **Verify installation:**
   ```bash
   # in a new tmp dir / terminal:
   python -m venv .venv
   pip install pyprodos
   ```

## Backlog

Next PR (CLI):
- move the remaining cp/mv/import destination logic from cli.py into the core
  (one-shot CLI and shell should both be thin wrappers raising ProDOSError)
- carry file type/aux type through host import/export with the CiderPress/AppleCommander
  naming convention, e.g. `NAME#FF2000`
- `prodos shell VOL`: mount a volume and run commands interactively using stdlib `cmd`,
  with `cd`/`pwd`, relative paths, tab completion of ProDOS paths, `lcd`/`lls` and `!cmd`
- show aux type in `ls` (currently only visible via export or the raw entry)
- maybe drop typer-di, which only provides trivial parameter aliases

Later / maybe:
- `cat` command to view text files (high-bit ASCII, CR line endings)
- write and import GS/OS extended files (reading and removing them works)
- the next release changes the library API (`Volume.open`, `Directory`, `File`, `Fork`),
  so bump the minor version

Done:
- `check` command (flags e.g. /GAMES/A.TO.B/BILLBUDGE/BUDGE.SYSTEM in images/ProDOS8.2mg,
  whose eof 640 exceeds a seedling's 512 bytes)
- file types: no more `$FF` everywhere; SYS for PRODOS and *.SYSTEM, else BIN, with `--type`/`--aux`
- `Volume.walk()` shared by check and the block map
- `chinfo` command
- reviewed TODO/NOTE comments

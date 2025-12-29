## PyPI Publishing

When ready to publish to production PyPI (currently on TestPyPI at v0.0.3):

1. **Update version in VERSION file** (e.g., to `0.1.0` or `1.0.0`)

2. **Rebuild the package:**
   ```bash
   rm -rf dist/ build/
   python -m build
   ```

3. **Create git commit and tag:**
   ```bash
   git add VERSION
   git commit -m "Release v0.1.0"       # sync with VERSION
   git tag -a v0.1.0 -m "Release version 0.1.0"
   git push origin main
   git push origin v0.1.0
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

- review #TODO/NOTE comments
- implement check CLI command, using walk with some additional checks, like eof file size vs actual block count used
- fix: hacked file type $ff everywhere, needed for system file boot
- move walk into volume.py and generalize so we can map a function across the directory tree (cf. check)
- implement chinfo CLI command
- (maybe) support import for gsos extended file
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185


# invalid file size example:
❯ prodos ls images/ProDOS8.2mg /GAMES/A.TO.B/BILLBUDGE/BUDGE.SYSTEM
BUDGE.SYSTEM            640 1/FF RW-BND 17-06-21T15:52 14-10-01T05:33 1 @ 1690


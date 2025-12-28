## PyPI Publishing

### Next Steps for Production Release

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
   git commit -m "Release v0.1.0"
   git tag -a v0.1.0 -m "Release version 0.1.0"
   git push origin main
   git push origin v0.1.0
   ```

4. **Upload to production PyPI:**
   ```bash
   python -m twine upload dist/*
   ```
   (Use PyPI API token, not TestPyPI)

5. **Verify installation:**
   ```bash
   # in a new tmp dir / terminal:
   python -m venv .venv
   pip install pyprodos
   ```

### Git Workflow for Releases

- Always tag releases: `git tag -a vX.Y.Z -m "Release version X.Y.Z"`
- Keep VERSION file in sync with git tags
- Push tags separately: `git push origin vX.Y.Z`
- Create a GitHub release from the tag for visibility
    - Click on "Releases" (in the right sidebar or under the "Code" tab)
    - Click "Draft a new release"
    - In "Choose a tag" dropdown, select your existing tag (e.g., v0.0.3) or type a new one
    - Fill in:
        - Release title: e.g., "Version 0.0.3" or "v0.0.3 - TestPyPI Release"
        - Description: Changelog, features, fixes, etc.
    - Optionally attach files (like your built wheel/tarball from dist/)
    - Click "Publish release"

---

## Backlog

- support walk for gsos extended file
- support export for gsos extended file
- implement check CLI command, using walk with some additional checks, like eof file size vs actual block count used
- implement chinfo CLI command
- add README note that pascal area storage type 4 is not supported
- fix: hacked file type $ff everywhere, needed for system file boot
- (maybe) add a repl mode https://github.com/tiangolo/typer/issues/185


# invalid file size example:
❯ prodos ls images/ProDOS8.2mg /GAMES/A.TO.B/BILLBUDGE/BUDGE.SYSTEM
BUDGE.SYSTEM            640 1/FF RW-BND 17-06-21T15:52 14-10-01T05:33 1 @ 1690

> prodos info --map ./images/GSOSv6.0.1.po
WARNING:root:FileEntry: unexpected storage type 5

GSHK                    512 5/B3 RW-BND 92-09-08T00:46 92-10-10T15:11   236 @ 1921


This project uses uv and a virtual env in .venv/  (`uv sync` installs the dev tools)

Note: When using Claude Code, add /opt/homebrew/bin to the PATH in your shell environment to access uv.

After activating the venv you can run the same checks as CI:
`ruff check src tests`, `pyright` (strict for src/) and `pytest`.
You can also run the CLI tool using prodos ...

The project emulates the Apple // ProDOS filesystem
and its data structures so those must remain compatible with ProDOS disk images.  This spec is useful background https://prodos8.com/docs/techref/file-organization/
Part of the goal is a clean, comprehensible implementation that explains how ProDOS works,
so keep things simple and keep names consistent with the glossary in metadata.py.

The source files are in src/prodos with a simple
CLI defined in src/prodos/cli.py.
The CLI should not implement complex logic, that should remain in the core files.
- device.py: BlockDevice reads and writes the blocks defined in blocks.py,
  with an access log to watch how the higher level routines are using the device.
- bitmap.py: the volume bit map, which owns block allocation.
- metadata.py: on-disk directory records (headers and file entries), mirroring the spec.
- file.py: Fork (seedling/sapling/tree storage) and File (an entry plus its forks).
- directory.py: Directory, a chain of blocks with fixed entry slots that are never compacted.
- volume.py: Volume ties these together; use it as a context manager so the bit map is flushed.
- check.py: volume integrity checks.

Raise ProDOSError for user-facing failures; use assert only for internal invariants.

Every disk image a test leaves in tmp_path is checked with check_volume after the test
(see tests/conftest.py); mark tests that deliberately leave damaged images with
@pytest.mark.skip_volume_check.

Put imports at the top of source files, don't
import within functions unless you have a specific need to do so.

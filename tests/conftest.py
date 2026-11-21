from collections.abc import Iterator
from pathlib import Path

import pytest

from prodos.check import check_volume
from prodos.metadata import FileEntry
from prodos.volume import Volume

ROOT = Path(__file__).parent.parent
IMAGES = ROOT / "images"
image_suffixes = {'.po', '.2mg', '.dsk'}


def pytest_configure(config: pytest.Config):
    config.addinivalue_line(
        "markers", "skip_volume_check: the test leaves damaged or non-ProDOS images in tmp_path")


@pytest.fixture(autouse=True)
def run_from_repo_root(monkeypatch: pytest.MonkeyPatch):
    """Tests refer to images/... relative to the repo root"""
    monkeypatch.chdir(ROOT)


@pytest.fixture(autouse=True)
def check_volumes_after(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[None]:
    """Every disk image a test leaves in tmp_path must pass check_volume"""
    yield
    if request.node.get_closest_marker('skip_volume_check'):
        return
    for p in sorted(tmp_path.rglob('*')):
        if p.suffix.lower() in image_suffixes and p.is_file():
            with Volume.open(p) as volume:
                problems = check_volume(volume)
            assert not problems, f"{p.name} failed check:\n" + "\n".join(problems)


@pytest.fixture
def volume(tmp_path: Path) -> Iterator[Volume]:
    """An empty 800K volume open for writing"""
    with Volume.create(tmp_path / "test.po", "TEST", total_blocks=1600) as v:
        yield v


def write(volume: Volume, path: str, data: bytes, file_type: int = 0x06) -> FileEntry:
    """Write a file at a path like /DIR/NAME"""
    parent, name = path.rsplit('/', 1)
    entry = volume.path_entry(parent or '/')
    assert entry
    return volume.read_directory(entry).write_file(FileEntry.new(name, file_type=file_type), data)

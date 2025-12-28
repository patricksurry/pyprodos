"""Python implementation of Apple ProDOS 8 file system."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pyprodos")
except PackageNotFoundError:
    # Package is not installed, fallback to reading VERSION file
    from pathlib import Path
    _version_file = Path(__file__).parent.parent.parent / "VERSION"
    __version__ = _version_file.read_text().strip()

__all__ = ["__version__"]

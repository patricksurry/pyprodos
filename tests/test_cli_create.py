from pathlib import Path
from typer.testing import CliRunner

from p8cli import app


runner = CliRunner(catch_exceptions=False)


def test_create_2mg(tmp_path: Path):
    vol = tmp_path / "newvol.2mg"
    result = runner.invoke(app, ["create", str(vol), "--name", "floppy", "--size", "140", "--format", "2mg"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["info", str(vol)])
    assert result.exit_code == 0
    assert "FLOPPY" in result.stdout
    assert f"{140 - 2 - 4 - 1} free" in result.stdout
    assert vol.stat().st_size == 140*512 + 64


def test_create_with_loader(tmp_path: Path):
    """Test creating a volume with a boot loader"""
    vol = tmp_path / "boot.po"
    loader = "images/bootloader.bin"

    # Create volume with loader
    result = runner.invoke(app, ["create", str(vol), "-n", "BOOT", "-l", loader])
    assert result.exit_code == 0

    # Verify volume was created
    result = runner.invoke(app, ["info", str(vol)])
    assert result.exit_code == 0
    assert "BOOT" in result.stdout


def test_bootloader_roundtrip(tmp_path: Path):
    """Test that we can write and read back a boot loader correctly"""
    vol = tmp_path / "boot.po"
    loader_original = "images/bootloader.bin"
    loader_exported = tmp_path / "exported_loader.bin"

    # Create volume with loader
    result = runner.invoke(app, ["create", str(vol), "-l", loader_original])
    assert result.exit_code == 0

    # Export the loader
    result = runner.invoke(app, ["export", str(vol), "--loader", str(loader_exported)])
    assert result.exit_code == 0
    assert loader_exported.exists()

    # Compare original and exported loaders
    original_data = open(loader_original, 'rb').read()
    exported_data = loader_exported.read_bytes()

    # Exported should be exactly 1024 bytes (2 blocks)
    assert len(exported_data) == 1024

    # Original might be shorter and padded, so compare the original length
    assert exported_data[:len(original_data)] == original_data

    # Remaining bytes should be zero padding
    if len(original_data) < 1024:
        assert exported_data[len(original_data):] == bytes(1024 - len(original_data))

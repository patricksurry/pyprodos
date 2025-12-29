from pathlib import Path

from typer.testing import CliRunner

from prodos.cli import app

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
    """Test creating a volume and importing a boot loader"""
    vol = tmp_path / "boot.po"
    loader = "images/bootloader.bin"

    # Create volume
    result = runner.invoke(app, ["create", str(vol), "-n", "BOOT"])
    assert result.exit_code == 0

    # Import loader
    result = runner.invoke(app, ["import", str(vol), "-l", loader, "/"])
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

    # Create volume
    result = runner.invoke(app, ["create", str(vol)])
    assert result.exit_code == 0

    # Import loader
    result = runner.invoke(app, ["import", str(vol), "-l", loader_original, "/"])
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


def test_export_files_and_loader(tmp_path: Path):
    """Test exporting files and loader in a single command"""
    vol = tmp_path / "boot.po"
    loader_file = "images/bootloader.bin"

    # Create volume
    result = runner.invoke(app, ["create", str(vol)])
    assert result.exit_code == 0

    # Import loader and some test files
    test_file1 = tmp_path / "test1.txt"
    test_file2 = tmp_path / "test2.txt"
    test_file1.write_text("Test content 1")
    test_file2.write_text("Test content 2")

    result = runner.invoke(app, ["import", str(vol), "-l", loader_file, str(test_file1), str(test_file2), "/"])
    assert result.exit_code == 0

    # Export files and loader in one command
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    loader_exported = tmp_path / "exported.bin"

    result = runner.invoke(app, [
        "export", str(vol),
        "/TEST1.TXT", "/TEST2.TXT",
        str(export_dir),
        "--loader", str(loader_exported)
    ])
    assert result.exit_code == 0

    # Verify files were exported
    assert (export_dir / "TEST1.TXT").exists()
    assert (export_dir / "TEST2.TXT").exists()
    assert (export_dir / "TEST1.TXT").read_text() == "Test content 1"
    assert (export_dir / "TEST2.TXT").read_text() == "Test content 2"

    # Verify loader was exported
    assert loader_exported.exists()
    assert len(loader_exported.read_bytes()) == 1024

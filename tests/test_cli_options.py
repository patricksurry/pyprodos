from pathlib import Path
from typer.testing import CliRunner
import pytest

from p8cli import app


runner = CliRunner(catch_exceptions=False)


@pytest.fixture
def vol_with_file(tmp_path: Path) -> Path:
    vol_path = tmp_path / "test.dsk"

    # Setup: Create volume and a file
    runner.invoke(app, ["create", str(vol_path)])

    # Create a dummy file to import
    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("HELLO WORLD")

    # Import file as /HELLO
    runner.invoke(app, ["import", str(vol_path), str(dummy_file), "/HELLO"])
    return vol_path


def test_create_short_options(tmp_path: Path):
    """Test create command with short form options"""
    vol = tmp_path / "newvol.po"
    result = runner.invoke(app, ["create", str(vol), "-n", "DISK", "-s", "280"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["info", str(vol)])
    assert result.exit_code == 0
    assert "DISK" in result.stdout


def test_create_force_flag(tmp_path: Path):
    """Test create --force overwrites existing volume"""
    vol = tmp_path / "newvol.po"

    # Create initial volume
    result = runner.invoke(app, ["create", str(vol), "-n", "FIRST"])
    assert result.exit_code == 0

    # Try to create again without force - should fail
    result = runner.invoke(app, ["create", str(vol), "-n", "SECOND"])
    assert result.exit_code == 5
    assert "exists" in result.stdout

    # Verify still has FIRST
    result = runner.invoke(app, ["info", str(vol)])
    assert "FIRST" in result.stdout

    # Create with force - should succeed
    result = runner.invoke(app, ["create", str(vol), "-n", "SECOND", "-f"])
    assert result.exit_code == 0

    # Verify now has SECOND
    result = runner.invoke(app, ["info", str(vol)])
    assert "SECOND" in result.stdout
    assert "FIRST" not in result.stdout


def test_import_without_force_fails(tmp_path: Path, vol_with_file: Path):
    """Test import fails when file exists without --force"""
    dummy_file = tmp_path / "new.txt"
    dummy_file.write_text("NEW CONTENT")

    # Try to import over existing file without force
    result = runner.invoke(app, ["import", str(vol_with_file), str(dummy_file), "/HELLO"])
    assert result.exit_code == 5
    assert "exists" in result.stdout

    # Verify original content is unchanged
    export_path = tmp_path / "exported.txt"
    runner.invoke(app, ["export", str(vol_with_file), "/HELLO", str(export_path)])
    assert export_path.read_text() == "HELLO WORLD"


def test_import_with_force_overwrites(tmp_path: Path, vol_with_file: Path):
    """Test import with --force overwrites existing file"""
    dummy_file = tmp_path / "new.txt"
    dummy_file.write_text("NEW CONTENT")

    # Import with force should succeed
    result = runner.invoke(app, ["import", str(vol_with_file), str(dummy_file), "/HELLO", "-f"])
    assert result.exit_code == 0

    # Verify new content
    export_path = tmp_path / "exported.txt"
    runner.invoke(app, ["export", str(vol_with_file), "/HELLO", str(export_path)])
    assert export_path.read_text() == "NEW CONTENT"


def test_import_short_option_force(tmp_path: Path, vol_with_file: Path):
    """Test import with -f short option"""
    dummy_file = tmp_path / "new.txt"
    dummy_file.write_text("FORCED CONTENT")

    # Use -f short form
    result = runner.invoke(app, ["import", str(vol_with_file), str(dummy_file), "/HELLO", "-f"])
    assert result.exit_code == 0

    export_path = tmp_path / "exported.txt"
    runner.invoke(app, ["export", str(vol_with_file), "/HELLO", str(export_path)])
    assert export_path.read_text() == "FORCED CONTENT"


def test_output_option_creates_copy(tmp_path: Path, vol_with_file: Path):
    """Test --output creates a copy instead of modifying original"""
    output_vol = tmp_path / "output.dsk"
    dummy_file = tmp_path / "new.txt"
    dummy_file.write_text("NEW FILE")

    # Import to output volume
    result = runner.invoke(app, ["import", str(vol_with_file), str(dummy_file), "/NEWFILE", "-o", str(output_vol)])
    assert result.exit_code == 0

    # Check original doesn't have NEWFILE
    result = runner.invoke(app, ["ls", str(vol_with_file)])
    assert "NEWFILE" not in result.stdout

    # Check output has NEWFILE
    result = runner.invoke(app, ["ls", str(output_vol)])
    assert "NEWFILE" in result.stdout


def test_ls_recursive_short_option(tmp_path: Path):
    """Test ls -r recursive option"""
    vol = tmp_path / "test.dsk"
    runner.invoke(app, ["create", str(vol)])
    runner.invoke(app, ["mkdir", str(vol), "/DIR"])
    runner.invoke(app, ["mkdir", str(vol), "/DIR/SUBDIR"])

    # Without recursive
    result = runner.invoke(app, ["ls", str(vol), "/"])
    assert "DIR/" in result.stdout
    assert "SUBDIR/" not in result.stdout

    # With -r
    result = runner.invoke(app, ["ls", str(vol), "/", "-r"])
    assert "DIR/" in result.stdout
    assert "SUBDIR/" in result.stdout


def test_mv_with_output_option(tmp_path: Path, vol_with_file: Path):
    """Test mv with -o option"""
    output_vol = tmp_path / "output.dsk"

    # Move file in output volume
    result = runner.invoke(app, ["mv", str(vol_with_file), "/HELLO", "/MOVED", "-o", str(output_vol)])
    assert result.exit_code == 0

    # Original should still have HELLO
    result = runner.invoke(app, ["ls", str(vol_with_file)])
    assert "HELLO" in result.stdout

    # Output should have MOVED
    result = runner.invoke(app, ["ls", str(output_vol)])
    assert "MOVED" in result.stdout
    assert "HELLO" not in result.stdout

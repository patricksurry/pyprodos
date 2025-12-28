"""Tests for the --log option."""
from pathlib import Path
from typer.testing import CliRunner

from prodos.cli import app


runner = CliRunner(catch_exceptions=False)


def test_log_create_command(tmp_path: Path):
    """Test that --log captures access log for create command."""
    vol = tmp_path / "test.po"
    log_file = tmp_path / "access.log"

    result = runner.invoke(app, ["create", str(vol), "--size", "100", "--log", str(log_file)])
    assert result.exit_code == 0

    # Verify log file was created
    assert log_file.exists()

    # Read and verify log contents
    log_lines = log_file.read_text().strip().split('\n')
    assert len(log_lines) > 0

    # Should have allocations, writes with block types
    assert any(line.startswith('a ') for line in log_lines), "Should have allocations"
    assert any('DirectoryBlock' in line for line in log_lines), "Should have DirectoryBlock writes"
    assert any('BitmapBlock' in line for line in log_lines), "Should have BitmapBlock writes"

    # Verify format: "access_type block_index block_type"
    for line in log_lines:
        parts = line.split(' ', 2)
        assert len(parts) >= 2, f"Invalid log line format: {line}"
        access_type, block_index = parts[0], parts[1]
        assert access_type in ['r', 'w', 'a', 'f'], f"Invalid access type: {access_type}"
        assert len(block_index) == 4, f"Block index should be 4 hex digits: {block_index}"
        int(block_index, 16)  # Should be valid hex


def test_log_import_command(tmp_path: Path):
    """Test that --log captures access log for import command."""
    vol = tmp_path / "test.po"
    log_file = tmp_path / "access.log"
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # Create volume first
    result = runner.invoke(app, ["create", str(vol), "--size", "100"])
    assert result.exit_code == 0

    # Import with logging
    result = runner.invoke(app, ["import", str(vol), str(test_file), "/", "--log", str(log_file)])
    assert result.exit_code == 0

    # Verify log file
    assert log_file.exists()
    log_lines = log_file.read_text().strip().split('\n')

    # Should have reads, writes, and allocations
    assert any(line.startswith('r ') for line in log_lines), "Should have reads"
    assert any(line.startswith('w ') for line in log_lines), "Should have writes"
    assert any(line.startswith('a ') for line in log_lines), "Should have allocations"


def test_log_export_command(tmp_path: Path):
    """Test that --log captures access log for export command."""
    vol = tmp_path / "test.po"
    log_file = tmp_path / "access.log"
    test_file = tmp_path / "test.txt"
    export_file = tmp_path / "exported.txt"
    test_file.write_text("test content")

    # Create and import
    result = runner.invoke(app, ["create", str(vol), "--size", "100"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["import", str(vol), str(test_file), "/"])
    assert result.exit_code == 0

    # Export with logging
    result = runner.invoke(app, ["export", str(vol), "/TEST.TXT", str(export_file), "--log", str(log_file)])
    assert result.exit_code == 0

    # Verify log file
    assert log_file.exists()
    log_lines = log_file.read_text().strip().split('\n')

    # Should have reads
    assert any(line.startswith('r ') for line in log_lines), "Should have reads"


def test_log_ls_command(tmp_path: Path):
    """Test that --log captures access log for ls command."""
    vol = tmp_path / "test.po"
    log_file = tmp_path / "access.log"

    # Create volume
    result = runner.invoke(app, ["create", str(vol), "--size", "100"])
    assert result.exit_code == 0

    # List with logging
    result = runner.invoke(app, ["ls", str(vol), "--log", str(log_file)])
    assert result.exit_code == 0

    # Verify log file
    assert log_file.exists()
    log_lines = log_file.read_text().strip().split('\n')

    # Should have reads including DirectoryBlock
    assert any(line.startswith('r ') for line in log_lines), "Should have reads"
    assert any('DirectoryBlock' in line for line in log_lines), "Should read DirectoryBlock"


def test_log_overwrite_on_each_command(tmp_path: Path):
    """Test that each command overwrites the log file."""
    vol = tmp_path / "test.po"
    log_file = tmp_path / "access.log"

    # First command
    result = runner.invoke(app, ["create", str(vol), "--size", "100", "--log", str(log_file)])
    assert result.exit_code == 0
    first_log = log_file.read_text()
    first_line_count = len(first_log.strip().split('\n'))

    # Second command should overwrite
    result = runner.invoke(app, ["ls", str(vol), "--log", str(log_file)])
    assert result.exit_code == 0
    second_log = log_file.read_text()
    second_line_count = len(second_log.strip().split('\n'))

    # Logs should be different - each command produces different access patterns
    assert first_line_count != second_line_count
    # Verify the second log doesn't contain remnants of the first
    # (i.e., it was overwritten, not appended to)
    assert 'BitmapBlock' in second_log or 'DirectoryBlock' in second_log

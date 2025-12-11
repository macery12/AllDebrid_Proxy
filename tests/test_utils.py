"""Tests for utility functions."""

import pytest
import tempfile
import os
from app.utils import parse_infohash, ensure_task_dirs, disk_free_bytes, append_log, write_metadata


class TestParseInfohash:
    """Tests for parse_infohash function."""
    
    def test_valid_hex_infohash(self):
        """Test parsing valid hex infohash."""
        magnet = "magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678"
        result = parse_infohash(magnet)
        assert result == "1234567890abcdef1234567890abcdef12345678"
    
    def test_valid_base32_infohash(self):
        """Test parsing valid base32 infohash."""
        magnet = "magnet:?xt=urn:btih:MFRGG2DFMZTWQ3DBNZ2HK4BAMFRGG2DF"
        result = parse_infohash(magnet)
        assert result is not None
        assert len(result) == 32
    
    def test_invalid_magnet(self):
        """Test parsing invalid magnet link."""
        magnet = "not-a-magnet-link"
        result = parse_infohash(magnet)
        assert result is None
    
    def test_empty_string(self):
        """Test parsing empty string."""
        result = parse_infohash("")
        assert result is None
    
    def test_magnet_with_multiple_params(self):
        """Test parsing magnet with additional parameters."""
        magnet = "magnet:?xt=urn:btih:ABC123&dn=test&tr=http://tracker.com"
        result = parse_infohash(magnet)
        # Should still extract the infohash
        assert result is not None


class TestEnsureTaskDirs:
    """Tests for ensure_task_dirs function."""
    
    def test_creates_directories(self):
        """Test that directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base, files = ensure_task_dirs(tmpdir, task_id)
            
            assert os.path.exists(base)
            assert os.path.exists(files)
            assert os.path.isdir(base)
            assert os.path.isdir(files)
    
    def test_creates_metadata_files(self):
        """Test that metadata files are initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base, files = ensure_task_dirs(tmpdir, task_id)
            
            metadata_path = os.path.join(base, "metadata.json")
            logs_path = os.path.join(base, "logs.json")
            
            assert os.path.exists(metadata_path)
            assert os.path.exists(logs_path)
    
    def test_idempotent(self):
        """Test that calling multiple times is safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base1, files1 = ensure_task_dirs(tmpdir, task_id)
            base2, files2 = ensure_task_dirs(tmpdir, task_id)
            
            assert base1 == base2
            assert files1 == files2


class TestDiskFreeBytes:
    """Tests for disk_free_bytes function."""
    
    def test_returns_positive_number(self):
        """Test that it returns a positive number."""
        with tempfile.TemporaryDirectory() as tmpdir:
            free = disk_free_bytes(tmpdir)
            assert isinstance(free, int)
            assert free > 0
    
    def test_invalid_path(self):
        """Test with invalid path."""
        with pytest.raises(OSError):
            disk_free_bytes("/nonexistent/path/that/does/not/exist")


class TestAppendLog:
    """Tests for append_log function."""
    
    def test_appends_log_entry(self):
        """Test that log entry is appended."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base, _ = ensure_task_dirs(tmpdir, task_id)
            
            entry = {"level": "info", "event": "test_event", "data": "test_data"}
            append_log(base, entry)
            
            logs_path = os.path.join(base, "logs.json")
            with open(logs_path, "r") as f:
                content = f.read()
            
            assert "test_event" in content
            assert "test_data" in content
    
    def test_adds_timestamp(self):
        """Test that timestamp is added if not present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base, _ = ensure_task_dirs(tmpdir, task_id)
            
            entry = {"level": "info", "event": "test"}
            append_log(base, entry)
            
            logs_path = os.path.join(base, "logs.json")
            with open(logs_path, "r") as f:
                content = f.read()
            
            assert "ts" in content


class TestWriteMetadata:
    """Tests for write_metadata function."""
    
    def test_writes_metadata(self):
        """Test that metadata is written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base, _ = ensure_task_dirs(tmpdir, task_id)
            
            data = {"taskId": task_id, "status": "queued", "mode": "auto"}
            write_metadata(base, data)
            
            metadata_path = os.path.join(base, "metadata.json")
            with open(metadata_path, "r") as f:
                content = f.read()
            
            assert task_id in content
            assert "queued" in content
    
    def test_overwrites_existing(self):
        """Test that existing metadata is overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_id = "test-task-123"
            base, _ = ensure_task_dirs(tmpdir, task_id)
            
            # Write first time
            data1 = {"status": "queued"}
            write_metadata(base, data1)
            
            # Write second time
            data2 = {"status": "downloading"}
            write_metadata(base, data2)
            
            metadata_path = os.path.join(base, "metadata.json")
            with open(metadata_path, "r") as f:
                content = f.read()
            
            assert "downloading" in content
            assert "queued" not in content

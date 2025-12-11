"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError
from app.schemas import CreateTaskRequest, FileItem, StorageInfo, TaskResponse, SelectRequest


class TestCreateTaskRequest:
    """Tests for CreateTaskRequest schema."""
    
    def test_valid_auto_mode(self):
        """Test valid request with auto mode."""
        data = {
            "mode": "auto",
            "source": "magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678",
            "label": "Test Download"
        }
        request = CreateTaskRequest(**data)
        assert request.mode == "auto"
        assert request.source.startswith("magnet:")
        assert request.label == "Test Download"
    
    def test_valid_select_mode(self):
        """Test valid request with select mode."""
        data = {
            "mode": "select",
            "source": "magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678"
        }
        request = CreateTaskRequest(**data)
        assert request.mode == "select"
        assert request.label is None
    
    def test_invalid_mode(self):
        """Test that invalid mode raises error."""
        data = {
            "mode": "invalid",
            "source": "magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678"
        }
        with pytest.raises(ValidationError) as exc_info:
            CreateTaskRequest(**data)
        assert "mode" in str(exc_info.value)
    
    def test_non_magnet_source(self):
        """Test that non-magnet source raises error."""
        data = {
            "mode": "auto",
            "source": "http://example.com/file.torrent"
        }
        with pytest.raises(ValidationError) as exc_info:
            CreateTaskRequest(**data)
        assert "magnet" in str(exc_info.value).lower()
    
    def test_short_magnet_link(self):
        """Test that very short magnet link raises error."""
        data = {
            "mode": "auto",
            "source": "magnet:?xt=urn:btih:"
        }
        with pytest.raises(ValidationError) as exc_info:
            CreateTaskRequest(**data)
        assert "too short" in str(exc_info.value).lower()
    
    def test_source_too_long(self):
        """Test that overly long source raises error."""
        data = {
            "mode": "auto",
            "source": "magnet:?xt=urn:btih:" + "A" * 10000
        }
        with pytest.raises(ValidationError):
            CreateTaskRequest(**data)
    
    def test_label_too_long(self):
        """Test that overly long label raises error."""
        data = {
            "mode": "auto",
            "source": "magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678",
            "label": "A" * 201
        }
        with pytest.raises(ValidationError):
            CreateTaskRequest(**data)


class TestFileItem:
    """Tests for FileItem schema."""
    
    def test_valid_file_item(self):
        """Test valid file item."""
        data = {
            "fileId": "file-123",
            "index": 0,
            "name": "test.mkv",
            "size": 1073741824,
            "state": "downloading",
            "bytesDownloaded": 536870912,
            "localPath": "/srv/storage/task/files/test.mkv"
        }
        item = FileItem(**data)
        assert item.fileId == "file-123"
        assert item.size == 1073741824
        assert item.bytesDownloaded == 536870912


class TestStorageInfo:
    """Tests for StorageInfo schema."""
    
    def test_valid_storage_info(self):
        """Test valid storage info."""
        data = {
            "freeBytes": 10737418240,
            "taskTotalSize": 2147483648,
            "taskReservedBytes": 1073741824,
            "globalReservedBytes": 5368709120,
            "lowSpaceFloorBytes": 10737418240
        }
        info = StorageInfo(**data)
        assert info.freeBytes == 10737418240
        assert info.taskTotalSize == 2147483648


class TestSelectRequest:
    """Tests for SelectRequest schema."""
    
    def test_valid_select_request(self):
        """Test valid select request."""
        data = {
            "fileIds": ["file-1", "file-2", "file-3"]
        }
        request = SelectRequest(**data)
        assert len(request.fileIds) == 3
    
    def test_empty_file_ids(self):
        """Test select request with empty list."""
        data = {"fileIds": []}
        request = SelectRequest(**data)
        assert request.fileIds == []

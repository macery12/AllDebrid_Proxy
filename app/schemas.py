from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

class CreateTaskRequest(BaseModel):
    """Request model for creating a new download task."""
    
    mode: str = Field(pattern="^(auto|select)$", description="Download mode: 'auto' downloads all files, 'select' waits for user selection")
    source: str = Field(max_length=10000, description="Magnet link (must start with 'magnet:')")
    label: Optional[str] = Field(None, max_length=200, description="Optional human-readable label for the task")
    
    @field_validator('source')
    @classmethod
    def validate_magnet_link(cls, v: str) -> str:
        """Validate that source is a magnet link."""
        if not v.startswith('magnet:'):
            raise ValueError('Source must be a magnet link (starting with "magnet:")')
        if len(v) < 20:
            raise ValueError('Magnet link appears to be too short or invalid')
        return v

class FileItem(BaseModel):
    fileId: str
    index: int
    name: str
    size: Optional[int] = None
    state: str
    bytesDownloaded: int = 0
    localPath: Optional[str] = None

class StorageInfo(BaseModel):
    freeBytes: int
    taskTotalSize: int
    taskReservedBytes: int
    globalReservedBytes: int
    lowSpaceFloorBytes: int
    willStartWhenFreeBytesAtLeast: Optional[int] = None

class TaskResponse(BaseModel):
    taskId: str
    mode: str
    status: str
    label: Optional[str] = None
    infohash: str
    files: List[FileItem] = []
    storage: Optional[StorageInfo] = None

class SelectRequest(BaseModel):
    fileIds: List[str]

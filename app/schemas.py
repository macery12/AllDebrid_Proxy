from pydantic import BaseModel, Field
from typing import List, Optional

class CreateTaskRequest(BaseModel):
    mode: str = Field(pattern="^(auto|select)$")
    source: str
    label: Optional[str] = None
    user_id: Optional[int] = None  # User ID for tracking

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

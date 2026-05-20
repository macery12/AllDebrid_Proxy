from pydantic import BaseModel, Field
from typing import List, Optional

# --- Auth schemas ---

class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False

class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    role: str

class LoginResponse(BaseModel):
    user: Optional[UserOut] = None
    first_time_setup: Optional[bool] = None
    message: Optional[str] = None

# --- Task schemas ---

class CreateTaskRequest(BaseModel):
    mode: str = Field(pattern="^(auto|select)$")
    source: str
    label: Optional[str] = None
    user_id: Optional[int] = None

class FileItem(BaseModel):
    fileId: str
    index: int
    name: str
    size: Optional[int] = None
    state: str
    bytesDownloaded: int = 0
    speedBps: int = 0
    etaSeconds: Optional[int] = None
    progressPct: int = 0
    # localPath intentionally omitted — never expose server filesystem paths

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

# --- User management schemas ---

class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    role: Optional[str] = None

class ResetPasswordRequest(BaseModel):
    password: str

class SetRoleRequest(BaseModel):
    role: str

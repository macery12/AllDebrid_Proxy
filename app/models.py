from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, String, Text, Integer, BigInteger, DateTime, ForeignKey, func, Boolean

Base = declarative_base()

class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    stats = relationship("UserStats", back_populates="user", uselist=False, cascade="all, delete-orphan")

class UserStats(Base):
    __tablename__ = "user_stats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True)
    total_downloads = Column(Integer, nullable=False, default=0)
    total_magnets_processed = Column(Integer, nullable=False, default=0)
    total_bytes_downloaded = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="stats")

class Task(Base):
    __tablename__ = "task"
    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True)  # nullable for migration
    label = Column(Text, nullable=True)
    mode = Column(String(16), nullable=False)  # auto|select
    source = Column(Text, nullable=False)
    infohash = Column(String(40), nullable=False, index=True)  # Allow multiple tasks with same infohash
    provider = Column(String(32), nullable=False, default="alldebrid")
    provider_ref = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="queued")
    progress_pct = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="tasks")
    files = relationship("TaskFile", back_populates="task", cascade="all, delete-orphan")
    events = relationship("TaskEvent", back_populates="task", cascade="all, delete-orphan")

class TaskFile(Base):
    __tablename__ = "task_file"
    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    index = Column(Integer, nullable=False)
    name = Column(Text, nullable=False)
    size_bytes = Column(BigInteger, nullable=True)
    state = Column(String(32), nullable=False, default="listed")  # listed|selected|downloading|done|failed
    bytes_downloaded = Column(BigInteger, nullable=False, default=0)
    local_path = Column(Text, nullable=True)
    unlocked_url = Column(Text, nullable=True)

    task = relationship("Task", back_populates="files")

class TaskEvent(Base):
    __tablename__ = "task_event"
    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    level = Column(String(16), nullable=False)  # info|warn|error|progress
    event = Column(Text, nullable=False)
    payload = Column(Text, nullable=True)  # JSON encoded

    task = relationship("Task", back_populates="events")

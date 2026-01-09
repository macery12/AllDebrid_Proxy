from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, String, Text, Integer, BigInteger, DateTime, ForeignKey, func

Base = declarative_base()

class Task(Base):
    __tablename__ = "task"
    id = Column(String(36), primary_key=True)
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

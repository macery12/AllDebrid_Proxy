from __future__ import annotations
import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base

# Default SQLite file in current working dir
DB_URL = os.getenv("DATABASE_URL", "sqlite:///proxy.db")

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)            # uuid
    client_id = Column(String, nullable=True)
    input_type = Column(String, nullable=False)      # magnet|torrent|url
    source_input = Column(Text, nullable=False)      # magnet string, torrent path, or urls block
    include_trackers = Column(Boolean, default=False)
    status = Column(String, default="queued")
    error = Column(Text, default="")

    # Kept for compatibility with previous code & UI expectations
    sharry_share_id   = Column(String, nullable=True)
    sharry_public_pid = Column(String, nullable=True)
    sharry_public_api = Column(String, nullable=True)
    sharry_public_web = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)

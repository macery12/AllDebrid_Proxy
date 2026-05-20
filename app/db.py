from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

def get_db():
    # FastAPI dependency — yields a DB session and closes it after the request
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

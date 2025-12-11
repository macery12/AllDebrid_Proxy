"""Pytest configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.models import Base
from app.config import Settings

# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def test_settings():
    """Override settings for testing."""
    return Settings(
        WORKER_API_KEY="test-key-12345678",
        ALLDEBRID_API_KEY="test-alldebrid-key",
        DATABASE_URL=TEST_DATABASE_URL,
        REDIS_URL="redis://localhost:6379/15",  # Use different DB for tests
        STORAGE_ROOT="/tmp/test_storage",
        ENVIRONMENT="testing"
    )


@pytest.fixture
def test_db():
    """Create a test database."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers(test_settings):
    """Return authentication headers for API requests."""
    return {"X-Worker-Key": test_settings.WORKER_API_KEY}

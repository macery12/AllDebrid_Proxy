from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import os
import sys

class Settings(BaseSettings):
    """Application settings with validation and security checks."""
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Security: Worker API key with validation
    WORKER_API_KEY: str = Field(default="change-me", min_length=8)

    # AllDebrid configuration
    ALLDEBRID_API_KEY: str = Field(default="")
    ALLDEBRID_AGENT: str = Field(default="alldebrid-proxy")

    # Storage configuration
    STORAGE_ROOT: str = Field(default="/srv/storage")
    LOW_SPACE_FLOOR_GB: int = Field(default=10, ge=1)

    # Worker configuration
    GLOBAL_QUEUE_LIMIT: int = Field(default=25, ge=1)
    PER_TASK_MAX_ACTIVE: int = Field(default=3, ge=1)
    PER_TASK_MAX_QUEUED: int = Field(default=9, ge=1)
    ARIA2_SPLITS: int = Field(default=4, ge=1, le=16)

    # Retention configuration
    RETENTION_DAYS: int = Field(default=7, ge=1)
    PARTIAL_MAX_AGE_HOURS: int = Field(default=24, ge=1)

    # Database configuration
    DATABASE_URL: str = Field(default="postgresql+psycopg2://alldebrid:alldebrid@db:5432/alldebrid")
    REDIS_URL: str = Field(default="redis://redis:6379/0")

    # Optional: Environment detection
    ENVIRONMENT: str = Field(default="development")

    @field_validator('WORKER_API_KEY')
    @classmethod
    def validate_worker_key(cls, v: str) -> str:
        """Ensure WORKER_API_KEY is not using default value in production."""
        if v == "change-me":
            env = os.getenv("ENVIRONMENT", "development")
            if env == "production":
                raise ValueError(
                    "WORKER_API_KEY must be changed from default value in production! "
                    "Set a strong random key in your .env file."
                )
            else:
                print("WARNING: WORKER_API_KEY is using default value. Change it for production!", file=sys.stderr)
        return v

    @field_validator('ALLDEBRID_API_KEY')
    @classmethod
    def validate_alldebrid_key(cls, v: str) -> str:
        """Warn if AllDebrid API key is not set."""
        if not v:
            print("WARNING: ALLDEBRID_API_KEY is not set. The service will not work without it.", file=sys.stderr)
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT.lower() == "production"

settings = Settings()

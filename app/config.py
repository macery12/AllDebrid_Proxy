from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, Field
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Security
    WORKER_API_KEY: str = Field(default="change-me", min_length=8)
    JWT_SECRET: str = Field(default="change-me")
    JWT_EXPIRY_HOURS: int = Field(default=8, ge=1, le=720)
    # Long-lived session when "Remember me" is checked at login
    JWT_REMEMBER_ME_HOURS: int = Field(default=168, ge=1, le=720)  # 7 days

    # AllDebrid provider
    ALLDEBRID_API_KEY: str = Field(default="")
    ALLDEBRID_AGENT: str = Field(default="alldebrid-proxy", min_length=1)

    # Storage
    STORAGE_ROOT: str = Field(default="/srv/storage")
    LOW_SPACE_FLOOR_GB: int = Field(default=10, ge=1, le=1000)

    # Queue and download settings
    GLOBAL_QUEUE_LIMIT: int = Field(default=25, ge=1, le=1000)
    PER_TASK_MAX_ACTIVE: int = Field(default=3, ge=1, le=50)
    PER_TASK_MAX_QUEUED: int = Field(default=9, ge=1, le=100)
    ARIA2_SPLITS: int = Field(default=4, ge=1, le=16)

    # Retention
    RETENTION_DAYS: int = Field(default=7, ge=1, le=365)
    PARTIAL_MAX_AGE_HOURS: int = Field(default=24, ge=1, le=720)

    # Database and cache
    DATABASE_URL: str = Field(default="postgresql+psycopg2://alldebrid:alldebrid@db:5432/alldebrid")
    REDIS_URL: str = Field(default="redis://redis:6379/0")

    # Optional Aria2 RPC settings
    ARIA2_RPC_URL: Optional[str] = Field(default=None)
    ARIA2_RPC_SECRET: Optional[str] = Field(default=None)

    # Scraper runtime data (auth.json, downloaded.json, downloads/) — bind-mounted in production
    SCRAPER_DATA_DIR: str = Field(default="/app/scraper_data")
    # BlueCog source base URL (required — set in .env)
    BLUECOGURL: str = Field()

    @field_validator("WORKER_API_KEY")
    @classmethod
    def validate_worker_api_key(cls, v: str) -> str:
        if v == "change-me":
            import os
            if os.getenv("ENVIRONMENT", "development") == "production":
                raise ValueError("WORKER_API_KEY must be changed from default in production")
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            import os
            if os.getenv("ENVIRONMENT", "development") == "production":
                raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return v

    @field_validator("ALLDEBRID_API_KEY")
    @classmethod
    def validate_alldebrid_key(cls, v: str) -> str:
        if not v:
            import warnings
            warnings.warn("ALLDEBRID_API_KEY is not set - provider operations will fail")
        return v

    @field_validator("DATABASE_URL", "REDIS_URL")
    @classmethod
    def validate_urls(cls, v: str) -> str:
        if not v:
            raise ValueError("Database URL and Redis URL are required")
        return v

settings = Settings()

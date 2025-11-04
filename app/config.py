from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    WORKER_API_KEY: str = "change-me"

    ALLDEBRID_API_KEY: str = ""
    ALLDEBRID_AGENT: str = "alldebrid-proxy"

    STORAGE_ROOT: str = "/srv/storage"
    LOW_SPACE_FLOOR_GB: int = 10

    GLOBAL_QUEUE_LIMIT: int = 25
    PER_TASK_MAX_ACTIVE: int = 3
    PER_TASK_MAX_QUEUED: int = 9
    ARIA2_SPLITS: int = 4

    RETENTION_DAYS: int = 7
    PARTIAL_MAX_AGE_HOURS: int = 24

    DATABASE_URL: str = "postgresql+psycopg2://alldebrid:alldebrid@db:5432/alldebrid"
    REDIS_URL: str = "redis://redis:6379/0"

settings = Settings()

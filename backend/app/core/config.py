from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATABASE_URL = "sqlite:///./data/pc_monitoring.db"


class Settings(BaseSettings):
    APP_NAME: str
    DEBUG: bool
    DATABASE_URL: str | None = None
    DATABASE_ECHO: bool = False
    METRICS_COLLECTION_INTERVAL_SECONDS: int = 10
    LIBRE_HARDWARE_MONITOR_ENABLED: bool = True
    LIBRE_HARDWARE_MONITOR_EXE_PATH: str | None = None
    LIBRE_HARDWARE_MONITOR_AUTO_START: bool = True
    LIBRE_HARDWARE_MONITOR_STARTUP_WAIT_SECONDS: float = 3.0

    @model_validator(mode="after")
    def apply_database_defaults(self) -> "Settings":
        if self.DATABASE_URL is None or not self.DATABASE_URL.strip():
            self.DATABASE_URL = DEFAULT_DATABASE_URL
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

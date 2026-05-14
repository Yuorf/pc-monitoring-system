from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str
    DEBUG: bool
    DATABASE_URL: str
    METRICS_COLLECTION_INTERVAL_SECONDS: int = 10
    LIBRE_HARDWARE_MONITOR_ENABLED: bool = True
    LIBRE_HARDWARE_MONITOR_EXE_PATH: str | None = None
    LIBRE_HARDWARE_MONITOR_AUTO_START: bool = True
    LIBRE_HARDWARE_MONITOR_STARTUP_WAIT_SECONDS: float = 3.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


BACKEND_DIR = Path(__file__).resolve().parents[2]
DATABASE_URL_CONFIGURED = "DATABASE_URL" in settings.model_fields_set


def _build_database_url(database_url: str) -> str:
    if not database_url.startswith("sqlite"):
        return database_url

    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        return database_url

    sqlite_path = database_url[len(sqlite_prefix) :]
    if sqlite_path == ":memory:":
        return database_url

    normalized_path = Path(sqlite_path)
    if not normalized_path.is_absolute():
        sqlite_path = sqlite_path[2:] if sqlite_path.startswith("./") else sqlite_path
        normalized_path = BACKEND_DIR / sqlite_path

    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    return f"{sqlite_prefix}{normalized_path.resolve().as_posix()}"


DATABASE_URL = _build_database_url(settings.DATABASE_URL)
DATABASE_TYPE = "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql"
DATABASE_FILE = None
if DATABASE_TYPE == "sqlite":
    sqlite_prefix = "sqlite:///"
    DATABASE_FILE = DATABASE_URL[len(sqlite_prefix) :]

ENGINE_KWARGS = {"echo": settings.DATABASE_ECHO}
if DATABASE_URL.startswith("sqlite"):
    ENGINE_KWARGS["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **ENGINE_KWARGS)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

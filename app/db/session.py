from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, create_engine

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)


def get_session():
    with Session(engine) as session:
        yield session


def sqlite_database_path() -> Path | None:
    if not settings.database_url.startswith("sqlite:///./"):
        return None
    relative = settings.database_url.removeprefix("sqlite:///./")
    return Path.cwd() / relative


def reset_sqlite_database() -> None:
    database_path = sqlite_database_path()
    if database_path is None:
        return
    engine.dispose()
    if database_path.exists():
        database_path.unlink()

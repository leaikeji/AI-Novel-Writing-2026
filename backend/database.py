"""Database configuration and SQLAlchemy session lifecycle."""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


DATABASE_URL_ENV = "AI_NOVEL_DATABASE_URL"


class DatabaseNotConfigured(RuntimeError):
    """Raised when the PawApp database URL has not been configured."""


def get_database_url() -> str:
    value = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not value:
        raise DatabaseNotConfigured(f"{DATABASE_URL_ENV} is not configured")
    return value


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def get_session() -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session


def database_status() -> dict[str, object]:
    try:
        with get_engine().connect() as connection:
            version = connection.execute(text("select current_setting('server_version')"))
            return {"connected": True, "postgres_version": version.scalar_one()}
    except Exception as error:  # Database failures must not stop QwenPaw.
        return {
            "connected": False,
            "error": f"{type(error).__name__}: {error}",
        }


def reset_engine_for_tests() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()

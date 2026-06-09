"""SQLAlchemy engine / session factory.

The engine is created from ``DATABASE_URL`` only — pointing it at Postgres
instead of SQLite is purely a configuration change. SQLite needs one extra
connect arg for multi-threaded use (the scheduler runs on a separate thread).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def create_db_engine(database_url: str) -> Engine:
    """Build an engine appropriate for the configured database backend."""
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        # Allow the engine to be shared across threads (API + scheduler).
        connect_args = {"check_same_thread": False}
    return create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured ``sessionmaker`` bound to ``engine``."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables. Import models first so they register on ``Base``."""
    from app.database import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=engine)

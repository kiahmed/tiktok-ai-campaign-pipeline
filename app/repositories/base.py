"""Base repository: owns a session factory and a transactional helper.

Repositories encapsulate all persistence. The service layer never touches a
SQLAlchemy session directly — it asks a repository, which opens a short-lived
session, commits, and returns detached ORM objects.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker


class BaseRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _unit_of_work(self) -> Iterator[Session]:
        """Yield a session inside a transaction; commit on success, rollback on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

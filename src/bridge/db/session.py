"""Engine and session management."""

from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import DB_PATH, ensure_dirs
from .models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _database_url() -> str:
    if url := os.environ.get("BRIDGE_DB_URL"):
        return url
    ensure_dirs()
    return f"sqlite:///{DB_PATH}"


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    url = _database_url()
    _engine = create_engine(url, future=True, pool_pre_ping=True)

    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(drop: bool = False) -> None:
    engine = get_engine()
    if drop:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Initialise the Bridge warehouse.")
    parser.add_argument("--drop", action="store_true", help="drop existing tables first")
    args = parser.parse_args()
    init_db(drop=args.drop)
    print(f"Initialised database at {_database_url()}")

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.repositories.models import Base


def build_engine(database_url: str):
    if not database_url.startswith("sqlite"):
        return create_engine(database_url, future=True)
    kwargs = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or database_url == "sqlite://":
        # One shared connection, otherwise every caller gets its own empty database.
        kwargs["poolclass"] = StaticPool
    return create_engine(database_url, future=True, **kwargs)


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

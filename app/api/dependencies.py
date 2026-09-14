from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.providers.base import ExtractionProvider
from app.repositories.session import session_scope


def get_session(request: Request) -> Iterator[Session]:
    with session_scope(request.app.state.session_factory) as session:
        yield session


def get_provider(request: Request) -> ExtractionProvider:
    return request.app.state.provider

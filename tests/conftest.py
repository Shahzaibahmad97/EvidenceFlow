from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.providers.fake import FakeProvider
from app.repositories.session import build_session_factory

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "invoices"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        provider="fake",
        openai_model="unused",
        request_timeout_seconds=1.0,
    )


@pytest.fixture
def session_factory(settings: Settings):
    return build_session_factory(settings)


@pytest.fixture
def session(session_factory) -> Session:
    with session_factory() as session:
        yield session


@pytest.fixture
def fixtures() -> "Fixtures":
    return Fixtures(FIXTURE_DIR)


class Fixtures:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def text(self, name: str) -> str:
        return (self._dir / f"{name}.txt").read_text()

    def payload(self, name: str) -> dict[str, Any]:
        return json.loads((self._dir / f"{name}.json").read_text())

    def provider(self, name: str, **kwargs: Any) -> FakeProvider:
        return FakeProvider.returning(self.payload(name), **kwargs)

    @property
    def directory(self) -> Path:
        return self._dir

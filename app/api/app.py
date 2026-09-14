from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings
from app.providers.base import ExtractionProvider
from app.providers.fake import FakeProvider
from app.repositories.session import build_session_factory

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "invoices"


def build_provider(settings: Settings) -> ExtractionProvider:
    if settings.provider == "openai":
        from openai import OpenAI

        from app.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            OpenAI(), settings.openai_model, timeout_seconds=settings.request_timeout_seconds
        )
    return FakeProvider.from_fixtures(FIXTURE_DIR)


def create_app(
    settings: Settings | None = None, provider: ExtractionProvider | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="EvidenceFlow", version="0.1.0")
    app.state.settings = settings
    app.state.session_factory = build_session_factory(settings)
    app.state.provider = provider or build_provider(settings)
    app.include_router(router)
    return app

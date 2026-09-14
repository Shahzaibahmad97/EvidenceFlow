from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings
from app.providers.base import ExtractionProvider
from app.providers.crm import CrmClient, MockCrm
from app.providers.fake import FakeProvider
from app.repositories.session import build_session_factory
from app.workflows.worker import Worker, run_in_background

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
FIXTURE_DIRS = (FIXTURES / "invoices", FIXTURES / "held_out")


def build_provider(settings: Settings) -> ExtractionProvider:
    if settings.provider == "openai":
        from openai import OpenAI

        from app.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            OpenAI(), settings.openai_model, timeout_seconds=settings.request_timeout_seconds
        )
    return FakeProvider.from_fixtures(*FIXTURE_DIRS)


def create_app(
    settings: Settings | None = None,
    provider: ExtractionProvider | None = None,
    crm: CrmClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="EvidenceFlow", version="0.1.0", lifespan=_lifespan)
    app.state.settings = settings
    app.state.session_factory = build_session_factory(settings)
    app.state.provider = provider or build_provider(settings)
    app.state.crm = crm or MockCrm()
    app.state.worker = Worker(
        session_factory=app.state.session_factory,
        provider=app.state.provider,
        crm=app.state.crm,
    )
    app.include_router(router)
    return app


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not app.state.settings.run_worker:
        yield
        return
    _, stop = run_in_background(app.state.worker)
    try:
        yield
    finally:
        stop.set()

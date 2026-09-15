from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.limits import MAX_BODY_BYTES
from app.providers.crm import MockCrm
from app.providers.fake import FakeProvider
from app.repositories import documents as repo
from app.repositories.session import build_session_factory, session_scope
from app.repositories.models import Job
from app.seed import seed_documents
from app.workflows import queue
from app.workflows.worker import wait_for


def build(settings, fixtures, tmp_path, **overrides) -> TestClient:
    configured = replace(
        settings, database_url=f"sqlite:///{tmp_path / 'seed.db'}", **overrides
    )
    app = create_app(
        configured, provider=FakeProvider.from_fixtures(*configured.fixture_dirs), crm=MockCrm()
    )
    return TestClient(app)


def test_seeding_loads_every_fixture_once(settings, tmp_path):
    factory = build_session_factory(
        replace(settings, database_url=f"sqlite:///{tmp_path / 'seed.db'}")
    )

    first = seed_documents(factory, settings.fixture_dirs)
    second = seed_documents(factory, settings.fixture_dirs)

    assert first == 30
    assert second == 0
    with session_scope(factory) as session:
        assert len(repo.list_documents(session)) == 30


def test_the_app_seeds_on_start_when_asked(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path, seed_on_start=True) as client:
        assert client.get("/review").text.count('href="/review/') == 30


def test_seeding_queues_every_document_for_extraction(settings, tmp_path):
    factory = build_session_factory(
        replace(settings, database_url=f"sqlite:///{tmp_path / 'seed.db'}")
    )
    seed_documents(factory, settings.fixture_dirs)

    with session_scope(factory) as session:
        assert len(queue.review_queue(session)) == 0
        assert session.query(Job).count() == 30


def test_seeding_leaves_duplicate_pairs_for_approval_to_settle(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path, seed_on_start=True, run_worker=True) as client:
        assert wait_for(lambda: "received" not in client.get("/review").text, timeout=20.0)
        rows = {row["filename"]: row["status"] for row in client.get("/documents").json()}

    for pair in (("inv_001_acme.txt", "adv_duplicate_number.txt"), ("h_001_wren.txt", "h_010_redelivered.txt")):
        assert {rows[name] for name in pair} == {"validated"}


def test_a_seeded_app_with_a_worker_processes_everything(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path, seed_on_start=True, run_worker=True) as client:
        assert wait_for(
            lambda: "received" not in client.get("/review").text, timeout=20.0
        )
        page = client.get("/review").text

    assert page.count(">validated<") == 15
    assert page.count(">needs review<") == 13
    assert page.count(">extraction failed<") == 2


def test_the_app_does_not_seed_by_default(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path) as client:
        assert "inv_001_acme" not in client.get("/review").text


def test_an_oversized_body_is_refused(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path) as client:
        response = client.post(
            "/documents", json={"filename": "big.txt", "text": "x" * (MAX_BODY_BYTES + 1)}
        )

    assert response.status_code == 413


def test_reads_are_never_rate_limited(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path) as client:
        assert all(client.get("/health").status_code == 200 for _ in range(200))


def test_writes_are_rate_limited(settings, fixtures, tmp_path):
    with build(settings, fixtures, tmp_path) as client:
        codes = {
            client.post("/documents", json={"filename": "a.txt", "text": "x"}).status_code
            for _ in range(80)
        }

    assert 429 in codes


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json"])
def test_the_public_surface_answers(settings, fixtures, tmp_path, path):
    with build(settings, fixtures, tmp_path) as client:
        assert client.get(path).status_code == 200

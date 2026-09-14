from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.domain.events import DocumentStatus
from app.providers.crm import MockCrm
from app.providers.fake import FakeProvider
from app.workflows.worker import wait_for


@pytest.fixture
def crm() -> MockCrm:
    return MockCrm()


def build_client(settings, fixtures, crm, tmp_path, *, run_worker: bool) -> TestClient:
    configured = replace(
        settings,
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        run_worker=run_worker,
    )
    app = create_app(
        configured, provider=FakeProvider.from_fixtures(fixtures.directory), crm=crm
    )
    return TestClient(app)


def upload(client, fixtures, name="inv_001_acme") -> str:
    return client.post(
        "/documents", json={"filename": f"{name}.txt", "text": fixtures.text(name)}
    ).json()["id"]


def test_enqueueing_returns_a_pending_job(settings, fixtures, crm, tmp_path):
    with build_client(settings, fixtures, crm, tmp_path, run_worker=False) as client:
        document_id = upload(client, fixtures)

        response = client.post(f"/documents/{document_id}/jobs", json={"type": "extract"})

        assert response.status_code == 202
        job = response.json()
        assert job["status"] == "pending"
        assert client.get(f"/jobs/{job['id']}").json()["attempts"] == 0


def test_an_unknown_job_type_is_rejected(settings, fixtures, crm, tmp_path):
    with build_client(settings, fixtures, crm, tmp_path, run_worker=False) as client:
        document_id = upload(client, fixtures)

        response = client.post(f"/documents/{document_id}/jobs", json={"type": "teleport"})

        assert response.status_code == 422


def test_an_unknown_job_is_404(settings, fixtures, crm, tmp_path):
    with build_client(settings, fixtures, crm, tmp_path, run_worker=False) as client:
        assert client.get("/jobs/missing").status_code == 404


def test_the_background_worker_drains_the_queue(settings, fixtures, crm, tmp_path):
    with build_client(settings, fixtures, crm, tmp_path, run_worker=True) as client:
        document_id = upload(client, fixtures)
        job = client.post(f"/documents/{document_id}/jobs", json={"type": "extract"}).json()

        assert wait_for(
            lambda: client.get(f"/jobs/{job['id']}").json()["status"] == "succeeded"
        )
        assert client.get(f"/documents/{document_id}").json()["status"] == (
            DocumentStatus.VALIDATED
        )

        client.post(f"/documents/{document_id}/approve")
        write_job = client.post(f"/documents/{document_id}/jobs", json={"type": "write"}).json()

        assert wait_for(
            lambda: client.get(f"/jobs/{write_job['id']}").json()["status"] == "succeeded"
        )
        assert client.get(f"/documents/{document_id}").json()["status"] == DocumentStatus.WRITTEN
        assert len(crm.records) == 1


def test_a_permanently_failed_job_appears_in_the_review_queue(settings, fixtures, crm, tmp_path):
    with build_client(settings, fixtures, crm, tmp_path, run_worker=True) as client:
        document_id = upload(client, fixtures, "fail_bad_currency")
        client.post(f"/documents/{document_id}/jobs", json={"type": "extract"})

        assert wait_for(lambda: client.get("/jobs/review").json() != [])
        review = client.get("/jobs/review").json()

    assert review[0]["document_id"] == document_id
    assert review[0]["failure_kind"] == "permanent"

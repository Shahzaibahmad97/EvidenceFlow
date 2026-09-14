from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.domain.events import DocumentStatus
from app.providers.fake import FakeProvider


@pytest.fixture
def client(settings, fixtures):
    app = create_app(settings, provider=FakeProvider.from_fixtures(fixtures.directory))
    with TestClient(app) as client:
        yield client


def _upload(client, fixtures, name):
    response = client.post(
        "/documents", json={"filename": f"{name}.txt", "text": fixtures.text(name)}
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_extract_and_read_back(client, fixtures):
    document_id = _upload(client, fixtures, "inv_001_acme")

    extraction = client.post(f"/documents/{document_id}/extract").json()
    assert extraction["status"] == "succeeded"
    assert extraction["draft"]["total"]["value"] == "507.60"
    assert len(extraction["evidence"]) == 7

    assert extraction["accepted"] is True
    assert {row["outcome"] for row in extraction["validation"]} == {"pass"}

    document = client.get(f"/documents/{document_id}").json()
    assert document["status"] == DocumentStatus.VALIDATED
    assert document["extraction"]["payload_hash"] == extraction["payload_hash"]
    assert [event["type"] for event in document["events"]][0] == "extraction_requested"


def test_failed_extraction_is_visible_with_its_error(client, fixtures):
    document_id = _upload(client, fixtures, "fail_bad_currency")

    extraction = client.post(f"/documents/{document_id}/extract").json()

    assert extraction["status"] == "failed"
    assert extraction["error_code"] == "malformed_provider_output"
    assert "currency" in extraction["error_detail"]


def test_unknown_document_is_404(client):
    assert client.get("/documents/missing").status_code == 404
    assert client.post("/documents/missing/extract").status_code == 404


def test_empty_upload_is_rejected(client):
    assert client.post("/documents", json={"filename": "a.txt", "text": ""}).status_code == 422

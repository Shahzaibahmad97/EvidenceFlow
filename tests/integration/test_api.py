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


def _through_extraction(client, fixtures, name):
    document_id = _upload(client, fixtures, name)
    client.post(f"/documents/{document_id}/extract")
    return document_id


def test_approve_then_write_then_replay(client, fixtures):
    document_id = _through_extraction(client, fixtures, "inv_002_northwind")

    approval = client.post(
        f"/documents/{document_id}/approve", headers={"X-Actor": "sam@example.com"}
    )
    assert approval.status_code == 200
    assert approval.json()["actor"] == "sam@example.com"

    first = client.post(f"/documents/{document_id}/write").json()
    assert first["called_destination"] is True
    assert first["external_id"]

    replays = [client.post(f"/documents/{document_id}/write").json() for _ in range(5)]
    assert all(replay["called_destination"] is False for replay in replays)
    assert {replay["external_id"] for replay in replays} == {first["external_id"]}

    document = client.get(f"/documents/{document_id}").json()
    assert document["status"] == DocumentStatus.WRITTEN
    assert document["approval"]["payload_hash"] == document["extraction"]["payload_hash"]


def test_a_document_in_review_cannot_be_approved_over_http(client, fixtures):
    document_id = _through_extraction(client, fixtures, "adv_ambiguous_date")

    response = client.post(f"/documents/{document_id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_ready_for_approval"


def test_writing_without_approval_is_404(client, fixtures):
    document_id = _through_extraction(client, fixtures, "inv_005_calder")

    response = client.post(f"/documents/{document_id}/write")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "approval_missing"


def test_re_extraction_invalidates_an_approval(client, fixtures):
    document_id = _through_extraction(client, fixtures, "inv_004_meridian")
    client.post(f"/documents/{document_id}/approve")

    client.post(f"/documents/{document_id}/extract")
    response = client.post(f"/documents/{document_id}/write")

    assert response.status_code == 404
    assert client.get(f"/documents/{document_id}").json()["status"] == DocumentStatus.VALIDATED


def test_listing_documents(client, fixtures):
    first = _upload(client, fixtures, "inv_001_acme")
    second = _upload(client, fixtures, "inv_003_bluepeak")
    client.post(f"/documents/{first}/extract")

    listed = client.get("/documents").json()

    assert [row["id"] for row in listed] == [first, second]
    assert {row["filename"] for row in listed} == {"inv_001_acme.txt", "inv_003_bluepeak.txt"}
    assert [row["status"] for row in listed] == [DocumentStatus.VALIDATED, DocumentStatus.RECEIVED]


def test_listing_is_empty_before_anything_arrives(client):
    assert client.get("/documents").json() == []


def test_a_refused_approval_is_recorded_not_rolled_back(client, fixtures):
    original = _through_extraction(client, fixtures, "inv_001_acme")
    copy = _through_extraction(client, fixtures, "adv_duplicate_number")
    client.post(f"/documents/{original}/approve")
    client.post(f"/documents/{original}/write")

    refused = client.post(f"/documents/{copy}/approve")

    assert refused.status_code == 409
    assert "invoice_number_not_duplicate" in refused.json()["detail"]["message"]

    document = client.get(f"/documents/{copy}").json()
    assert document["status"] == DocumentStatus.NEEDS_REVIEW
    assert "invoice_number_not_duplicate" in {
        row["rule"] for row in document["extraction"]["validation"] if row["outcome"] != "pass"
    }
    assert [event["type"] for event in document["events"]].count("validation_completed") == 2

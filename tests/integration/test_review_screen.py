from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.providers.crm import MockCrm
from app.providers.fake import FakeProvider


@pytest.fixture
def crm() -> MockCrm:
    return MockCrm()


@pytest.fixture
def client(settings, fixtures, crm, tmp_path):
    app = create_app(
        replace(settings, database_url=f"sqlite:///{tmp_path / 'review.db'}"),
        provider=FakeProvider.from_fixtures(fixtures.directory),
        crm=crm,
    )
    with TestClient(app) as client:
        yield client


def prepare(client, fixtures, name="inv_001_acme") -> str:
    document_id = client.post(
        "/documents", json={"filename": f"{name}.txt", "text": fixtures.text(name)}
    ).json()["id"]
    client.post(f"/documents/{document_id}/extract")
    return document_id


def test_the_queue_lists_documents_with_their_status(client, fixtures):
    prepare(client, fixtures)
    prepare(client, fixtures, "adv_rounding_drift")

    page = client.get("/review").text

    assert "inv_001_acme.txt" in page
    assert "validated" in page
    assert "subtotal_plus_tax_equals_total" in page


def test_the_document_page_highlights_verified_evidence(client, fixtures):
    document_id = prepare(client, fixtures)

    page = client.get(f"/review/{document_id}").text

    assert "<mark" in page
    assert "Invoice Number: INV-2026-0001" in page
    assert "507.60" in page


def test_unverified_evidence_is_shown_as_unverified(client, fixtures):
    document_id = prepare(client, fixtures, "fail_unverifiable_quote")

    page = client.get(f"/review/{document_id}").text

    assert "unverified" in page
    assert "Subtotal of 560.00 before VAT" in page


def test_approving_from_the_screen_then_writing(client, fixtures, crm):
    document_id = prepare(client, fixtures)
    extraction = client.get(f"/documents/{document_id}").json()["extraction"]

    approved = client.post(
        f"/review/{document_id}/approve",
        data={"payload_hash": extraction["payload_hash"]},
        follow_redirects=True,
    )
    assert "Approved by" in approved.text

    written = client.post(f"/review/{document_id}/write", follow_redirects=True)
    assert "Wrote CRM-00001" in written.text
    assert len(crm.records) == 1

    replayed = client.post(f"/review/{document_id}/write", follow_redirects=True)
    assert "Already written as CRM-00001" in replayed.text
    assert len(crm.records) == 1


def test_a_stale_page_cannot_approve(client, fixtures, crm):
    document_id = prepare(client, fixtures)
    stale_hash = client.get(f"/documents/{document_id}").json()["extraction"]["payload_hash"]
    client.post(f"/documents/{document_id}/extract")

    response = client.post(
        f"/review/{document_id}/approve",
        data={"payload_hash": "hash-from-an-older-page"},
        follow_redirects=True,
    )

    assert "changed since this page was loaded" in response.text
    assert stale_hash
    assert crm.calls == []


def test_a_document_in_review_cannot_be_approved_from_the_screen(client, fixtures):
    document_id = prepare(client, fixtures, "adv_ambiguous_date")
    extraction = client.get(f"/documents/{document_id}").json()["extraction"]

    response = client.post(
        f"/review/{document_id}/approve",
        data={"payload_hash": extraction["payload_hash"]},
        follow_redirects=True,
    )

    assert "not validated" in response.text


def test_an_unknown_document_is_404(client):
    assert client.get("/review/missing").status_code == 404


def test_the_event_trail_is_rendered(client, fixtures):
    document_id = prepare(client, fixtures)

    page = client.get(f"/review/{document_id}").text

    assert "extraction requested" in page
    assert "validation completed" in page

from __future__ import annotations

import pytest

from app.providers.crm import CrmRejected, DatabaseCrm, external_id_for
from app.repositories.models import CrmRecordRow
from app.repositories.session import session_scope

PAYLOAD = {
    "supplier": {"value": "ACME Supplies Ltd", "quote": "ACME SUPPLIES LTD"},
    "invoice_number": {"value": "INV-2026-0001", "quote": "Invoice Number: INV-2026-0001"},
    "total": {"value": "507.60", "quote": "Total 507.60"},
}


def other(**overrides) -> dict:
    payload = {key: dict(value) for key, value in PAYLOAD.items()}
    for field, value in overrides.items():
        payload[field]["value"] = value
    return payload


def test_a_record_is_created_once(file_session_factory):
    crm = DatabaseCrm(file_session_factory)

    first = crm.create_record("key-one", PAYLOAD)
    replay = crm.create_record("key-one", PAYLOAD)

    assert first.created
    assert not replay.created
    assert first.external_id == replay.external_id == external_id_for("key-one")


def test_the_destination_refuses_a_second_record_for_the_same_invoice(file_session_factory):
    crm = DatabaseCrm(file_session_factory)
    crm.create_record("key-one", PAYLOAD)

    with pytest.raises(CrmRejected, match="INV-2026-0001"):
        crm.create_record("key-two", PAYLOAD)

    with session_scope(file_session_factory) as session:
        assert session.query(CrmRecordRow).count() == 1


def test_a_different_invoice_from_the_same_supplier_is_accepted(file_session_factory):
    crm = DatabaseCrm(file_session_factory)
    crm.create_record("key-one", PAYLOAD)

    assert crm.create_record("key-two", other(invoice_number="INV-2026-0002")).created


def test_the_same_number_from_a_different_supplier_is_accepted(file_session_factory):
    crm = DatabaseCrm(file_session_factory)
    crm.create_record("key-one", PAYLOAD)

    assert crm.create_record("key-two", other(supplier="Someone Else Ltd")).created


def test_supplier_punctuation_does_not_create_a_second_record(file_session_factory):
    crm = DatabaseCrm(file_session_factory)
    crm.create_record("key-one", PAYLOAD)

    with pytest.raises(CrmRejected):
        crm.create_record("key-two", other(supplier="acme supplies ltd."))


def test_a_payload_without_a_business_key_is_rejected(file_session_factory):
    crm = DatabaseCrm(file_session_factory)

    with pytest.raises(CrmRejected, match="no supplier and invoice number"):
        crm.create_record("key-one", {"total": {"value": "1.00", "quote": "x"}})


def test_the_destination_is_shared_across_clients(file_session_factory):
    first = DatabaseCrm(file_session_factory)
    second = DatabaseCrm(file_session_factory)

    first.create_record("key-one", PAYLOAD)

    assert not second.create_record("key-one", PAYLOAD).created

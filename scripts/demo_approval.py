"""Walk the approval gate: one clean write, one stale approval, twenty replays.

    python scripts/demo_approval.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.app import build_provider  # noqa: E402
from app.config import Settings  # noqa: E402
from app.domain.approval import ApprovalError, idempotency_key  # noqa: E402
from app.providers.crm import MockCrm  # noqa: E402
from app.repositories import documents as repo  # noqa: E402
from app.repositories.session import build_session_factory, session_scope  # noqa: E402
from app.services.approval import approve_extraction  # noqa: E402
from app.services.crm_write import write_approved_record  # noqa: E402
from app.services.extraction import extract_document  # noqa: E402
from app.services.validation import validate_extraction  # noqa: E402

DOCUMENTS = ROOT / "tests" / "fixtures" / "invoices"
ACTOR = "reviewer@example.com"
NAME = "inv_001_acme"


def main() -> int:
    settings = replace(Settings.from_env(), database_url="sqlite://", provider="fake")
    provider = build_provider(settings)
    factory = build_session_factory(settings)
    crm = MockCrm()

    with session_scope(factory) as session:
        document = repo.create_document(
            session, filename=NAME, source_text=(DOCUMENTS / f"{NAME}.txt").read_text()
        )
        extraction = extract_document(session, document, provider).extraction
        validate_extraction(session, document, extraction)
        document_id = document.id
        print(f"1. extracted and validated -> {document.status}")
        print(f"   payload_hash {extraction.payload_hash[:16]}")

        approve_extraction(session, document, extraction, actor=ACTOR)
        print(f"2. approved by {ACTOR} -> {document.status}")
        print(f"   idempotency key {idempotency_key(document.id, extraction.payload_hash)[:16]}")

        outcome = write_approved_record(session, document, crm)
        print(f"3. wrote {outcome.external_id} -> {document.status}")

    with session_scope(factory) as session:
        document = repo.get_document(session, document_id)
        for _ in range(20):
            write_approved_record(session, document, crm)
    print(f"4. twenty replays -> {len(crm.calls)} destination call(s), {len(crm.records)} record(s)")

    with session_scope(factory) as session:
        document = repo.get_document(session, document_id)
        document.status = "validated"
        extraction = extract_document(session, document, provider).extraction
        validate_extraction(session, document, extraction)
        try:
            write_approved_record(session, document, crm)
        except ApprovalError as exc:
            print(f"5. corrected document, write refused -> {exc.code}: {exc}")

    with session_scope(factory) as session:
        events = repo.list_events(session, document_id)
    print(f"6. event trail: {' -> '.join(event.type for event in events)}")
    print(f"   destination records: {len(crm.records)}")
    return 0 if len(crm.records) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the vertical slice end to end and print the evidence packet.

    python scripts/demo.py                       # fake provider, no API key
    python scripts/demo.py --provider openai     # live, requires OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.app import build_provider  # noqa: E402
from app.config import Settings  # noqa: E402
from app.repositories import documents as repo  # noqa: E402
from app.repositories.session import build_session_factory, session_scope  # noqa: E402
from app.services.extraction import extract_document  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "invoices"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="fake", choices=["fake", "openai"])
    parser.add_argument("--glob", default="inv_*.txt")
    args = parser.parse_args()

    settings = replace(
        Settings.from_env(), database_url="sqlite://", provider=args.provider
    )
    provider = build_provider(settings)
    factory = build_session_factory(settings)

    failures = 0
    for path in sorted(FIXTURE_DIR.glob(args.glob)):
        with session_scope(factory) as session:
            document = repo.create_document(
                session, filename=path.name, source_text=path.read_text()
            )
            outcome = extract_document(session, document, provider)
            failures += _report(path.name, outcome, document.source_text)
    return 1 if failures else 0


def _report(name: str, outcome, source: str) -> int:
    print(f"\n=== {name} -> {outcome.document.status} ===")
    if not outcome.succeeded:
        print(f"  failed: {outcome.extraction.error_code}: {outcome.extraction.error_detail}")
        return 1
    draft = outcome.extraction.draft
    print(f"  {draft['invoice_number']['value']}  {draft['supplier']['value']}")
    print(f"  {draft['total']['value']} {draft['currency']['value']}  {draft['issue_date']['value']}")
    print(f"  payload_hash {outcome.extraction.payload_hash[:12]}  {outcome.extraction.latency_ms}ms")
    for item in outcome.extraction.evidence:
        if item["verified"]:
            print(f"    [line {item['line']:>2}] {item['field']}: {source[item['start']:item['end']]!r}")
        else:
            print(f"    [unverified] {item['field']}: {item['quote']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

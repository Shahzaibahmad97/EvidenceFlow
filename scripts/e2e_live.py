"""End-to-end checks against a running deployment.

    python scripts/e2e_live.py --base-url http://localhost:8000

Drives the documents the deployment is seeded with, the way a reviewer would,
and asserts what a buyer would check by hand.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
ACTOR = "e2e@example.com"


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed.append(name)
            print(f"  PASS  {name}")
        else:
            self.failed.append((name, detail))
            print(f"  FAIL  {name}: {detail}")
        return condition


def documents(client: httpx.Client) -> list[dict]:
    response = client.get("/documents")
    response.raise_for_status()
    return response.json()


def by_name(client: httpx.Client, name: str) -> str:
    for row in documents(client):
        if row["filename"] == f"{name}.txt":
            return row["id"]
    raise LookupError(f"{name} is not in this deployment")


RESERVED = {"inv_001_acme.txt", "adv_duplicate_number.txt"}


def take_validated(client: httpx.Client) -> str:
    for row in documents(client):
        if row["status"] == "validated" and row["filename"] not in RESERVED:
            return row["id"]
    raise LookupError("no validated document is waiting for approval")


def extract(client: httpx.Client, document_id: str) -> dict:
    return client.post(f"/documents/{document_id}/extract").json()


def extraction_of(client: httpx.Client, document_id: str) -> dict:
    return client.get(f"/documents/{document_id}").json()["extraction"]


def wait_for(predicate, timeout: float = 30.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def case_happy_path(client: httpx.Client, report: Report) -> None:
    print("\n1. A validated invoice is approved and written")
    document_id = take_validated(client)
    extraction = extraction_of(client, document_id)
    document = client.get(f"/documents/{document_id}").json()
    print(f"     using {document['filename']}")

    report.check("extraction succeeded", extraction["status"] == "succeeded", str(extraction)[:200])
    report.check(
        "every field carries verified evidence",
        all(item["verified"] for item in extraction["evidence"]),
        str([i["field"] for i in extraction["evidence"] if not i["verified"]]),
    )
    report.check("every span resolves inside the source", _spans_resolve(document, extraction))
    report.check("all rules pass", extraction["accepted"] is True)

    approval = client.post(
        f"/documents/{document_id}/approve", headers={"X-Actor": ACTOR}
    ).json()
    report.check("approval records the actor", approval["actor"] == ACTOR)
    report.check(
        "approval binds the payload hash",
        approval["payload_hash"] == extraction["payload_hash"],
    )

    write = client.post(f"/documents/{document_id}/write").json()
    report.check("destination was called once", write["called_destination"] is True)
    report.check("an external id came back", bool(write["external_id"]), str(write))

    replays = [client.post(f"/documents/{document_id}/write").json() for _ in range(20)]
    report.check(
        "twenty replays call the destination zero more times",
        not any(replay["called_destination"] for replay in replays),
    )
    report.check(
        "every replay returns the same record",
        {replay["external_id"] for replay in replays} == {write["external_id"]},
    )
    report.check(
        "document is written",
        client.get(f"/documents/{document_id}").json()["status"] == "written",
    )


def case_blocked(client: httpx.Client, report: Report) -> None:
    print("\n2. Documents ordinary code refuses")
    cases = [
        ("adv_ambiguous_date", "needs_review", "issue_date_unambiguous"),
        ("adv_unsupported_currency", "needs_review", "supported_currency"),
        ("adv_document_discount", "needs_review", "line_items_sum_to_subtotal"),
        ("fail_unverifiable_quote", "needs_review", "evidence_verified"),
        ("h_005_prior_balance", "needs_review", "line_items_sum_to_subtotal"),
    ]
    for name, status, rule in cases:
        document_id = by_name(client, name)
        extraction = extraction_of(client, document_id)
        blocking = {row["rule"] for row in extraction["validation"] if row["outcome"] != "pass"}
        document = client.get(f"/documents/{document_id}").json()

        report.check(f"{name} is routed to {status}", document["status"] == status, document["status"])
        report.check(f"{name} is blocked by {rule}", rule in blocking, str(sorted(blocking)))

        refused = client.post(f"/documents/{document_id}/approve")
        report.check(f"{name} cannot be approved", refused.status_code == 409, str(refused.status_code))


def case_schema_boundary(client: httpx.Client, report: Report) -> None:
    print("\n3. Output the contract itself refuses")
    for name, marker in (("fail_bad_currency", "currency"), ("fail_missing_invoice_number", "invoice_number")):
        document_id = by_name(client, name)
        extraction = extraction_of(client, document_id)

        report.check(f"{name} fails extraction", extraction["status"] == "failed")
        report.check(
            f"{name} names {marker} in the error",
            marker in (extraction["error_detail"] or ""),
            str(extraction["error_detail"])[:120],
        )
        report.check(
            f"{name} writes no business record", extraction["draft"] is None, str(extraction["draft"])[:80]
        )


def case_duplicate(client: httpx.Client, report: Report) -> None:
    print("\n5. A redelivered invoice is refused once the original is committed")
    original = by_name(client, "inv_001_acme")
    copy = by_name(client, "adv_duplicate_number")

    report.check(
        "an uncommitted copy does not block the original",
        client.get(f"/documents/{original}").json()["status"] == "validated",
        client.get(f"/documents/{original}").json()["status"],
    )
    report.check(
        "the copy is extracted perfectly",
        extraction_of(client, copy)["draft"]["invoice_number"]["value"] == "INV-2026-0001",
    )

    approved = client.post(f"/documents/{original}/approve", headers={"X-Actor": ACTOR})
    report.check("the original is approved", approved.status_code == 200, str(approved.status_code))
    written = client.post(f"/documents/{original}/write").json()
    report.check("the original is written", bool(written.get("external_id")), str(written))

    refused = client.post(f"/documents/{copy}/approve", headers={"X-Actor": ACTOR})
    report.check("the copy is now refused", refused.status_code == 409, str(refused.status_code))
    report.check(
        "the reason names the duplicate rule",
        "invoice_number_not_duplicate" in str(refused.json()),
        str(refused.json())[:160],
    )
    report.check(
        "the copy is routed back to review",
        client.get(f"/documents/{copy}").json()["status"] == "needs_review",
        client.get(f"/documents/{copy}").json()["status"],
    )


def case_correction_invalidates_approval(client: httpx.Client, report: Report) -> None:
    print("\n4. A correction after approval invalidates it")
    document_id = take_validated(client)
    print(f"     using {client.get(f'/documents/{document_id}').json()['filename']}")
    client.post(f"/documents/{document_id}/approve", headers={"X-Actor": ACTOR})

    extract(client, document_id)
    refused = client.post(f"/documents/{document_id}/write")

    report.check("the write is refused", refused.status_code == 404, str(refused.status_code))
    report.check(
        "the reason is a missing approval",
        refused.json()["detail"]["code"] == "approval_missing",
        str(refused.json()),
    )


def case_async_worker(client: httpx.Client, report: Report) -> None:
    print("\n6. A separate worker process drains the queue")
    document_id = take_validated(client)
    print(f"     using {client.get(f'/documents/{document_id}').json()['filename']}")
    job = client.post(f"/documents/{document_id}/jobs", json={"type": "extract"}).json()

    report.check("the job is queued", job["status"] == "pending", str(job))
    settled = wait_for(
        lambda: client.get(f"/jobs/{job['id']}").json()["status"] in {"succeeded", "failed"}
    )
    report.check("the worker picked it up", settled, "job never settled")

    final = client.get(f"/jobs/{job['id']}").json()
    report.check("the job succeeded", final["status"] == "succeeded", str(final))
    report.check(
        "the document reached validated",
        client.get(f"/documents/{document_id}").json()["status"] == "validated",
    )

    client.post(f"/documents/{document_id}/approve", headers={"X-Actor": ACTOR})
    write_job = client.post(f"/documents/{document_id}/jobs", json={"type": "write"}).json()
    wrote = wait_for(
        lambda: client.get(f"/documents/{document_id}").json()["status"] == "written"
    )
    report.check("the worker wrote the record", wrote, str(client.get(f"/jobs/{write_job['id']}").json()))


def case_review_screen(client: httpx.Client, report: Report) -> None:
    print("\n7. The review screen")
    document_id = take_validated(client)
    filename = client.get(f"/documents/{document_id}").json()["filename"]
    print(f"     using {filename}")
    extraction = extraction_of(client, document_id)

    page = client.get(f"/review/{document_id}").text
    report.check("evidence is highlighted", page.count("<mark") == 7, str(page.count("<mark")))
    report.check("the source is shown", filename.replace(".txt", "") in page or "<pre" in page)
    report.check("the approve control is present", "Approve this version" in page)

    stale = client.post(
        f"/review/{document_id}/approve", data={"payload_hash": "stale"}, follow_redirects=True
    )
    report.check("a stale page cannot approve", "changed since this page was loaded" in stale.text)
    report.check(
        "the document is still unapproved",
        client.get(f"/documents/{document_id}").json()["status"] == "validated",
    )

    approved = client.post(
        f"/review/{document_id}/approve",
        data={"payload_hash": extraction["payload_hash"]},
        headers={"X-Actor": ACTOR},
        follow_redirects=True,
    )
    report.check("a current page can approve", "Approved by" in approved.text)

    written = client.post(f"/review/{document_id}/write", follow_redirects=True).text
    report.check("the screen writes the record", "Wrote CRM-" in written, written[-200:])
    again = client.post(f"/review/{document_id}/write", follow_redirects=True).text
    report.check("a second press creates nothing", "Already written as CRM-" in again)


def _spans_resolve(document: dict, extraction: dict) -> bool:
    source = document["source_text"]
    return all(
        source[item["start"] : item["end"]].split() == item["quote"].split()
        for item in extraction["evidence"]
        if item["verified"]
    )


def case_limits(client: httpx.Client, report: Report) -> None:
    print("\n8. Public-surface limits")
    oversized = client.post("/documents", json={"filename": "big.txt", "text": "x" * 300_000})
    report.check("an oversized body is refused", oversized.status_code == 413, str(oversized.status_code))
    report.check("health is open", client.get("/health").json() == {"status": "ok"})
    report.check("the queue renders", client.get("/review").status_code == 200)


def case_review_queue(client: httpx.Client, report: Report) -> None:
    print("\n9. The seeded queue matches the evaluation")
    page = client.get("/review").text
    report.check(
        "the seeded documents are listed",
        page.count('href="/review/') >= 30,
        str(page.count('href="/review/')),
    )
    report.check("some documents are validated", ">validated<" in page)
    report.check("some documents need review", ">needs review<" in page)
    report.check("some were refused at the schema boundary", ">extraction failed<" in page)


def _refuse_rate_limited(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise SystemExit(
            "the deployment rate-limited this run: it makes more than sixty writes a "
            "minute. Set EVIDENCEFLOW_RATE_LIMIT_PER_MINUTE higher on the deployment "
            "you are testing, or run the suite against a local instance."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-queue", action="store_true")
    parser.add_argument("--expect-seeded", type=int, default=30)
    args = parser.parse_args()

    report = Report()
    with httpx.Client(base_url=args.base_url, timeout=30.0, event_hooks={"response": [_refuse_rate_limited]}) as client:
        client.get("/health").raise_for_status()
        case_happy_path(client, report)
        case_blocked(client, report)
        case_schema_boundary(client, report)
        case_correction_invalidates_approval(client, report)
        case_duplicate(client, report)
        case_async_worker(client, report)
        case_review_screen(client, report)
        case_limits(client, report)
        if not args.skip_queue:
            case_review_queue(client, report)

    print(f"\n{len(report.passed)} passed, {len(report.failed)} failed")
    for name, detail in report.failed:
        print(f"  {name}: {detail}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

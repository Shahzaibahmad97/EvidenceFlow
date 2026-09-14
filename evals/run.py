"""Replay the dataset through extraction and validation, then write the report.

    python evals/run.py                      # fake provider, deterministic
    python evals/run.py --provider openai    # live, requires OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.app import build_provider  # noqa: E402
from app.config import Settings  # noqa: E402
from app.domain.validation import RuleOutcome  # noqa: E402
from app.repositories import documents as repo  # noqa: E402
from app.repositories.session import build_session_factory, session_scope  # noqa: E402
from app.services.extraction import extract_document  # noqa: E402
from app.services.validation import validate_extraction  # noqa: E402

DATASET = Path(__file__).parent / "dataset.jsonl"
DOCUMENTS = ROOT / "tests" / "fixtures" / "invoices"
SCORED_FIELDS = (
    "invoice_number",
    "supplier",
    "currency",
    "issue_date",
    "subtotal",
    "tax",
    "total",
)


@dataclass
class Row:
    id: str
    difficulty: str
    notes: str
    expected_outcome: str
    expected_rules: list[str]
    outcome: str = ""
    blocking_rules: list[str] = None  # type: ignore[assignment]
    correct_fields: int = 0
    scored_fields: int = 0
    wrong: list[str] = None  # type: ignore[assignment]
    unscorable: list[str] = None  # type: ignore[assignment]
    latency_ms: int = 0
    error: str = ""

    @property
    def routed_as_expected(self) -> bool:
        return self.outcome == self.expected_outcome

    @property
    def rules_as_expected(self) -> bool:
        return sorted(self.blocking_rules or []) == sorted(self.expected_rules)


def load_dataset() -> list[dict[str, Any]]:
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def run(provider_name: str) -> list[Row]:
    settings = replace(Settings.from_env(), database_url="sqlite://", provider=provider_name)
    provider = build_provider(settings)
    factory = build_session_factory(settings)

    rows = []
    for entry in load_dataset():
        with session_scope(factory) as session:
            rows.append(_run_one(session, entry, provider))
    return rows


def _run_one(session, entry: dict[str, Any], provider) -> Row:
    row = Row(
        id=entry["id"],
        difficulty=entry["difficulty"],
        notes=entry["notes"],
        expected_outcome=entry["expected_outcome"],
        expected_rules=entry["expected_blocking_rules"],
        blocking_rules=[],
        wrong=[],
        unscorable=[],
    )
    document = repo.create_document(
        session,
        filename=entry["document"],
        source_text=(DOCUMENTS / entry["document"]).read_text(),
    )
    outcome = extract_document(session, document, provider)
    row.latency_ms = outcome.extraction.latency_ms or 0

    if not outcome.succeeded:
        row.outcome = "extraction_failed"
        row.error = f"{outcome.extraction.error_code}: {outcome.extraction.error_detail}"
        return row

    results = validate_extraction(session, document, outcome.extraction)
    row.blocking_rules = [r.rule for r in results if r.blocking]
    row.outcome = _routing(results)
    _score_fields(row, outcome.extraction.draft, entry["ground_truth"])
    return row


def _routing(results) -> str:
    outcomes = {r.outcome for r in results}
    if RuleOutcome.FAIL in outcomes:
        return "fail"
    if RuleOutcome.NEEDS_REVIEW in outcomes:
        return "needs_review"
    return "validated"


def _score_fields(row: Row, draft: dict[str, Any], truth: dict[str, Any]) -> None:
    for name in SCORED_FIELDS:
        expected = truth.get(name)
        if expected is None:
            row.unscorable.append(name)
            continue
        row.scored_fields += 1
        if draft[name]["value"] == expected:
            row.correct_fields += 1
        else:
            row.wrong.append(f"{name}={draft[name]['value']!r} (truth {expected!r})")


def report(rows: list[Row], provider_name: str) -> str:
    scored = sum(r.scored_fields for r in rows)
    correct = sum(r.correct_fields for r in rows)
    routed = sum(1 for r in rows if r.routed_as_expected)
    rules_ok = sum(1 for r in rows if r.outcome == "extraction_failed" or r.rules_as_expected)
    outcomes = Counter(r.outcome for r in rows)
    accepted = outcomes["validated"]

    lines = [
        "# Evaluation v1 — deterministic validation",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} from `evals/dataset.jsonl` "
        f"via the `{provider_name}` provider.",
        "Regenerate with `python evals/run.py`.",
        "",
        "## Headline",
        "",
        f"- Documents: **{len(rows)}** ({sum(1 for r in rows if r.difficulty == 'routine')} routine, "
        f"{sum(1 for r in rows if r.difficulty == 'hard')} hard)",
        f"- Field accuracy: **{correct}/{scored}** ({_pct(correct, scored)})",
        f"- Routed as the hand-written label expects: **{routed}/{len(rows)}** ({_pct(routed, len(rows))})",
        f"- Blocking rules matched the label: **{rules_ok}/{len(rows)}**",
        f"- Reached `validated`: **{accepted}/{len(rows)}** — "
        f"{outcomes['needs_review']} to review, {outcomes['fail']} failed, "
        f"{outcomes['extraction_failed']} rejected at the schema boundary",
        "",
        "Field accuracy is scored only where a correct answer exists. "
        f"{sum(len(r.unscorable) for r in rows)} field(s) are marked unscorable because the "
        "document itself is ambiguous or self-contradictory — those are review work by "
        "definition, not extraction errors.",
        "",
        "## By difficulty",
        "",
        "| Cohort | Documents | Field accuracy | Routed as expected | Reached validated |",
        "|---|---|---|---|---|",
    ]
    for cohort in ("routine", "hard"):
        subset = [r for r in rows if r.difficulty == cohort]
        s = sum(r.scored_fields for r in subset)
        c = sum(r.correct_fields for r in subset)
        lines.append(
            f"| {cohort} | {len(subset)} | {c}/{s} ({_pct(c, s)}) | "
            f"{sum(1 for r in subset if r.routed_as_expected)}/{len(subset)} | "
            f"{sum(1 for r in subset if r.outcome == 'validated')}/{len(subset)} |"
        )

    lines += [
        "",
        "## Per document",
        "",
        "| Document | Expected | Actual | Fields | Blocking rules |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        mark = "" if row.routed_as_expected else " **!**" 
        fields = f"{row.correct_fields}/{row.scored_fields}" if row.scored_fields else "n/a"
        rules = ", ".join(f"`{r}`" for r in row.blocking_rules) or "—"
        lines.append(
            f"| `{row.id}` | {row.expected_outcome} | {row.outcome}{mark} | {fields} | {rules} |"
        )

    lines += ["", "## Schema-valid, business-invalid", ""]
    semantic = [
        r
        for r in rows
        if r.outcome in {"fail", "needs_review"} and r.outcome != "extraction_failed"
    ]
    lines.append(
        f"{len(semantic)} of {len(rows)} documents produced output the model's own schema "
        "accepts and that ordinary code refused. This is the case the project exists to make: "
        "valid JSON is not a valid business outcome."
    )
    lines.append("")
    for row in semantic:
        lines += [
            f"**`{row.id}`** — {row.notes}",
            "",
            f"- Routed to `{row.outcome}` by {', '.join(f'`{r}`' for r in row.blocking_rules)}",
        ]
        if row.wrong:
            lines.append(f"- Extracted wrongly: {'; '.join(row.wrong)}")
        if row.unscorable:
            lines.append(f"- No correct answer exists for: {', '.join(row.unscorable)}")
        lines.append("")

    mismatches = [r for r in rows if not r.routed_as_expected]
    lines += ["## Label mismatches", ""]
    lines.append(
        "None. Every document routed the way its hand-written label said it should."
        if not mismatches
        else "\n".join(
            f"- `{r.id}`: expected `{r.expected_outcome}`, got `{r.outcome}`"
            f"{' — ' + r.error if r.error else ''}"
            for r in mismatches
        )
    )
    lines += [
        "",
        "## What this does not measure",
        "",
        "- Ground truth is hand-written, but the documents are synthetic and written by the "
        "same person who wrote the rules. Accuracy here is a floor on difficulty, not a "
        "forecast of live performance.",
        "- The fake provider replays a fixed payload per document, so this run measures the "
        "validation layer, not model quality. Week 5 adds held-out documents and live runs.",
        "- No latency, token, or cost figure is reported: the deterministic provider has no "
        "cost, and reporting one would be theatre.",
        "",
    ]
    return "\n".join(lines)


def _pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.0f}%" if denominator else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="fake", choices=["fake", "openai"])
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "report.md")
    parser.add_argument("--check", action="store_true", help="exit non-zero on any label mismatch")
    args = parser.parse_args()

    rows = run(args.provider)
    args.out.write_text(report(rows, args.provider))
    mismatches = [r for r in rows if not r.routed_as_expected]
    print(f"{len(rows)} documents, {len(mismatches)} label mismatches -> {args.out}")
    for row in mismatches:
        print(f"  {row.id}: expected {row.expected_outcome}, got {row.outcome} {row.error}")
    return 1 if (args.check and mismatches) else 0


if __name__ == "__main__":
    raise SystemExit(main())

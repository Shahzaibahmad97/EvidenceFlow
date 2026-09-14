"""Replay the evaluation set through the real pipeline and write the report.

    python evals/run.py                       # dev + held-out, fake provider
    python evals/run.py --split held_out      # held-out only
    python evals/run.py --provider openai     # live, requires OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.app import build_provider  # noqa: E402
from app.config import Settings  # noqa: E402
from app.domain.events import DocumentStatus  # noqa: E402
from app.domain.jobs import JobType  # noqa: E402
from app.providers.crm import MockCrm  # noqa: E402
from app.providers.fake import FAKE_MODEL  # noqa: E402
from app.providers.prompt import PROMPT_HASH  # noqa: E402
from app.repositories import documents as repo  # noqa: E402
from app.repositories.models import Job  # noqa: E402
from app.repositories.session import build_session_factory, session_scope  # noqa: E402
from app.services.approval import approve_extraction  # noqa: E402
from app.workflows import queue  # noqa: E402
from app.workflows.worker import Worker  # noqa: E402
from evals.cost import CostModel  # noqa: E402
from evals.labels import CausalLabel, label_blocking_rules, label_extraction_failure  # noqa: E402

SPLITS = {
    "dev": (Path(__file__).parent / "dataset.jsonl", ROOT / "tests" / "fixtures" / "invoices"),
    "held_out": (Path(__file__).parent / "held_out.jsonl", ROOT / "tests" / "fixtures" / "held_out"),
}
SCORED_FIELDS = (
    "invoice_number",
    "supplier",
    "currency",
    "issue_date",
    "subtotal",
    "tax",
    "total",
)
ACTOR = "evaluation@example.com"


@dataclass
class Trajectory:
    id: str
    split: str
    difficulty: str
    notes: str
    expected_outcome: str
    expected_rules: list[str]
    expected_label: str | None
    outcome: str = ""
    blocking_rules: list[str] = field(default_factory=list)
    label: str | None = None
    correct_fields: int = 0
    scored_fields: int = 0
    wrong: list[str] = field(default_factory=list)
    unscorable: list[str] = field(default_factory=list)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    jobs: int = 0
    accepted: bool = False
    external_id: str | None = None
    error: str = ""

    @property
    def retries(self) -> int:
        return max(self.attempts - self.jobs, 0)

    @property
    def routed_as_expected(self) -> bool:
        return self.outcome == self.expected_outcome

    @property
    def labelled_as_expected(self) -> bool:
        return self.label == self.expected_label

    @property
    def needs_a_person(self) -> bool:
        return not self.accepted


@dataclass
class Run:
    name: str
    rows: list[Trajectory]
    destination_records: int
    destination_calls: int

    @property
    def accepted(self) -> int:
        return sum(row.accepted for row in self.rows)

    @property
    def duplicate_writes(self) -> int:
        return self.destination_records - self.accepted


def load(split: str) -> list[dict[str, Any]]:
    path, _ = SPLITS[split]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_splits(selection: str) -> list[dict[str, Any]]:
    names = list(SPLITS) if selection == "all" else [selection]
    return [entry for name in names for entry in load(name)]


def run(entries: list[dict[str, Any]], provider_name: str, *, fallback: bool, name: str) -> Run:
    settings = replace(Settings.from_env(), database_url="sqlite://", provider=provider_name)
    crm = MockCrm()
    factory = build_session_factory(settings)
    worker = Worker(
        session_factory=factory,
        provider=build_provider(settings),
        crm=crm,
        allow_value_fallback=fallback,
    )
    rows = [_one(factory, worker, entry) for entry in entries]
    return Run(name=name, rows=rows, destination_records=len(crm.records), destination_calls=len(crm.calls))


def _one(factory, worker: Worker, entry: dict[str, Any]) -> Trajectory:
    row = Trajectory(
        id=entry["id"],
        split=entry["split"],
        difficulty=entry["difficulty"],
        notes=entry["notes"],
        expected_outcome=entry["expected_outcome"],
        expected_rules=entry["expected_blocking_rules"],
        expected_label=entry["expected_label"],
    )
    _, documents = SPLITS[entry["split"]]

    with session_scope(factory) as session:
        document_id = repo.create_document(
            session,
            filename=entry["document"],
            source_text=(documents / entry["document"]).read_text(),
        ).id
        queue.enqueue(session, type=JobType.EXTRACT, document_id=document_id)
    worker.drain()

    with session_scope(factory) as session:
        document = repo.get_document(session, document_id)
        extraction = repo.latest_extraction(session, document_id)
        row.latency_ms = extraction.latency_ms or 0
        row.input_tokens = extraction.input_tokens or 0
        row.output_tokens = extraction.output_tokens or 0

        if not extraction.succeeded:
            row.outcome = "extraction_failed"
            row.error = f"{extraction.error_code}: {extraction.error_detail}"
            row.label = label_extraction_failure(extraction.error_detail or "")
            row.attempts, row.jobs = _job_totals(session, document_id)
            return row

        results = repo.list_validation_results(session, extraction.id)
        row.blocking_rules = [r.rule for r in results if r.outcome != "pass"]
        row.outcome = _routing(results)
        row.label = label_blocking_rules(row.blocking_rules)
        _score(row, extraction.draft, entry["ground_truth"])

        if document.status == DocumentStatus.VALIDATED:
            approve_extraction(session, document, extraction, actor=ACTOR)
            queue.enqueue(session, type=JobType.WRITE, document_id=document_id)

    worker.drain()

    with session_scope(factory) as session:
        document = repo.get_document(session, document_id)
        row.accepted = document.status == DocumentStatus.WRITTEN
        row.attempts, row.jobs = _job_totals(session, document_id)
        if row.accepted:
            write = repo.find_write(
                session,
                _write_key(document),
            )
            row.external_id = write.external_id if write else None
    return row


def _write_key(document) -> str:
    from app.domain.approval import idempotency_key

    return idempotency_key(document.id, document.approved_payload_hash)


def _job_totals(session, document_id: str) -> tuple[int, int]:
    from sqlalchemy import func, select

    return session.execute(
        select(func.coalesce(func.sum(Job.attempts), 0), func.count(Job.id)).where(
            Job.document_id == document_id
        )
    ).one()


def _routing(results) -> str:
    outcomes = {row.outcome for row in results}
    if "fail" in outcomes:
        return "fail"
    if "needs_review" in outcomes:
        return "needs_review"
    return "validated"


def _score(row: Trajectory, draft: dict[str, Any], truth: dict[str, Any]) -> None:
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


def _pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.0f}%" if denominator else "n/a"


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(int(fraction * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _money(amount: Decimal) -> str:
    return f"${amount.quantize(Decimal('0.0001'))}"


def report(baseline: Run, variant: Run | None, provider_name: str, costs: CostModel) -> str:
    rows = baseline.rows
    scored = sum(r.scored_fields for r in rows)
    correct = sum(r.correct_fields for r in rows)
    routed = sum(r.routed_as_expected for r in rows)
    labelled = sum(r.labelled_as_expected for r in rows)
    reviewed = sum(r.needs_a_person for r in rows)
    latencies = [r.latency_ms for r in rows]
    input_tokens = sum(r.input_tokens for r in rows)
    output_tokens = sum(r.output_tokens for r in rows)
    retries = sum(r.retries for r in rows)

    model_cost = costs.model_cost(input_tokens, output_tokens)
    reviewer_cost = costs.reviewer_cost(reviewed)
    total_cost = model_cost + reviewer_cost
    per_accepted = total_cost / baseline.accepted if baseline.accepted else Decimal("0")

    lines = [
        "# Evaluation v2 — causal labels and cost per accepted outcome",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Provider `{provider_name}`, "
        f"model `{FAKE_MODEL if provider_name == 'fake' else 'see settings'}`, "
        f"prompt `{PROMPT_HASH}`.",
        "Regenerate with `python evals/run.py`.",
        "",
        f"Runs marked `fake` are **replayed** from committed fixtures, not live model calls. "
        f"Live runs use `--provider openai` and are labelled as such in the header above.",
        "",
        "## Headline",
        "",
        f"- Documents: **{len(rows)}** — {sum(r.split == 'dev' for r in rows)} development, "
        f"{sum(r.split == 'held_out' for r in rows)} held out",
        f"- Accepted and written: **{baseline.accepted}/{len(rows)}** ({_pct(baseline.accepted, len(rows))})",
        f"- Field accuracy: **{correct}/{scored}** ({_pct(correct, scored)})",
        f"- Routed as the hand-written label expects: **{routed}/{len(rows)}**",
        f"- Causal label matched the hand-written label: **{labelled}/{len(rows)}**",
        f"- Duplicate destination records: **{baseline.duplicate_writes}**",
        f"- Destination calls: {baseline.destination_calls} for {baseline.destination_records} records",
        f"- Retries: **{retries}**",
        f"- Extraction latency: p50 {_percentile(latencies, 0.5)} ms, p95 "
        f"{_percentile(latencies, 0.95)} ms"
        + (" — a replayed run has no model call to time" if provider_name == "fake" else ""),
        f"- Tokens: {input_tokens:,} in, {output_tokens:,} out",
        "",
        "## Cost per accepted outcome",
        "",
        "Every figure below rests on stated assumptions, not measurements:",
        "",
        *[f"- {line}" for line in costs.describe()],
        "",
        f"| Component | Amount |",
        "|---|---|",
        f"| Model | {_money(model_cost)} |",
        f"| Reviewer ({reviewed} documents) | {_money(reviewer_cost)} |",
        f"| **Total** | **{_money(total_cost)}** |",
        f"| Accepted records | {baseline.accepted} |",
        f"| **Cost per accepted record** | **{_money(per_accepted)}** |",
        "",
        "Reviewer time dominates, and that is the finding. A cost figure quoting only "
        "tokens would be smaller, more flattering, and wrong.",
        "",
        "## By split",
        "",
        "| Split | Documents | Field accuracy | Routed as expected | Labelled as expected | Accepted |",
        "|---|---|---|---|---|---|",
    ]
    for split in ("dev", "held_out"):
        subset = [r for r in rows if r.split == split]
        if not subset:
            continue
        s = sum(r.scored_fields for r in subset)
        c = sum(r.correct_fields for r in subset)
        lines.append(
            f"| {split} | {len(subset)} | {c}/{s} ({_pct(c, s)}) | "
            f"{sum(r.routed_as_expected for r in subset)}/{len(subset)} | "
            f"{sum(r.labelled_as_expected for r in subset)}/{len(subset)} | "
            f"{sum(r.accepted for r in subset)}/{len(subset)} |"
        )

    lines += [
        "",
        "## By difficulty",
        "",
        "| Cohort | Documents | Field accuracy | Accepted | Sent to a person |",
        "|---|---|---|---|---|",
    ]
    for cohort in ("routine", "hard"):
        subset = [r for r in rows if r.difficulty == cohort]
        if not subset:
            continue
        s = sum(r.scored_fields for r in subset)
        c = sum(r.correct_fields for r in subset)
        lines.append(
            f"| {cohort} | {len(subset)} | {c}/{s} ({_pct(c, s)}) | "
            f"{sum(r.accepted for r in subset)}/{len(subset)} | "
            f"{sum(r.needs_a_person for r in subset)}/{len(subset)} |"
        )

    counts = Counter(r.label for r in rows if r.label)
    lines += [
        "",
        "## Earliest causal error",
        "",
        "Each blocked document is labelled by its root cause, not by the damage that "
        "followed it. A document whose lines were mis-read *and* whose totals then failed "
        "to add up is a selection error, once.",
        "",
        "| Label | Documents | Meaning |",
        "|---|---|---|",
        f"| `selection` | {counts[CausalLabel.SELECTION]} | the model took the wrong value from the document |",
        f"| `completeness` | {counts[CausalLabel.COMPLETENESS]} | a required field was not there to take |",
        f"| `truthfulness` | {counts[CausalLabel.TRUTHFULNESS]} | the evidence offered does not appear in the source |",
        f"| `postcondition` | {counts[CausalLabel.POSTCONDITION]} | extraction was faithful; the record still cannot be written |",
        "",
        f"{counts[CausalLabel.POSTCONDITION]} of {len(rows) - baseline.accepted} blocked documents are "
        "postcondition failures. The model was right and the answer was still no — because "
        "the document contradicts itself, repeats an earlier invoice, or falls outside "
        "policy. No prompt change addresses those.",
        "",
        "## Per document",
        "",
        "| Document | Split | Expected | Actual | Label | Fields | Jobs | Retries |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        mark = "" if row.routed_as_expected else " **!**"
        label_mark = "" if row.labelled_as_expected else " **!**"
        fields = f"{row.correct_fields}/{row.scored_fields}" if row.scored_fields else "n/a"
        lines.append(
            f"| `{row.id}` | {row.split} | {row.expected_outcome} | {row.outcome}{mark} | "
            f"{row.label or '—'}{label_mark} | {fields} | {row.jobs} | {row.retries} |"
        )

    lines += ["", "## Held-out documents", ""]
    held = [r for r in rows if r.split == "held_out"]
    if held:
        surprises = [r for r in held if not (r.routed_as_expected and r.labelled_as_expected)]
        lines.append(
            "These ten were written after the rules were fixed and were never used to tune "
            "them. No rule, threshold, or prompt was changed after seeing these results."
        )
        lines.append("")
        if surprises:
            lines += [f"- `{r.id}`: expected {r.expected_outcome}/{r.expected_label}, got {r.outcome}/{r.label}" for r in surprises]
        else:
            lines.append(
                "All ten routed and labelled as their hand-written labels said they would. "
                "That is a real result and a narrow one: the held-out set shares an author "
                "and a generator with the development set."
            )

    mismatches = [r for r in rows if not r.routed_as_expected or not r.labelled_as_expected]
    lines += ["", "## Label mismatches", ""]
    lines.append(
        "None."
        if not mismatches
        else "\n".join(
            f"- `{r.id}`: expected `{r.expected_outcome}`/`{r.expected_label}`, "
            f"got `{r.outcome}`/`{r.label}`{' — ' + r.error if r.error else ''}"
            for r in mismatches
        )
    )

    if variant is not None:
        lines += _improvement_section(baseline, variant)

    lines += [
        "",
        "## What this does not measure",
        "",
        "- The documents are synthetic and share an author with the rules. Accuracy here is "
        "a statement about the difficulty of this set, not a forecast of live performance.",
        "- A `fake` run replays committed payloads, so it measures the validation, approval "
        "and write layers rather than model quality. Only a live run measures the model.",
        "- Retries are zero in a clean run because nothing failed. The retry and recovery "
        "paths are exercised by the test suite and by `scripts/demo_recovery.py`, not here.",
        "- Reviewer minutes are assumed, not observed. Nobody reviewed these documents.",
        "",
    ]
    return "\n".join(lines)


def _improvement_section(baseline: Run, variant: Run) -> list[str]:
    changed = [
        (before, after)
        for before, after in zip(baseline.rows, variant.rows, strict=True)
        if before.outcome != after.outcome
    ]
    derived = [after.id for _, after in changed if after.accepted]
    return [
        "",
        "## Attempted improvement: fall back to the field value when a quote cannot be found",
        "",
        "**Change.** When a model-supplied quote is not present in the source, look for the "
        "extracted *value* instead and accept the span it lands on.",
        "",
        f"**Result.** Accepted records {baseline.accepted} -> {variant.accepted}. "
        f"Documents that changed outcome: {len(changed)}"
        + (f" ({', '.join(after.id for _, after in changed)})" if changed else ""),
        "",
        "**Decision: rejected.** It buys acceptance by giving up the guarantee the project "
        "exists to make. A quote the model invented is not evidence, and finding the number "
        "somewhere else in the document does not make it so — the number appears in a total, "
        "a line item and a payment slip, and the fallback cannot tell which one the model "
        "meant. Every document it newly accepted"
        + (f" ({', '.join(derived)})" if derived else "")
        + " would have been accepted on evidence nobody can check.",
        "",
        "The code path stays in the repository, off by default, because the experiment is "
        "part of the evidence. `allow_value_fallback` is never set in production.",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="fake", choices=["fake", "openai"])
    parser.add_argument("--split", default="all", choices=[*SPLITS, "all"])
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "report.md")
    parser.add_argument("--no-experiment", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    entries = load_splits(args.split)
    baseline = run(entries, args.provider, fallback=False, name="baseline")
    variant = (
        None
        if args.no_experiment
        else run(entries, args.provider, fallback=True, name="value-fallback")
    )

    args.out.write_text(report(baseline, variant, args.provider, CostModel()))

    mismatches = [
        r for r in baseline.rows if not r.routed_as_expected or not r.labelled_as_expected
    ]
    print(
        f"{len(baseline.rows)} documents, {baseline.accepted} accepted, "
        f"{baseline.duplicate_writes} duplicate writes, {len(mismatches)} label mismatches "
        f"-> {args.out}"
    )
    for row in mismatches:
        print(
            f"  {row.id}: expected {row.expected_outcome}/{row.expected_label}, "
            f"got {row.outcome}/{row.label} {row.error}"
        )
    return 1 if (args.check and (mismatches or baseline.duplicate_writes)) else 0


if __name__ == "__main__":
    raise SystemExit(main())

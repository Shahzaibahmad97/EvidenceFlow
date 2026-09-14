from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import wraps
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.domain.evidence import EvidenceResult
from app.domain.schema import InvoiceDraft

MONEY_TOLERANCE = Decimal("0.01")
SUPPORTED_CURRENCIES = frozenset({"GBP", "EUR", "USD"})
EARLIEST_PLAUSIBLE_DATE = date(2000, 1, 1)

CURRENCY_SYMBOLS = {
    "£": frozenset({"GBP"}),
    "€": frozenset({"EUR"}),
    "$": frozenset({"USD", "CAD", "AUD", "NZD"}),
}

AMBIGUOUS_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")


class RuleOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class RuleResult:
    rule: str
    outcome: RuleOutcome
    message: str = ""

    @property
    def blocking(self) -> bool:
        return self.outcome is not RuleOutcome.PASS


@dataclass(frozen=True)
class ValidationInput:
    draft: InvoiceDraft
    source: str
    evidence: list[EvidenceResult] = field(default_factory=list)
    known_invoice_numbers: frozenset[tuple[str, str]] = frozenset()
    today: date = field(default_factory=date.today)


Verdict = tuple[RuleOutcome, str] | None
Rule = Callable[[ValidationInput], RuleResult]
RULES: list[Rule] = []


def rule(name: str) -> Callable[[Callable[[ValidationInput], Verdict]], Rule]:
    def decorate(fn: Callable[[ValidationInput], Verdict]) -> Rule:
        @wraps(fn)
        def run(data: ValidationInput) -> RuleResult:
            outcome, message = fn(data) or (RuleOutcome.PASS, "")
            return RuleResult(rule=name, outcome=outcome, message=message)

        RULES.append(run)
        return run

    return decorate


def validate(data: ValidationInput) -> list[RuleResult]:
    return [rule_fn(data) for rule_fn in RULES]


def is_accepted(results: Iterable[RuleResult]) -> bool:
    return not any(result.blocking for result in results)


def _money_outcome(difference: Decimal) -> RuleOutcome:
    if difference == 0:
        return RuleOutcome.PASS
    return RuleOutcome.NEEDS_REVIEW if difference <= MONEY_TOLERANCE else RuleOutcome.FAIL


def normalize_supplier(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


@rule("required_fields_present")
def required_fields_present(data: ValidationInput) -> Verdict:
    blank = [
        name
        for name in ("invoice_number", "supplier")
        if not str(getattr(data.draft, name).value).strip()
    ]
    if blank:
        return RuleOutcome.FAIL, f"blank: {', '.join(blank)}"
    if not data.draft.line_items:
        return RuleOutcome.FAIL, "no line items"
    return None


@rule("line_item_arithmetic")
def line_item_arithmetic(data: ValidationInput) -> Verdict:
    worst = RuleOutcome.PASS
    messages = []
    for index, item in enumerate(data.draft.line_items, start=1):
        outcome = _money_outcome(abs(item.quantity * item.unit_price - item.amount))
        if outcome is RuleOutcome.PASS:
            continue
        messages.append(f"line {index}: {item.quantity} x {item.unit_price} != {item.amount}")
        if outcome is RuleOutcome.FAIL or worst is RuleOutcome.PASS:
            worst = outcome
    return None if worst is RuleOutcome.PASS else (worst, "; ".join(messages))


@rule("line_items_sum_to_subtotal")
def line_items_sum_to_subtotal(data: ValidationInput) -> Verdict:
    summed = sum((item.amount for item in data.draft.line_items), Decimal("0"))
    subtotal = data.draft.subtotal.value
    outcome = _money_outcome(abs(summed - subtotal))
    if outcome is RuleOutcome.PASS:
        return None
    return outcome, f"line items sum to {summed}, subtotal is {subtotal}"


@rule("subtotal_plus_tax_equals_total")
def subtotal_plus_tax_equals_total(data: ValidationInput) -> Verdict:
    draft = data.draft
    outcome = _money_outcome(
        abs(draft.subtotal.value + draft.tax.value - draft.total.value)
    )
    if outcome is RuleOutcome.PASS:
        return None
    return outcome, f"{draft.subtotal.value} + {draft.tax.value} != {draft.total.value}"


@rule("supported_currency")
def supported_currency(data: ValidationInput) -> Verdict:
    code = data.draft.currency.value
    if code not in SUPPORTED_CURRENCIES:
        return RuleOutcome.FAIL, f"unsupported currency {code}"
    return None


@rule("currency_agrees_with_source")
def currency_agrees_with_source(data: ValidationInput) -> Verdict:
    code = data.draft.currency.value
    for symbol, codes in CURRENCY_SYMBOLS.items():
        if symbol in data.source and code not in codes:
            return RuleOutcome.NEEDS_REVIEW, f"source shows {symbol} but currency is {code}"
    return None


@rule("issue_date_plausible")
def issue_date_plausible(data: ValidationInput) -> Verdict:
    issued = data.draft.issue_date.value
    if issued > data.today:
        return RuleOutcome.FAIL, f"{issued} is in the future"
    if issued < EARLIEST_PLAUSIBLE_DATE:
        return RuleOutcome.FAIL, f"{issued} is implausibly old"
    return None


@rule("issue_date_unambiguous")
def issue_date_unambiguous(data: ValidationInput) -> Verdict:
    match = AMBIGUOUS_DATE.search(data.draft.issue_date.quote)
    if not match:
        return None
    first, second = int(match.group(1)), int(match.group(2))
    if first != second and first <= 12 and second <= 12:
        return RuleOutcome.NEEDS_REVIEW, f"{match.group(0)} could be day-first or month-first"
    return None


@rule("invoice_number_not_duplicate")
def invoice_number_not_duplicate(data: ValidationInput) -> Verdict:
    supplier, number = (
        normalize_supplier(data.draft.supplier.value),
        data.draft.invoice_number.value.strip(),
    )
    if (supplier, number) in data.known_invoice_numbers:
        return RuleOutcome.FAIL, f"{number} already recorded for this supplier"
    return None


@rule("evidence_verified")
def evidence_verified(data: ValidationInput) -> Verdict:
    unverified = [item.field for item in data.evidence if not item.verified]
    if unverified:
        return RuleOutcome.NEEDS_REVIEW, f"unverified evidence: {', '.join(unverified)}"
    return None


@rule("credit_note_consistent")
def credit_note_consistent(data: ValidationInput) -> Verdict:
    draft = data.draft
    if draft.total.value < 0 and any(item.amount > 0 for item in draft.line_items):
        return RuleOutcome.FAIL, "negative total with positive line amounts"
    return None

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.schema import InvoiceDraft

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class EvidenceResult:
    field: str
    quote: str
    span: Span | None

    @property
    def verified(self) -> bool:
        return self.span is not None

    def to_row(self) -> dict[str, object]:
        return {
            "field": self.field,
            "quote": self.quote,
            "verified": self.verified,
            "start": self.span.start if self.span else None,
            "end": self.span.end if self.span else None,
            "line": self.span.line if self.span else None,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "EvidenceResult":
        span = (
            Span(start=row["start"], end=row["end"], line=row["line"])
            if row.get("start") is not None
            else None
        )
        return cls(field=row["field"], quote=row["quote"], span=span)


def _collapse_whitespace(text: str) -> tuple[str, list[int]]:
    """Returns the collapsed text and, per collapsed index, its index in the original."""
    chars: list[str] = []
    offsets: list[int] = []
    in_run = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_run and chars:
                chars.append(" ")
                offsets.append(i)
            in_run = True
            continue
        in_run = False
        chars.append(ch)
        offsets.append(i)
    return "".join(chars), offsets


def find_span(source: str, quote: str) -> Span | None:
    normalized_quote = _WHITESPACE.sub(" ", quote).strip()
    if not normalized_quote:
        return None
    normalized_source, offsets = _collapse_whitespace(source)
    index = normalized_source.find(normalized_quote)
    if index == -1:
        return None
    start = offsets[index]
    end = offsets[index + len(normalized_quote) - 1] + 1
    return Span(start=start, end=end, line=source.count("\n", 0, start) + 1)


def verify_draft(draft: InvoiceDraft, source: str) -> list[EvidenceResult]:
    return [
        EvidenceResult(field=name, quote=field.quote, span=find_span(source, field.quote))
        for name, field in draft.evidenced_fields().items()
    ]

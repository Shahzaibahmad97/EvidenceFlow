from __future__ import annotations

import re
from dataclasses import dataclass

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


def _normalize(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs, keeping a map from normalized index to source index."""
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
    """Locate a verbatim quote in the source. Whitespace-insensitive, never fuzzy."""
    normalized_quote = _WHITESPACE.sub(" ", quote).strip()
    if not normalized_quote:
        return None
    normalized_source, offsets = _normalize(source)
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

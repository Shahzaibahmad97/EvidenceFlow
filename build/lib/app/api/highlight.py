from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Segment:
    text: str
    field: str | None = None


def segments(source: str, evidence: list[dict[str, Any]]) -> list[Segment]:
    spans = sorted(
        (item for item in evidence if item.get("start") is not None),
        key=lambda item: (item["start"], -item["end"]),
    )
    result: list[Segment] = []
    cursor = 0
    for span in spans:
        start, end = span["start"], span["end"]
        if start < cursor:
            continue
        if start > cursor:
            result.append(Segment(source[cursor:start]))
        result.append(Segment(source[start:end], span["field"]))
        cursor = end
    if cursor < len(source):
        result.append(Segment(source[cursor:]))
    return result

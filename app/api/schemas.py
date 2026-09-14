from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)


class DocumentSummary(BaseModel):
    id: str
    filename: str
    status: str


class EvidenceView(BaseModel):
    field: str
    quote: str
    verified: bool
    start: int | None = None
    end: int | None = None
    line: int | None = None


class ExtractionView(BaseModel):
    id: str
    status: str
    schema_version: str
    payload_hash: str | None = None
    draft: dict[str, Any] | None = None
    evidence: list[EvidenceView] = []
    error_code: str | None = None
    error_detail: str | None = None
    model: str | None = None
    latency_ms: int | None = None


class EventView(BaseModel):
    type: str
    actor: str
    payload: dict[str, Any]
    created_at: str


class DocumentDetail(DocumentSummary):
    source_text: str
    extraction: ExtractionView | None = None
    events: list[EventView] = []

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.domain.events import DocumentStatus, EventType, ExtractionStatus, WriteStatus
from app.domain.jobs import DEFAULT_MAX_ATTEMPTS, JobStatus


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.RECEIVED)
    approved_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    extractions: Mapped[list["Extraction"]] = relationship(
        back_populates="document", order_by="Extraction.created_at"
    )


class Extraction(Base):
    __tablename__ = "extraction"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(16))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped[Document] = relationship(back_populates="extractions")

    @property
    def succeeded(self) -> bool:
        return self.status == ExtractionStatus.SUCCEEDED


class Approval(Base):
    __tablename__ = "approval"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("extraction.id"))
    payload_hash: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CrmWrite(Base):
    __tablename__ = "crm_write"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_crm_write_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("extraction.id"))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=WriteStatus.PENDING)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Job(Base):
    __tablename__ = "job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(16))
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_ATTEMPTS)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CrmRecordRow(Base):
    __tablename__ = "crm_record"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_crm_record_idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ValidationResult(Base):
    __tablename__ = "validation_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("extraction.id"), index=True)
    rule: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Event(Base):
    __tablename__ = "event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    extraction_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(48))
    actor: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


EVENT_TYPES = {member.value for member in EventType}

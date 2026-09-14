from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.approval import as_utc, now
from app.domain.jobs import (
    DEFAULT_LEASE,
    DEFAULT_MAX_ATTEMPTS,
    FailureKind,
    JobStatus,
    JobType,
    backoff,
    is_transient,
)
from app.repositories.models import Job

CLAIM_BATCH = 10


def enqueue(
    session: Session,
    *,
    type: JobType,
    document_id: str,
    run_at: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Job:
    job = Job(
        type=type.value,
        document_id=document_id,
        run_at=run_at or now(),
        max_attempts=max_attempts,
    )
    session.add(job)
    session.flush()
    return job


def claim(session: Session, *, worker_id: str, lease: timedelta = DEFAULT_LEASE) -> Job | None:
    moment = now()
    for job_id in _claimable_ids(session, moment):
        claimed = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
            .where(Job.lease_expires_at.is_(None) | (Job.lease_expires_at <= moment))
            .values(
                status=JobStatus.RUNNING,
                locked_by=worker_id,
                lease_expires_at=moment + lease,
                attempts=Job.attempts + 1,
                updated_at=moment,
            )
        )
        if claimed.rowcount == 1:
            session.flush()
            session.expire_all()
            return session.get(Job, job_id)
    return None


def _claimable_ids(session: Session, moment: datetime) -> list[str]:
    stmt = (
        select(Job.id)
        .where(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .where(Job.run_at <= moment)
        .where(Job.lease_expires_at.is_(None) | (Job.lease_expires_at <= moment))
        .order_by(Job.run_at, Job.created_at)
        .limit(CLAIM_BATCH)
    )
    if session.bind.dialect.supports_for_update_of or session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    return list(session.scalars(stmt))


def succeed(session: Session, job: Job) -> Job:
    job.status = JobStatus.SUCCEEDED
    job.lease_expires_at = None
    job.locked_by = None
    job.last_error = None
    job.updated_at = now()
    session.flush()
    return job


def fail(session: Session, job: Job, error: Exception) -> Job:
    moment = now()
    job.last_error = f"{getattr(error, 'code', type(error).__name__)}: {error}"
    job.lease_expires_at = None
    job.locked_by = None
    job.updated_at = moment

    if not is_transient(error):
        job.status = JobStatus.FAILED
        job.failure_kind = FailureKind.PERMANENT
    elif job.attempts >= job.max_attempts:
        job.status = JobStatus.FAILED
        job.failure_kind = FailureKind.TRANSIENT_EXHAUSTED
    else:
        job.status = JobStatus.PENDING
        job.run_at = moment + backoff(job.attempts)
    session.flush()
    return job


def reclaim_expired(session: Session) -> int:
    moment = now()
    result = session.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.lease_expires_at <= moment)
        .values(status=JobStatus.PENDING, locked_by=None, lease_expires_at=None, updated_at=moment)
    )
    session.flush()
    return result.rowcount


def review_queue(session: Session) -> list[Job]:
    return list(
        session.scalars(
            select(Job).where(Job.status == JobStatus.FAILED).order_by(Job.updated_at.desc())
        )
    )


def lease_is_live(job: Job) -> bool:
    return job.lease_expires_at is not None and as_utc(job.lease_expires_at) > now()

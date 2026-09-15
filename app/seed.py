from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.domain.jobs import JobType
from app.repositories import documents as repo
from app.repositories.session import session_scope
from app.workflows import queue

SEED_NAMESPACE = uuid.UUID("6f0a1e64-2b3a-5c7d-9e10-4f5a6b7c8d90")


def seeded_document_id(filename: str) -> str:
    """Stable across reseeds, so a link to a document survives a restart."""
    return str(uuid.uuid5(SEED_NAMESPACE, filename))


def seed_documents(factory: sessionmaker[Session], directories: tuple[Path, ...]) -> int:
    with session_scope(factory) as session:
        if repo.list_documents(session):
            return 0
        paths = sorted(path for directory in directories for path in directory.glob("*.txt"))
        for path in paths:
            document = repo.create_document(
                session,
                filename=path.name,
                source_text=path.read_text(),
                document_id=seeded_document_id(path.name),
            )
            queue.enqueue(session, type=JobType.EXTRACT, document_id=document.id)
        return len(paths)

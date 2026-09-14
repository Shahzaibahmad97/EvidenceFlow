from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.domain.jobs import JobType
from app.repositories import documents as repo
from app.repositories.session import session_scope
from app.workflows import queue


def seed_documents(factory: sessionmaker[Session], directories: tuple[Path, ...]) -> int:
    with session_scope(factory) as session:
        if repo.list_documents(session):
            return 0
        paths = sorted(path for directory in directories for path in directory.glob("*.txt"))
        for path in paths:
            document = repo.create_document(
                session, filename=path.name, source_text=path.read_text()
            )
            queue.enqueue(session, type=JobType.EXTRACT, document_id=document.id)
        return len(paths)

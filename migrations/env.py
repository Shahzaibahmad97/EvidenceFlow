from __future__ import annotations

from alembic import context
from sqlalchemy import pool

from app.config import Settings
from app.repositories.models import Base
from app.repositories.session import build_engine

target_metadata = Base.metadata


def _database_url() -> str:
    return context.get_x_argument(as_dictionary=True).get(
        "database_url", Settings.from_env().database_url
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

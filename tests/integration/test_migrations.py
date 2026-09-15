from __future__ import annotations

from dataclasses import replace

from sqlalchemy import inspect

from app.migrate import upgrade_to_head
from app.repositories.models import Base
from app.repositories.session import build_engine, build_session_factory

IGNORED_TABLES = {"alembic_version"}


def _shape(engine) -> dict[str, dict[str, object]]:
    inspector = inspect(engine)
    return {
        table: {
            "columns": {
                column["name"]: str(column["type"]).upper()
                for column in inspector.get_columns(table)
            },
            "unique": sorted(
                tuple(sorted(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table)
            ),
            "primary_key": sorted(inspector.get_pk_constraint(table)["constrained_columns"]),
        }
        for table in inspector.get_table_names()
        if table not in IGNORED_TABLES
    }


def test_migrations_produce_the_same_schema_as_the_models(tmp_path, settings):
    migrated_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    upgrade_to_head(migrated_url)

    build_session_factory(replace(settings, database_url=f"sqlite:///{tmp_path / 'created.db'}"))

    migrated = _shape(build_engine(migrated_url))
    created = _shape(build_engine(f"sqlite:///{tmp_path / 'created.db'}"))

    assert set(migrated) == set(Base.metadata.tables)
    assert migrated == created


def test_migrating_twice_is_a_no_op(tmp_path):
    url = f"sqlite:///{tmp_path / 'twice.db'}"

    upgrade_to_head(url)
    upgrade_to_head(url)

    assert "document" in _shape(build_engine(url))


def test_auto_create_can_be_turned_off(tmp_path, settings):
    url = f"sqlite:///{tmp_path / 'empty.db'}"

    build_session_factory(replace(settings, database_url=url, auto_create_schema=False))

    assert _shape(build_engine(url)) == {}

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.cmd_opts = type("Options", (), {"x": [f"database_url={database_url}"]})()
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def main() -> None:
    url = Settings.from_env().database_url
    upgrade_to_head(url)
    print(f"schema at head: {url.split('@')[-1]}")


if __name__ == "__main__":
    main()

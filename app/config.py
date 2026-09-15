from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_FIXTURE_DIR = str(Path(__file__).resolve().parents[1] / "tests" / "fixtures")


@dataclass(frozen=True)
class Settings:
    database_url: str
    provider: str
    openai_model: str
    request_timeout_seconds: float
    run_worker: bool
    seed_on_start: bool
    fixture_dir: Path
    auto_create_schema: bool
    rate_limit_per_minute: int
    max_body_bytes: int

    @property
    def fixture_dirs(self) -> tuple[Path, ...]:
        return (self.fixture_dir / "invoices", self.fixture_dir / "held_out")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("EVIDENCEFLOW_DATABASE_URL", "sqlite:///./evidenceflow.db"),
            provider=os.getenv("EVIDENCEFLOW_PROVIDER", "fake"),
            openai_model=os.getenv("EVIDENCEFLOW_OPENAI_MODEL", "gpt-4.1-2025-04-14"),
            request_timeout_seconds=float(os.getenv("EVIDENCEFLOW_TIMEOUT_SECONDS", "60")),
            run_worker=os.getenv("EVIDENCEFLOW_RUN_WORKER", "false").lower() == "true",
            seed_on_start=os.getenv("EVIDENCEFLOW_SEED_ON_START", "false").lower() == "true",
            fixture_dir=Path(os.getenv("EVIDENCEFLOW_FIXTURE_DIR", DEFAULT_FIXTURE_DIR)),
            auto_create_schema=os.getenv("EVIDENCEFLOW_AUTO_CREATE_SCHEMA", "true").lower()
            == "true",
            rate_limit_per_minute=int(os.getenv("EVIDENCEFLOW_RATE_LIMIT_PER_MINUTE", "60")),
            max_body_bytes=int(os.getenv("EVIDENCEFLOW_MAX_BODY_BYTES", str(256 * 1024))),
        )

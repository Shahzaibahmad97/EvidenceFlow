from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    provider: str
    openai_model: str
    request_timeout_seconds: float
    run_worker: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("EVIDENCEFLOW_DATABASE_URL", "sqlite:///./evidenceflow.db"),
            provider=os.getenv("EVIDENCEFLOW_PROVIDER", "fake"),
            openai_model=os.getenv("EVIDENCEFLOW_OPENAI_MODEL", "gpt-4.1-2025-04-14"),
            request_timeout_seconds=float(os.getenv("EVIDENCEFLOW_TIMEOUT_SECONDS", "60")),
            run_worker=os.getenv("EVIDENCEFLOW_RUN_WORKER", "false").lower() == "true",
        )

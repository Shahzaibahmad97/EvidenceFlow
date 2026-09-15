from __future__ import annotations

import signal
import threading

from app.api.app import build_provider
from app.config import Settings
from app.repositories.session import build_session_factory
from app.workflows.worker import Worker


def main() -> None:
    settings = Settings.from_env()
    factory = build_session_factory(settings)
    worker = Worker(
        session_factory=factory,
        provider=build_provider(settings),
        worker_id=f"worker-{threading.get_ident()}",
    )
    stop = threading.Event()
    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, lambda *_: stop.set())
    worker.run_forever(stop)


if __name__ == "__main__":
    main()

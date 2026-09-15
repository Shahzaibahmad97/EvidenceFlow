#!/bin/sh
# Single-process start: migrate, then serve. Used where a host gives one process
# and no separate release step. Compose runs migrations as their own service.
set -e
python -m app.migrate
exec uvicorn app.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"

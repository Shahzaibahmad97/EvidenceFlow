FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVIDENCEFLOW_PROVIDER=fake \
    EVIDENCEFLOW_RUN_WORKER=true \
    EVIDENCEFLOW_SEED_ON_START=true \
    EVIDENCEFLOW_FIXTURE_DIR=/app/tests/fixtures

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[postgres]"

COPY tests/fixtures ./tests/fixtures

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

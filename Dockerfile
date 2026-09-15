ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVIDENCEFLOW_PROVIDER=fake \
    EVIDENCEFLOW_RUN_WORKER=true \
    EVIDENCEFLOW_SEED_ON_START=true \
    EVIDENCEFLOW_FIXTURE_DIR=/app/tests/fixtures \
    EVIDENCEFLOW_DATABASE_URL=sqlite:////home/user/data/evidenceflow.db \
    HOME=/home/user \
    PORT=8000

RUN useradd --create-home --uid 1000 user && mkdir -p /home/user/data && chown -R user /home/user

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[postgres]"

COPY tests/fixtures ./tests/fixtures
COPY scripts/start.sh ./scripts/start.sh

USER user

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health')"

CMD ["./scripts/start.sh"]

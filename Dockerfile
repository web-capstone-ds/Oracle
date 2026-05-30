FROM python:3.11-slim AS runtime

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY sql ./sql

RUN python -m venv "$VIRTUAL_ENV" \
 && pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

STOPSIGNAL SIGTERM

CMD ["python", "-m", "main"]

FROM runtime AS test

ENV PYTHONPATH=/app:/app/src

COPY auth ./auth
COPY tests ./tests

RUN pip install --no-cache-dir -e '.[dev]'

CMD ["python", "-m", "pytest"]

FROM runtime AS final

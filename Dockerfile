FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY sql ./sql

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

STOPSIGNAL SIGTERM

CMD ["python", "-m", "main"]

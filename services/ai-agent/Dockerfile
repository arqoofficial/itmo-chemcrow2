FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/ai-agent/pyproject.toml .
COPY services/ai-agent/app ./app
COPY services/ai-agent/scripts ./scripts
COPY scripts/download_embedding_model.py ./scripts/download_embedding_model.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]

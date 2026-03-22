# Must be built with context = repo root: docker build -f services/pdf-parser/Dockerfile .
# See compose.yml pdf-parser service (context: .)
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    libxcb1 libxrender1 libxext6 libx11-6 libglib2.0-0 libgl1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY services/pdf-parser/pyproject.toml .
COPY services/pdf-parser/app ./app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

# Pre-download spaCy models
RUN python -m spacy download en_core_web_sm && \
    python -m spacy download ru_core_news_sm

EXPOSE 8300

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]

FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/ai-agent/pyproject.toml .
COPY services/ai-agent/app ./app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

# Pre-download the Nomic embedding model into the image layer.
#
# This is a plain RUN (not --mount=type=cache) intentionally: BuildKit cache
# mounts are ephemeral scratch space that exists only during the build and is
# NOT committed to the final image layer.  Using --mount=type=cache here would
# download the model into the build cache but discard it from the image, so
# the container would fetch the weights from HuggingFace Hub on every cold
# start.  A plain RUN writes the downloaded files into the image filesystem,
# making the model available offline at inference time.
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]

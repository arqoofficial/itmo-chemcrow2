# Retrosynthesis Service

Retrosynthetic pathway planning using AiZynthFinder (USPTO reaction templates, ZINC stock).

## Dev Commands

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8052 --reload
```

## Setup Requirement

This service requires external data at `data/aizynthfinder/` (models, templates, stock).
See `docs/data-aizynthfinder.md` for download instructions before running.

Config path: `AZF_CONFIG_PATH=/data/aizynthfinder/config.yml`

## Project Structure

```
app/
├── main.py      # FastAPI endpoints for retrosynthesis planning
├── config.py    # AiZynthFinder config loading (reads AZF_CONFIG_PATH)
├── schemas.py   # Request/response models (SMILES in, route tree out)
└── engines/     # AiZynthFinder engine wrappers
```

## Gotchas

- AiZynthFinder tree search can take 30–120 seconds — the backend polls via TaskJob; don't reduce timeouts
- Volume `data/aizynthfinder/` is mounted **read-only** in compose — don't try to write there
- The Dockerfile installs RDKit graphics libs (`libxrender`, `libxext`) — required for AiZynthFinder
- This service has no Redis dependency — it's compute-only, called synchronously by Celery workers

# ADMET microservice

FastAPI microservice that accepts a single-molecule SMILES string and returns:

- RDKit descriptors
- heuristic ADMET proxy predictions
- success / error information in a stable JSON envelope

## Important note

This service does **not** perform validated ADMET modeling. It derives descriptor-based **heuristic proxy predictions** from RDKit features. That makes it useful for agent tooling, quick screening, ranking, and demos, but not as a substitute for experimental data or a trained QSAR model.

## Project structure

```text
app/
  __init__.py
  admet.py
  main.py
  schemas.py
demo/
  agent_demo.py
Dockerfile
docker-compose.yml
pyproject.toml
tool_definition.json
```

## Local development with uv

Create the environment and install the API dependencies:

```bash
uv sync
```

Run the API:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8144
```

Open docs:

```text
http://127.0.0.1:8144/docs
```

## Run with Docker Compose

```bash
docker compose up --build
```

## Example request

```bash
curl -X POST http://127.0.0.1:8144/v1/admet \
  -H 'Content-Type: application/json' \
  -d '{
    "smiles": "CC(=O)Oc1ccccc1C(=O)O",
    "allow_explicit_h": false,
    "max_heavy_atoms": 200,
    "include_descriptors": true
  }'
```

## Example response shape

```json
{
  "success": true,
  "input_smiles": "CC(=O)Oc1ccccc1C(=O)O",
  "canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O",
  "warnings": [],
  "error": null,
  "descriptors": {
    "MolWt": 180.159,
    "MolLogP": 1.31,
    "TPSA": 63.6
  },
  "admet": {
    "absorption": {
      "oral_absorption": {
        "label": "high",
        "score": 0.86,
        "rationale": "..."
      }
    }
  },
  "meta": {
    "prediction_kind": "descriptor-based heuristic proxy"
  }
}
```

## Demo agent with LangChain + Langfuse

Install the optional demo dependencies too:

```bash
uv sync --extra demo
```

Set environment variables:

```bash
cp .env.example .env
```

Run the demo from the console:

```bash
uv run admet-agent-demo "Estimate ADMET for aspirin with SMILES CC(=O)Oc1ccccc1C(=O)O"
```

The demo defines a tool named `SMILES_to_ADMET`, calls the FastAPI service over HTTP, and lets a LangChain agent decide when to use it. If `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` are set, traces are sent to Langfuse.

## Tool definition for LLMs

The OpenAI-style function schema is included in `tool_definition.json`.

## Suggested next step

When you are ready for real ADMET prediction, replace the heuristics inside `app/admet.py` with a trained model or an ensemble of property-specific models while keeping the API contract unchanged.

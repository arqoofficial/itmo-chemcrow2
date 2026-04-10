# RAG Integration Design

**Date:** 2026-03-21
**Branch:** seva-rag-proto

## Background

The `seva-rag-proto` branch introduced a hybrid RAG system embedded directly inside the `ai-agent` service. It adds two LangChain tools (`rag_search`, `literature_citation_search`) backed by a BM25 + Nomic dense retriever with Reciprocal Rank Fusion. The tools are already registered in the tool registry and the agent system prompt is updated.

## Goals

1. Make the service deployable via Docker Compose (model pre-baked, data bind-mounted).
2. Restructure the data layout and retriever internals to support multiple corpus scopes in the future (e.g. per-conversation uploaded articles), without implementing scope injection yet.

## Future RAG scope model (context, not in scope for this PR)

In the future, when a user uploads a document in a conversation, a parser will create a new corpus scope combining the base corpus + uploaded document. The agent calls `rag_search` identically — the active scope is injected automatically by the infrastructure, invisible to the LLM. The mechanism for injection is TBD; this design only prepares the data structure and retriever registry.

---

## Design

### 1. Data directory restructure

Move from a flat layout to a source-keyed layout:

**Before:**
```
data-rag/
  corpus_raw/
  corpus_processed/
  indexes/
    bm25_index.json
    nomic_dense/
  benchmarks/
```

**After:**
```
data-rag/
  sources/
    default/
      corpus_raw/       ← current corpus_raw contents
      corpus_processed/ ← current corpus_processed contents
      indexes/
        bm25_index.json
        nomic_dense/
  benchmarks/           ← stays at top level (not source-specific)
```

Future corpus scopes (e.g. per-conversation uploaded articles) are added as siblings of `default/` under `sources/`.

### 2. Config — updated path defaults

Update `config.py`. All four derived path settings are rewritten to use the `sources/default/` layout. A follow-up PR should remove the four derived settings in favour of pure dynamic derivation from `RAG_SOURCES_DIR / scope`, but for now both representations are kept for backward compatibility with the existing `build_or_load` call sites.

```python
RAG_DATA_DIR: str = "app/data-rag"
RAG_SOURCES_DIR: str = "app/data-rag/sources"
RAG_DEFAULT_SOURCE: str = "default"
# Derived paths for the default source (to be removed once scope derivation is the only path):
RAG_CORPUS_RAW_DIR: str = "app/data-rag/sources/default/corpus_raw"
RAG_CORPUS_PROCESSED_DIR: str = "app/data-rag/sources/default/corpus_processed"
RAG_BM25_INDEX_PATH: str = "app/data-rag/sources/default/indexes/bm25_index.json"
RAG_DENSE_INDEX_DIR: str = "app/data-rag/sources/default/indexes/nomic_dense"
```

### 3. Retriever registry — replace global singleton

**Before:** `_HYBRID_RETRIEVER: BM25DenseRankFusionRetriever | None = None` — a single global retriever.

**After:** A scope-keyed registry with a single lock guarding all writes:

```python
_RETRIEVER_REGISTRY: dict[str, BM25DenseRankFusionRetriever] = {}
_REGISTRY_LOCK = Lock()

def _get_retriever_for_scope(scope: str = "default") -> BM25DenseRankFusionRetriever:
    with _REGISTRY_LOCK:
        if scope not in _RETRIEVER_REGISTRY:
            _RETRIEVER_REGISTRY[scope] = _build_hybrid_retriever(scope)
    return _RETRIEVER_REGISTRY[scope]
```

The lock always guards both the read and the write to avoid the unsynchronized-read bug in the existing double-checked locking pattern. Index building is a one-time startup cost per scope, so lock contention is not a concern.

**Path resolution contract:** `_build_hybrid_retriever(scope)` always derives all paths from `Path(settings.RAG_SOURCES_DIR) / scope`:

```python
def _build_hybrid_retriever(scope: str = "default") -> BM25DenseRankFusionRetriever:
    source_dir = Path(settings.RAG_SOURCES_DIR) / scope
    if not source_dir.exists():
        raise FileNotFoundError(f"RAG source directory not found: {source_dir}")

    raw_corpus_dir = source_dir / "corpus_raw"
    processed_corpus_dir = source_dir / "corpus_processed"
    bm25_index_path = source_dir / "indexes" / "bm25_index.json"
    dense_index_dir = source_dir / "indexes" / "nomic_dense"
    ...
```

For the `default` scope, these paths resolve identically to the existing settings values. The four derived `config.py` settings (`RAG_CORPUS_RAW_DIR` etc.) are no longer used by `_build_hybrid_retriever` after this change.

The tools call `_get_retriever_for_scope("default")` for now. When scope injection is implemented, they will receive the scope from the execution context instead.

### 4. Fix `_format_citation_results` source path

The hardcoded path at `rag.py:650`:

```python
source = f"app/data-rag/corpus_raw/{hit.doc_id}.md"
```

Will be actively wrong after the data restructure. `_load_dual_corpus_documents` already sets `"raw_source"` on `Document.metadata`, but `BM25DenseRankFusionRetriever.retrieve()` constructs `RetrievalResult` with its own fixed metadata dict and never forwards document-level metadata — so `hit.metadata.get("raw_source")` would always return `None`.

Two changes are needed:

**a) Forward document metadata in `BM25DenseRankFusionRetriever.retrieve()`**

Change the `DocumentResolver` type to also carry metadata:

```python
DocumentResolver = Callable[[str], tuple[str, dict[str, Any]] | None]
```

Update `_build_raw_document_resolver` to return `(text, {"raw_source": raw_doc.metadata["source"]})` — note that `raw_doc.metadata` contains `"source"` (the raw file path), so we explicitly remap it to `"raw_source"` to match what `_format_citation_results` expects. Update `BM25DenseRankFusionRetriever.retrieve()` to merge the resolved doc metadata into `RetrievalResult.metadata`:

```python
for doc_id, score in ranked_ids:
    text, doc_meta = "", {}
    if self._document_resolver is not None:
        resolved = self._document_resolver(doc_id)
        if resolved is not None:
            text, doc_meta = resolved
    merged_meta = {**doc_meta, "retriever": "bm25_dense_rrf", ...}
    results.append(RetrievalResult(doc_id=doc_id, score=score, text=text, metadata=merged_meta))
```

**b) Use `raw_source` in `_format_citation_results`**

```python
source = hit.metadata.get("raw_source") or f"(unknown source for {hit.doc_id})"
```

No hardcoded fallback path — if `raw_source` is missing, surface it explicitly rather than silently returning a wrong path.

### 5. Dockerfile — pre-download the embedding model with BuildKit cache

Add a `RUN` step after `uv pip install` that bakes the Nomic model into the image. Use a BuildKit cache mount so repeated local builds don't re-download the ~274 MB model:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/huggingface \
    python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"
```

The model lives permanently in `/root/.cache/huggingface` inside the image layer. **No volume is mounted over this path.** The BuildKit cache layer speeds up iterative rebuilds but is not present in the final pushed image.

### 6. Exclude `data-rag` from the Docker build context

Add to the root `.dockerignore`:

```
services/ai-agent/app/data-rag/
```

The `COPY services/ai-agent/app ./app` line is unchanged. The corpus arrives at runtime via bind mount.

### 7. compose.yml — bind mount, env vars, watch ignore

Add to the `ai-agent` service:

```yaml
volumes:
  # Note: WORKDIR is /app and app code lives at /app/app/, so data-rag is at /app/app/data-rag
  - ./services/ai-agent/app/data-rag:/app/app/data-rag

develop:
  watch:
    - path: ./services/ai-agent
      action: sync
      target: /app
      ignore:
        - .venv
        - app/data-rag   # corpus managed via bind mount, not file watch

environment:
  - RAG_ENABLED=true
  - RAG_FORCE_REBUILD_INDEXES=false
```

The remaining RAG path settings use correct defaults from `config.py`.

**Auto-rebuild:** Fingerprint-based rebuild is already implemented in `BM25Retriever` and `NomicDenseRetriever`. Adding/modifying `.md` files triggers a rebuild on next container start. Rebuilt indexes are written back to the bind-mounted host directory.

**Startup latency note:** The service healthcheck covers HTTP readiness only, not RAG readiness. First `rag_search` call will cold-load the embedding model and indexes (~15–60 s). This is accepted; a warm-up step is deferred to a future PR.

### 8. compose.production.yml — mirror bind mount and env vars

Mirror the bind mount and the two RAG env vars into the `ai-agent` service in `compose.production.yml`.

### 9. Frontend — RAG indicator in ToolCallCard

In `frontend/src/components/Chat/ToolCallCard.tsx`, detect when the tool name is `rag_search` or `literature_citation_search` and render a small "RAG" badge/chip alongside the tool call card header.

---

## Files to change

| File | Change |
|------|--------|
| `services/ai-agent/app/data-rag/` | Move corpus/indexes into `sources/default/` subdirectory |
| `.gitignore` | Exclude generated index files: `services/ai-agent/app/data-rag/sources/*/indexes/`; corpus markdown files in `corpus_raw/` and `corpus_processed/` are tracked in git as seed data |
| `services/ai-agent/app/config.py` | Update path defaults; add `RAG_SOURCES_DIR`, `RAG_DEFAULT_SOURCE` |
| `services/ai-agent/app/tools/rag.py` | Replace singleton with scope registry; fix `_build_hybrid_retriever` to use `scope` arg; update `DocumentResolver` type and `_build_raw_document_resolver` to return `(text, metadata)`; update `BM25DenseRankFusionRetriever.retrieve()` to forward doc metadata; fix citation path |
| `services/ai-agent/Dockerfile` | Add model pre-download `RUN` step with BuildKit cache mount |
| `.dockerignore` | Exclude `services/ai-agent/app/data-rag/` |
| `compose.yml` | Add bind mount, RAG env vars, add `app/data-rag` to watch ignore |
| `compose.production.yml` | Mirror bind mount and RAG env vars |
| `frontend/src/components/Chat/ToolCallCard.tsx` | Add RAG badge for RAG tool names |

## Out of scope

- Scope injection mechanism (per-conversation retriever selection)
- User-uploaded document parsing and indexing pipeline
- Removing the four derived `RAG_*` path settings from config (deferred; noted in section 2)
- Dedicated RAG search page in the frontend

# RAG Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the existing RAG tools into the Docker Compose stack, restructure the data layout for future multi-scope support, and add a RAG indicator badge in the frontend.

**Architecture:** RAG lives inside the `ai-agent` service — no separate container. The Nomic embedding model is baked into the Docker image at build time. The chemistry corpus is bind-mounted from the host repo at runtime. The retriever singleton is replaced with a scope-keyed registry to prepare for per-conversation document scopes.

**Tech Stack:** Python 3.11, uv, FastAPI, LangChain, sentence-transformers (nomic-embed-text-v1.5), Docker/Compose, React/TypeScript

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `services/ai-agent/app/data-rag/sources/default/` | Create (move) | New home for corpus and indexes |
| `.gitignore` | Modify | Exclude regenerated index files |
| `services/ai-agent/app/config.py` | Modify | Add `RAG_SOURCES_DIR`, `RAG_DEFAULT_SOURCE`; update derived path defaults |
| `services/ai-agent/app/tools/rag.py` | Modify | Scope registry, DocumentResolver metadata, citation path fix |
| `services/ai-agent/tests/test_rag.py` | Modify | Update monkeypatching targets; update citation assertion |
| `services/ai-agent/Dockerfile` | Modify | Pre-download Nomic model with BuildKit cache |
| `.dockerignore` | Modify | Exclude `services/ai-agent/app/data-rag/` from build context |
| `compose.yml` | Modify | Bind mount data-rag, RAG env vars, watch ignore |
| `compose.production.yml` | Modify | Mirror bind mount and env vars |
| `frontend/src/components/Chat/ToolCallCard.tsx` | Modify | RAG badge for RAG tool calls |

---

## Task 1: Restructure data directory

**Files:**
- Move: `services/ai-agent/app/data-rag/corpus_raw/` → `services/ai-agent/app/data-rag/sources/default/corpus_raw/`
- Move: `services/ai-agent/app/data-rag/corpus_processed/` → `services/ai-agent/app/data-rag/sources/default/corpus_processed/`
- Move: `services/ai-agent/app/data-rag/indexes/` → `services/ai-agent/app/data-rag/sources/default/indexes/`
- Modify: `.gitignore`

- [ ] **Step 1: Create the new directory structure and move files**

```bash
mkdir -p services/ai-agent/app/data-rag/sources/default
mv services/ai-agent/app/data-rag/corpus_raw     services/ai-agent/app/data-rag/sources/default/
mv services/ai-agent/app/data-rag/corpus_processed services/ai-agent/app/data-rag/sources/default/
mv services/ai-agent/app/data-rag/indexes        services/ai-agent/app/data-rag/sources/default/
```

Verify:
```bash
ls services/ai-agent/app/data-rag/sources/default/
# Expected: corpus_raw  corpus_processed  indexes
ls services/ai-agent/app/data-rag/sources/default/corpus_raw/ | head -3
# Expected: chapter_01_*.md  chapter_02_*.md  ...
```

- [ ] **Step 2: Add index files to `.gitignore`**

Append to the root `.gitignore`:

```
# RAG index files (auto-generated, do not commit)
services/ai-agent/app/data-rag/sources/*/indexes/
```

Corpus markdown files (`corpus_raw/`, `corpus_processed/`) are seed data and remain tracked.

- [ ] **Step 3: Commit**

```bash
git add services/ai-agent/app/data-rag/ .gitignore
git commit -m "refactor(rag): restructure data-rag into sources/default layout for multi-scope support"
```

---

## Task 2: Update config.py

**Files:**
- Modify: `services/ai-agent/app/config.py`

- [ ] **Step 1: Update the RAG settings block in `config.py`**

Replace the existing RAG settings block (lines 47–59) with:

```python
# RAG settings
RAG_ENABLED: bool = True
RAG_DATA_DIR: str = "app/data-rag"           # kept: used by evaluate_rag.py for benchmarks
RAG_SOURCES_DIR: str = "app/data-rag/sources"
RAG_DEFAULT_SOURCE: str = "default"
# Derived paths for the default source
# TODO: remove once _build_hybrid_retriever derives all paths from RAG_SOURCES_DIR/scope
RAG_CORPUS_RAW_DIR: str = "app/data-rag/sources/default/corpus_raw"
RAG_CORPUS_PROCESSED_DIR: str = "app/data-rag/sources/default/corpus_processed"
RAG_BM25_INDEX_PATH: str = "app/data-rag/sources/default/indexes/bm25_index.json"
RAG_DENSE_INDEX_DIR: str = "app/data-rag/sources/default/indexes/nomic_dense"
RAG_FORCE_REBUILD_INDEXES: bool = False
RAG_DENSE_MATRYOSHKA_DIM: int = 512
RAG_DENSE_BATCH_SIZE: int = 16
RAG_RRF_K: int = 60
RAG_BM25_WEIGHT: float = 1.0
RAG_DENSE_WEIGHT: float = 1.0
RAG_CANDIDATE_K: int = 20
```

`RAG_DATA_DIR` is still used by `services/ai-agent/scripts/evaluate_rag.py` to locate `benchmarks/`. Keep it.

- [ ] **Step 2: Commit**

```bash
git add services/ai-agent/app/config.py
git commit -m "feat(rag): add RAG_SOURCES_DIR and RAG_DEFAULT_SOURCE config settings"
```

---

## Task 3: Refactor rag.py — scope registry + metadata forwarding + citation fix

**Files:**
- Modify: `services/ai-agent/app/tools/rag.py`
- Modify: `services/ai-agent/tests/test_rag.py`

This task touches several interconnected parts of `rag.py`. Work through them in order.

### 3a — Update `DocumentResolver` type and `BM25DenseRankFusionRetriever.retrieve()`

- [ ] **Step 1: Write failing tests for metadata forwarding**

Add to `services/ai-agent/tests/test_rag.py`:

```python
def test_bm25_dense_rrf_retrieve_forwards_doc_metadata():
    """retrieve() must forward raw_source from document resolver into RetrievalResult.metadata."""
    from app.tools.rag import (
        BM25DenseRankFusionRetriever,
        BM25Retriever,
        NomicDenseRetriever,
        Document,
    )

    class _StubBM25:
        def retrieve_ids(self, query, top_k=5):
            return [("doc_01", 0.9)]

        def build_or_load(self, docs, force_rebuild=False):
            pass

    class _StubDense:
        def retrieve_ids(self, query, top_k=5):
            return [("doc_01", 0.8)]

        def build_or_load(self, docs, force_rebuild=False):
            pass

    def resolver(doc_id):
        return ("some text about chemistry", {"raw_source": "app/data-rag/sources/default/corpus_raw/doc_01.md"})

    retriever = BM25DenseRankFusionRetriever(
        bm25_retriever=_StubBM25(),
        dense_retriever=_StubDense(),
        document_resolver=resolver,
    )
    results = retriever.retrieve("test query", top_k=1)

    assert len(results) == 1
    assert results[0].text == "some text about chemistry"
    assert results[0].metadata["raw_source"] == "app/data-rag/sources/default/corpus_raw/doc_01.md"
    assert results[0].metadata["retriever"] == "bm25_dense_rrf"
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd services/ai-agent && uv run pytest tests/test_rag.py::test_bm25_dense_rrf_retrieve_forwards_doc_metadata -v
```

Expected: `FAILED` — `TypeError` because resolver still returns `str`, not `tuple`.

- [ ] **Step 3: Update `DocumentResolver` type alias in `rag.py` (line 50)**

```python
DocumentResolver = Callable[[str], tuple[str, dict[str, Any]] | None]
```

- [ ] **Step 4: Update `BM25DenseRankFusionRetriever.retrieve()` (lines 458–480)**

```python
def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
    ranked_ids = self.retrieve_ids(query, top_k=top_k)
    results: list[RetrievalResult] = []
    for doc_id, score in ranked_ids:
        text = ""
        doc_meta: dict[str, Any] = {}
        if self._document_resolver is not None:
            resolved = self._document_resolver(doc_id)
            if resolved is not None:
                text, doc_meta = resolved
        results.append(
            RetrievalResult(
                doc_id=doc_id,
                score=float(score),
                text=text,
                metadata={
                    **doc_meta,
                    "retriever": "bm25_dense_rrf",
                    "rrf_k": self.rrf_k,
                    "bm25_weight": self.bm25_weight,
                    "dense_weight": self.dense_weight,
                },
            )
        )
    return results
```

- [ ] **Step 5: Run test — expect PASS**

```bash
cd services/ai-agent && uv run pytest tests/test_rag.py::test_bm25_dense_rrf_retrieve_forwards_doc_metadata -v
```

### 3b — Update `_build_raw_document_resolver`

- [ ] **Step 6: Update `_build_raw_document_resolver` (lines 553–558)**

```python
def _build_raw_document_resolver(raw_docs_by_id: dict[str, Document]) -> DocumentResolver:
    def _resolve(doc_id: str) -> tuple[str, dict[str, Any]] | None:
        doc = raw_docs_by_id.get(doc_id)
        if doc is None:
            return None
        return (doc.text, {"raw_source": doc.metadata["source"]})

    return _resolve
```

### 3c — Replace singleton with scope registry and update `_build_hybrid_retriever`

- [ ] **Step 7: Replace module-level globals (lines 27–28)**

Remove both of these lines:
```python
_RETRIEVER_LOCK = Lock()
_HYBRID_RETRIEVER: BM25DenseRankFusionRetriever | None = None
```

Replace with:
```python
_RETRIEVER_REGISTRY: dict[str, BM25DenseRankFusionRetriever] = {}
_REGISTRY_LOCK = Lock()
```

- [ ] **Step 8: Update `_build_hybrid_retriever` to accept `scope` arg (lines 561–604)**

Replace the function signature and path derivation (keep the rest of the function body intact, only change how paths are obtained):

```python
def _build_hybrid_retriever(scope: str = "default") -> BM25DenseRankFusionRetriever:
    from app.config import settings

    source_dir = Path(settings.RAG_SOURCES_DIR) / scope
    if not source_dir.exists():
        raise FileNotFoundError(f"RAG source directory not found: {source_dir}")

    raw_corpus_dir = source_dir / "corpus_raw"
    processed_corpus_dir = source_dir / "corpus_processed"
    bm25_index_path = source_dir / "indexes" / "bm25_index.json"
    dense_index_dir = source_dir / "indexes" / "nomic_dense"

    if not raw_corpus_dir.exists():
        raise FileNotFoundError(f"RAG raw corpus directory not found: {raw_corpus_dir}")

    if not processed_corpus_dir.exists() or not any(processed_corpus_dir.glob("*.md")):
        logger.info("Preparing processed corpus in %s", processed_corpus_dir)
        _prepare_processed_corpus(raw_corpus_dir, processed_corpus_dir)

    processed_docs, raw_docs_by_id = _load_dual_corpus_documents(
        raw_corpus_dir=raw_corpus_dir,
        processed_corpus_dir=processed_corpus_dir,
    )
    resolver = _build_raw_document_resolver(raw_docs_by_id)

    bm25 = BM25Retriever(index_path=bm25_index_path, document_resolver=resolver)
    bm25.build_or_load(processed_docs, force_rebuild=settings.RAG_FORCE_REBUILD_INDEXES)

    dense = NomicDenseRetriever(
        matryoshka_dim=settings.RAG_DENSE_MATRYOSHKA_DIM,
        batch_size=settings.RAG_DENSE_BATCH_SIZE,
        index_dir=dense_index_dir,
        document_resolver=resolver,
    )
    dense.build_or_load(processed_docs, force_rebuild=settings.RAG_FORCE_REBUILD_INDEXES)

    return BM25DenseRankFusionRetriever(
        bm25_retriever=bm25,
        dense_retriever=dense,
        rrf_k=settings.RAG_RRF_K,
        bm25_weight=settings.RAG_BM25_WEIGHT,
        dense_weight=settings.RAG_DENSE_WEIGHT,
        candidate_k=settings.RAG_CANDIDATE_K,
        document_resolver=resolver,
    )
```

Note: `NomicDenseRetriever` also has a `document_resolver` parameter — pass it the same `resolver` so it can forward text+metadata consistently.

- [ ] **Step 9: Replace `_get_hybrid_retriever` with `_get_retriever_for_scope` (lines 607–615)**

```python
def _get_retriever_for_scope(scope: str = "default") -> BM25DenseRankFusionRetriever:
    with _REGISTRY_LOCK:
        if scope not in _RETRIEVER_REGISTRY:
            _RETRIEVER_REGISTRY[scope] = _build_hybrid_retriever(scope)
    return _RETRIEVER_REGISTRY[scope]
```

- [ ] **Step 10: Update `_run_rag_query` to call `_get_retriever_for_scope`**

In `_run_rag_query` (around line 667), change:
```python
retriever = _get_hybrid_retriever()
```
to:
```python
retriever = _get_retriever_for_scope(settings.RAG_DEFAULT_SOURCE)
```

### 3d — Fix `_format_citation_results`

- [ ] **Step 11: Fix the hardcoded source path in `_format_citation_results` (line 650)**

```python
source = hit.metadata.get("raw_source") or f"(unknown source for {hit.doc_id})"
```

### 3e — Update tests

- [ ] **Step 12: Update `test_rag.py` — fix monkeypatch targets and citation assertion**

The existing tests monkeypatch `rag._get_hybrid_retriever`. That function no longer exists; replace with `rag._get_retriever_for_scope`.

Also update `_FakeRetriever` to work with the new call signature (it now receives `scope` arg implicitly via `_get_retriever_for_scope("default")` — the tests monkeypatch at the `_get_retriever_for_scope` level, so no change to `_FakeRetriever` itself).

Update the two tests that reference `_get_hybrid_retriever`:

```python
def test_rag_search_happy_path_and_top_k_clamp(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    fake = _FakeRetriever()
    monkeypatch.setattr(rag, "_get_retriever_for_scope", lambda scope="default": fake)
    ...

def test_literature_citation_search_formats_structured_citations(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    fake = _FakeRetriever()
    monkeypatch.setattr(rag, "_get_retriever_for_scope", lambda scope="default": fake)
    ...
```

The citation test currently asserts:
```python
assert "source=app/data-rag/corpus_raw/chapter_01.md" in result
```

The fake retriever returns `RetrievalResult` with `metadata={}`, so `hit.metadata.get("raw_source")` is `None` and the fallback fires. Update the assertion:

```python
assert "source=(unknown source for chapter_01)" in result
```

Also update the missing-data test:
```python
def test_rag_search_missing_data(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    def _raise_missing(scope="default"):
        raise FileNotFoundError("app/data-rag/sources/default")

    monkeypatch.setattr(rag, "_get_retriever_for_scope", _raise_missing)
    ...
```

- [ ] **Step 13: Run all RAG tests — expect PASS**

```bash
cd services/ai-agent && uv run pytest tests/test_rag.py -v
```

Expected: all tests pass.

- [ ] **Step 14: Commit**

```bash
git add services/ai-agent/app/tools/rag.py services/ai-agent/tests/test_rag.py
git commit -m "refactor(rag): replace singleton with scope registry; forward doc metadata; fix citation path"
```

---

## Task 4: Dockerfile — pre-download Nomic model

**Files:**
- Modify: `services/ai-agent/Dockerfile`

- [ ] **Step 1: Add model pre-download after `uv pip install`**

The current Dockerfile ends with:
```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
```

Insert after the `uv pip install` step:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)"

EXPOSE 8100
```

This step writes the model (~274 MB) to `/root/.cache/huggingface` inside the image layer — it is present in the final image and available offline. **Do not use `--mount=type=cache` here**: a BuildKit cache mount is ephemeral and not committed to the image layer, so the model would not be present in the pushed image and the container would attempt to re-download at runtime. **No volume is mounted over `/root/.cache/huggingface` at runtime.**

This step will re-run (and re-download) on any rebuild that invalidates a prior layer. This is an accepted trade-off for having the model available offline.

- [ ] **Step 2: Commit**

```bash
git add services/ai-agent/Dockerfile
git commit -m "feat(rag): pre-download nomic-embed-text-v1.5 model during Docker image build"
```

---

## Task 5: Update `.dockerignore`

**Files:**
- Modify: `.dockerignore`

- [ ] **Step 1: Add data-rag exclusion**

Append to `.dockerignore`:

```
# RAG corpus is bind-mounted at runtime, not baked into the image
services/ai-agent/app/data-rag/
```

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: exclude data-rag from Docker build context (bind-mounted at runtime)"
```

---

## Task 6: Update compose.yml and compose.production.yml

**Files:**
- Modify: `compose.yml`
- Modify: `compose.production.yml`

- [ ] **Step 1: Update `ai-agent` service in `compose.yml`**

In `compose.yml`, the `ai-agent` service currently has:
```yaml
  ai-agent:
    build:
      context: .
      dockerfile: services/ai-agent/Dockerfile
    restart: unless-stopped
    ports:
      - "8100:8100"
    depends_on:
      redis:
        condition: service_healthy
    develop:
      watch:
        - path: ./services/ai-agent
          action: sync
          target: /app
          ignore:
            - .venv
        - path: ./services/ai-agent/pyproject.toml
          action: rebuild
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - BACKEND_URL=http://backend:8000
      - REACTION_PREDICT_URL=http://reaction-predict:8051
      - RETROSYNTHESIS_URL=http://retrosynthesis:8052
```

Add a `volumes` block and update `develop.watch.ignore` and `environment`:

```yaml
  ai-agent:
    build:
      context: .
      dockerfile: services/ai-agent/Dockerfile
    restart: unless-stopped
    ports:
      - "8100:8100"
    depends_on:
      redis:
        condition: service_healthy
    volumes:
      # WORKDIR=/app, app code at /app/app/ → data-rag resolves to /app/app/data-rag
      - ./services/ai-agent/app/data-rag:/app/app/data-rag
    develop:
      watch:
        - path: ./services/ai-agent
          action: sync
          target: /app
          ignore:
            - .venv
            - app/data-rag
        - path: ./services/ai-agent/pyproject.toml
          action: rebuild
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - BACKEND_URL=http://backend:8000
      - REACTION_PREDICT_URL=http://reaction-predict:8051
      - RETROSYNTHESIS_URL=http://retrosynthesis:8052
      - RAG_ENABLED=true
      - RAG_FORCE_REBUILD_INDEXES=false
```

- [ ] **Step 2: Update `ai-agent` service in `compose.production.yml`**

In `compose.production.yml`, add the same `volumes` block and two env vars to the `ai-agent` service (lines 104–123):

```yaml
  ai-agent:
    build:
      context: .
      dockerfile: services/ai-agent/Dockerfile
    restart: always
    depends_on:
      redis:
        condition: service_healthy
    volumes:
      - ./services/ai-agent/app/data-rag:/app/app/data-rag
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - BACKEND_URL=http://backend:8000
      - REACTION_PREDICT_URL=http://reaction-predict:8051
      - RETROSYNTHESIS_URL=http://retrosynthesis:8052
      - RAG_ENABLED=true
      - RAG_FORCE_REBUILD_INDEXES=false
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8100/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 3: Commit**

```bash
git add compose.yml compose.production.yml
git commit -m "feat(rag): add data-rag bind mount and RAG env vars to compose services"
```

---

## Task 7: Frontend — RAG badge in ToolCallCard

**Files:**
- Modify: `frontend/src/components/Chat/ToolCallCard.tsx`

- [ ] **Step 1: Add the RAG badge**

The current card header renders:
```tsx
<div className="flex items-center gap-2 border-b border-muted px-3 py-2">
  {statusIcon[status]}
  <span className="text-xs font-medium">{toolCall.name}</span>
  <Badge variant="outline" className="ml-auto text-[10px]">
    tool
  </Badge>
</div>
```

Add a RAG badge that appears before the `tool` badge when the tool is a RAG tool:

```tsx
const RAG_TOOL_NAMES = new Set(["rag_search", "literature_citation_search"])

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const status = toolCall.status ?? "completed"
  const isRagTool = RAG_TOOL_NAMES.has(toolCall.name)

  return (
    <Card className="my-2 overflow-hidden border-muted bg-muted/30 p-0" data-testid="tool-call-card">
      <div className="flex items-center gap-2 border-b border-muted px-3 py-2">
        {statusIcon[status]}
        <span className="text-xs font-medium">{toolCall.name}</span>
        {isRagTool && (
          <Badge variant="secondary" className="text-[10px] bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20">
            RAG
          </Badge>
        )}
        <Badge variant="outline" className="ml-auto text-[10px]">
          tool
        </Badge>
      </div>

      {Object.keys(toolCall.args).length > 0 && (
        <div className="px-3 py-2">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(toolCall.args, null, 2)}
          </pre>
        </div>
      )}

      {toolCall.result && (
        <div className="border-t border-muted px-3 py-2">
          <pre className="text-xs whitespace-pre-wrap break-all">
            {toolCall.result}
          </pre>
        </div>
      )}
    </Card>
  )
}
```

- [ ] **Step 2: Verify visually**

Start the frontend dev server and trigger a chat message that invokes `rag_search` or `literature_citation_search`. Confirm the green "RAG" badge appears next to the tool name in the tool call card.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Chat/ToolCallCard.tsx
git commit -m "feat(frontend): add RAG badge to tool call cards for rag_search and literature_citation_search"
```

---

## Verification Checklist

After all tasks are complete:

- [ ] `cd services/ai-agent && uv run pytest tests/test_rag.py -v` — all pass
- [ ] `docker compose build ai-agent` completes without errors (model download baked in)
- [ ] `docker compose up ai-agent` starts and `/health` returns 200
- [ ] Sending a chemistry question through the chat triggers `rag_search` with the RAG badge visible
- [ ] Adding a new `.md` file to `services/ai-agent/app/data-rag/sources/default/corpus_raw/` and restarting the container triggers an index rebuild — confirmed by `docker compose logs ai-agent | grep -i "built\|build\|fingerprint"` showing a build line rather than a load line

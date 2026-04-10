# OSN Pre-Main Merge Strategy Design

**Date:** 2026-03-23
**Goal:** Create `osn-pre-main` as a release candidate by merging three feature branches in optimal order
**Status:** Design approved, ready for implementation

---

## Executive Summary

This document specifies the merge sequence and conflict resolution strategy for integrating three parallel feature lines into a single, cohesive `osn-pre-main` branch:

1. **pre-main_stas** (base): Safety/chemistry tools + Langfuse infrastructure
2. **osn-article-downloading**: Article fetching + PDF parsing with RAG ingest
3. **seva-rag-gamma**: Latest RAG variant with RAGAS evaluation

The merge sequence prioritizes **dependency-driven ordering**: start from the most integrated base (pre-main_stas), add application features (articles) on top, then upgrade infrastructure (RAG) to the latest.

---

## Goals

1. **Release Candidate:** Produce a cohesive, production-ready branch combining all three feature lines
2. **Minimal Rework:** Start from pre-main_stas to avoid re-integrating Stas's work
3. **Clear Dependency Chain:** RAG → articles (depend on RAG scoping) → safety tools (orthogonal)
4. **Testability:** Establish validation gates after each merge to catch integration issues early

---

## Merge Sequence

### Phase 1: Base (pre-main_stas)
```
osn-pre-main ← origin/pre-main_stas
```

**Contains:**
- LLM Guard (input/output safety scanner)
- Hazard checker (chemical safety assessment)
- 1H NMR predictor
- 2D molecule drawing (RDKit)
- Langfuse tracing infrastructure
- Basic RAG setup (inherited from pre-main, likely `seva-rag-beta` state)
- Nginx/docker networking improvements
- Langfuse service in docker compose

**Why start here:**
- Most integrated state already
- Stas's infrastructure work already settled
- Reduces redundant conflict resolution

---

### Phase 2: Merge osn-article-downloading
```
osn-pre-main ← osn-article-downloading
```

**Adds:**
- Article fetcher service (scidownl-based, MinIO storage)
- PDF parser service (Docling + spaCy NLP, FastAPI webhook)
- Redis job store for article fetch/parse jobs
- Backend article status context injection (depends on conversation_id threading)
- Frontend ArticleDownloadsCard component with polling

**Expected conflicts:**
- `compose.yml` / `compose.production.yml` — service definitions (add article-fetcher/pdf-parser sections)
- `backend/app/worker/tasks/chat.py` — context injection logic (keep both article status + hazard checking)
- `services/ai-agent/app/main.py` — config routes (add ARTICLE_FETCHER_URL)
- `.gitignore` — merge both sets of rules

**Conflict resolution:**
- Accept article-fetcher/pdf-parser service definitions; merge with existing services
- Preserve both article status injection and hazard checking in chat.py:
  - Article status: prepend summary of downloaded/parsed articles to system prompt before streaming (via `_build_article_status_block()`)
  - Hazard checking: scan all tool outputs for unsafe content (independent, runs after tool execution)
- Add article routes alongside existing ones in main.py
- Merge .gitignore rules (union of both)
- **MinIO Setup**: Article chunks stored in MinIO under conversation-scoped paths: `articles-minio/chunks/{conversation_id}/`. Ensure `articles-minio` service (port 9000, with public endpoint on 9092) is defined separately from langfuse-minio

**Integration point:**
- Article pipeline threads `conversation_id` through fetch → webhook → parser → MinIO chunks
- RAG (from pre-main_stas baseline) will later retrieve these chunks per-conversation via scope injection
- ✓ Compatible: chunks stored in conversation-scoped path, retriever loads per-scope

---

### Phase 3: Merge seva-rag-gamma
```
osn-pre-main ← seva-rag-gamma
```

**Adds:**
- Upgraded RAG retriever: RAGAS evaluation metrics, query benchmarking
- query_mas CLI for direct MAS API queries
- Latest retriever registry with improved scope handling
- Agent autostart for evaluation pipelines

**Expected conflicts:**
- `services/ai-agent/app/agent.py` — tool definitions (accept RAG-gamma's tools, preserve article status context from Phase 2)
- `services/ai-agent/app/config.py` — RAG paths and settings (accept RAG-gamma)
- RAG data structure and indexes (accept RAG-gamma layout)

**Conflict resolution:**
- Accept RAG-gamma's agent tools and config (RAG is authoritative here)
- Preserve article status context injection from Phase 2 (orthogonal concern)
- No changes needed to services/ai-agent/app/main.py routes (article routes already there)

**Integration point:**
- RAG-gamma's scope registry (`_get_retriever_for_scope(scope)`) already supports conversation-scoped retrieval
- Article chunks stored in `data-rag/sources/{conversation_id}/` via MinIO (from Phase 2)
- When chat requests RAG search with `conversation_id` context, retriever loads chunks for that conversation
- ✓ Compatible: no changes needed, scope injection works with article storage

---

## Conflict Resolution Rules

### By file category:

**Docker Compose (`compose.yml`, `compose.production.yml`):**
- Keep all service definitions from all sources (no removals)
- Merge environment variables, depends_on, volumes, ports
- Ensure no port collisions:
  - article-fetcher: port 8200
  - pdf-parser: port 8300
  - articles-minio: port 9000 (public endpoint 9092)
  - All other services keep existing ports (ai-agent: 8100, redis: 6379, postgres: 5432, etc.)
  - Verify with `docker compose config | grep "ports:"` after merge

**Agent (`services/ai-agent/app/agent.py`):**
- Accept RAG-gamma for tool definitions and registrations
- Preserve article status context injection logic from osn-article-downloading (independently added)

**Agent Config (`services/ai-agent/app/config.py`):**
- Accept RAG-gamma (RAG paths + settings are authoritative)
- Preserve ARTICLE_FETCHER_URL from osn-article-downloading

**Agent Routes (`services/ai-agent/app/main.py`):**
- Add ARTICLE_FETCHER_URL config route if not present
- No conflict expected (RAG-gamma doesn't modify routes)

**Backend Chat (`backend/app/worker/tasks/chat.py`):**
- Keep both article status logic AND hazard checking logic (orthogonal)
- Both inspect tool outputs: articles inspect for DOIs, hazard checker scans for unsafe content

**Dependencies (`services/ai-agent/pyproject.toml`, `uv.lock`):**
- Accept union of all dependencies
- No expected version conflicts (article-fetcher and PDF parser dependencies are separate)

**.gitignore:**
- Merge all patterns from all branches (union)

---

## Testing & Validation Gates

### Pre-Phase 3 (before merging seva-rag-gamma):
- [ ] **CRITICAL**: Verify seva-rag-gamma code supports conversation-scoped retrieval:
  - Confirm `services/ai-agent/app/rag.py` (or equivalent) defines `_get_retriever_for_scope(scope: str)` function
  - Confirm retriever registry uses scope parameter (not global singleton)
  - Confirm agent tool calls pass `scope` or `conversation_id` to retriever
  - If scope injection is missing or named differently, Phase 3 integration will fail silently
  - **DO NOT PROCEED** with Phase 3 merge if scope support is incomplete

### After Phase 2 (osn-article-downloading merged):
- [ ] `docker compose up` completes without errors
- [ ] All services reach healthy state:
  - `ai-agent` service running
  - `article-fetcher` service listening on configured port
  - `pdf-parser` service listening on configured port
  - Redis service running
  - MinIO service running
  - Langfuse service running
- [ ] AI agent startup: RAG tools (`rag_search`, `literature_citation_search`) load successfully
- [ ] Chat workflow:
  - Submit chat message containing DOI text
  - Backend extracts DOIs via `_extract_dois()`
  - Article fetcher job created and persisted to Redis
  - Fetcher retrieves article via scidownl
  - Parser webhook invoked with PDF
  - Chunks uploaded to MinIO under conversation-scoped path
- [ ] No import errors in `services/ai-agent/app/`
- [ ] No import errors in `services/article-fetcher/`
- [ ] No import errors in `services/pdf-parser/`

### After Phase 3 (seva-rag-gamma merged):
- [ ] `docker compose up` still completes without errors
- [ ] All services still healthy
- [ ] RAG services operational:
  - Nomic model loaded
  - BM25 + dense indexes operational
  - Retriever registry initialized
- [ ] `rag_search` tool callable and returns results
- [ ] Article chunks retrievable via RAG with conversation scope isolation:
  - Fetch and parse article via `/fetch` endpoint with `conversation_id: "conv-1"` and DOI
  - Once parsed, query RAG within same conversation: `{"query": "relevant-keyword", "conversation_id": "conv-1"}`
  - Verify article chunks appear in results
  - Create second conversation `conv-2` and query same keyword
  - Verify chunks do NOT appear in RAG search for `conv-2` (scope isolation working)
  - **Sample curl for Phase 3 test:**
    ```bash
    # Fetch article in conv-1
    curl -X POST http://localhost:8200/fetch -H "Content-Type: application/json" \
      -d '{"doi": "10.1234/example", "conversation_id": "conv-1"}'
    # Query RAG in conv-1 (should find article)
    curl -X POST http://localhost:8100/rag_search -H "Content-Type: application/json" \
      -d '{"query": "search-term", "conversation_id": "conv-1"}'
    # Query RAG in conv-2 (should NOT find article)
    curl -X POST http://localhost:8100/rag_search -H "Content-Type: application/json" \
      -d '{"query": "search-term", "conversation_id": "conv-2"}'
    ```
- [ ] No import/config errors in `services/ai-agent/`

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Docker port collision after merges | Medium | High | Audit compose.yml ports after each merge; test with `docker compose config` |
| Article scope mismatch with RAG retriever | Low | High | Manually verify conversation_id flows through chat → MinIO path → retriever scope in Phase 3 test |
| RAG-gamma tool conflict with Guard/hazard checker | Low | Medium | Both are tool call consumers; no tool definition conflict expected; verify tool list after merge |
| uv.lock divergence (version conflicts) | Low | Medium | Accept union of dependencies; manual inspection if version ranges overlap |
| Langfuse tracing breaks with RAG-gamma additions | Low | Medium | Langfuse auto-discovers new spans; verify trace output in dashboard after Phase 3 |

---

## Post-Merge Integration Verification

After all three phases complete, run:

```bash
# Verify all services start
docker compose up -d

# Verify AI agent loads all tools
curl http://localhost:8100/tools

# Verify article pipeline
curl -X POST http://localhost:8101/fetch -H "Content-Type: application/json" \
  -d '{"doi": "10.1234/example", "conversation_id": "test-conv-1"}'

# Verify RAG search works
curl -X POST http://localhost:8100/rag_search \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "conversation_id": "test-conv-1"}'

# Verify chunks are scoped
# Check MinIO: articles-minio/data/test-conv-1/ should contain chunks
# Check different conversation: articles-minio/data/test-conv-2/ should be empty if no articles fetched
```

---

## Implementation Order

1. Create `osn-pre-main` branch from `origin/pre-main_stas`
2. Merge `osn-article-downloading`, resolve conflicts per Phase 2 rules
3. Run Phase 2 validation gates
4. Merge `seva-rag-gamma`, resolve conflicts per Phase 3 rules
5. Run Phase 3 validation gates
6. Test end-to-end article + RAG workflow
7. Commit to `osn-pre-main` and push

---

## Success Criteria

✓ All three branches merged without losing functionality
✓ All validation gates pass
✓ All services start in docker compose
✓ Article pipeline (fetch → parse → MinIO) works end-to-end
✓ RAG search works and returns conversation-scoped results
✓ Safety tools (Guard, hazard checker, NMR, drawing) still functional
✓ Langfuse tracing captures all tool calls
✓ No import/config errors in any service
✓ Ready for PR to main as release candidate

---

## Out of Scope

- Optimizing article fetcher performance
- Adding new RAG evaluation metrics beyond RAGAS
- Adding new safety tools beyond those in pre-main_stas
- Testing against production datasets (integration testing scope only)

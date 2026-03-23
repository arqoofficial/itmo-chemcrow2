# OSN Pre-Main Three-Phase Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge three feature branches (pre-main_stas + osn-article-downloading + seva-rag-gamma) into osn-pre-main release candidate.

**Architecture:** Sequential merge starting from most-integrated base (pre-main_stas), adding application features (articles), then upgrading infrastructure (RAG). Each phase has validation gates before proceeding.

**Tech Stack:** Git merge, Docker Compose, Python services (ai-agent, article-fetcher, pdf-parser), RAG retriever registry, MinIO, Langfuse

---

## Phase 1: Create osn-pre-main from pre-main_stas

### Task 1: Verify Current State and Fetch Latest

**Files:** None (verification only)

- [ ] **Step 1: Show current branch**

Run: `git branch -vv`
Expected: Current branch shown; verify you're on osn-article-downloading or other working branch

- [ ] **Step 2: Fetch latest from all remotes**

Run: `git fetch --all`
Expected: Remote refs updated (show "Fetching origin", "Fetching upstream" or similar)

- [ ] **Step 3: Verify pre-main_stas remote exists and is current**

Run: `git log origin/pre-main_stas -1 --oneline`
Expected: Recent commit visible (should be `be3d1f6 FIX: Fix .gitignore` or later)

---

### Task 2: Create osn-pre-main Branch from pre-main_stas

**Files:** None (git operation only)

- [ ] **Step 1: Create branch from origin/pre-main_stas**

Run: `git checkout -b osn-pre-main origin/pre-main_stas`
Expected: "Switched to a new branch 'osn-pre-main'" and "branch 'osn-pre-main' set up to track 'origin/pre-main_stas'."

- [ ] **Step 2: Verify branch creation and tracking**

Run: `git branch -vv | grep osn-pre-main`
Expected: `osn-pre-main be3d1f6 [origin/pre-main_stas] FIX: Fix .gitignore`

- [ ] **Step 3: Log recent commits on new branch**

Run: `git log --oneline -5`
Expected: Shows recent commits from pre-main_stas (safety tools, Langfuse, etc.)

---

### Task 3: Document Phase 1 Completion

**Files:** None (logging only)

- [ ] **Step 1: Record Phase 1 status**

Output in your implementation notes:
```
✓ Phase 1 Complete
  Branch: osn-pre-main
  Base: origin/pre-main_stas (be3d1f6)
  Contains: Safety tools, Langfuse, basic RAG

Ready for Phase 2: Merge osn-article-downloading
```

---

## Phase 2: Merge osn-article-downloading

### Task 4: Merge osn-article-downloading with Conflict Resolution

**Files:**
- `.gitignore` (conflict expected)
- `backend/app/worker/tasks/chat.py` (conflict expected)
- `compose.yml` (conflict expected)
- `compose.production.yml` (conflict expected)
- `services/ai-agent/app/main.py` (conflict expected)
- `services/ai-agent/app/agent.py` (may conflict)
- `services/ai-agent/pyproject.toml` (may conflict)
- `uv.lock` (may conflict)

- [ ] **Step 1: Start merge**

Run: `git merge osn-article-downloading -m "merge: integrate article downloading and PDF parsing (Phase 2)"`
Expected: Merge conflict output showing files with conflicts (see list above)

- [ ] **Step 2: Resolve .gitignore**

Run: `git diff .gitignore | head -40`
Expected: Shows conflict markers `<<<<<<<`, `=======`, `>>>>>>>`

Edit `.gitignore` to accept BOTH sets of ignore rules (union merge):
```bash
# Keep all patterns from both branches
# No patterns should be removed
```

Run: `git add .gitignore`
Expected: File staged

- [ ] **Step 3: Resolve compose.yml**

Run: `git diff compose.yml | head -60`
Expected: Shows service definition conflicts

Strategy: Accept BOTH service sets (keep pre-main_stas services, ADD article-fetcher/pdf-parser)

Key sections to merge:
- **From osn-article-downloading, ADD:**
  ```yaml
  article-fetcher:
    build: ./services/article-fetcher
    ports:
      - "8200:8080"
    environment:
      REDIS_URL: redis://redis:6379
      MINIO_ENDPOINT: http://articles-minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    depends_on:
      - redis
      - articles-minio

  pdf-parser:
    build: ./services/pdf-parser
    ports:
      - "8300:8000"
    environment:
      REDIS_URL: redis://redis:6379
      MINIO_ENDPOINT: http://articles-minio:9000
      AI_AGENT_INGEST_URL: http://ai-agent:8100
    depends_on:
      - redis
      - articles-minio
      - ai-agent

  articles-minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9092:9092"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
      MINIO_PUBLIC_ENDPOINT: http://localhost:9092
  ```

- Keep all services from pre-main_stas (ai-agent, redis, langfuse, etc.)

Run: `git add compose.yml`
Expected: File staged

- [ ] **Step 4: Resolve compose.production.yml (same strategy as compose.yml)**

Run: `git add compose.production.yml`
Expected: File staged

- [ ] **Step 5: Resolve backend/app/worker/tasks/chat.py**

Run: `git diff backend/app/worker/tasks/chat.py | head -80`
Expected: Shows article status injection logic conflict

Strategy: Keep BOTH article status injection AND hazard checking logic

Key: Article status is injected into system prompt via `_build_article_status_block()`, hazard checking scans all tool outputs independently.

Verify merged file contains:
- `_extract_dois()` function (from osn-article-downloading)
- `_get_conversation_article_jobs()` function (from osn-article-downloading)
- `_build_article_status_block()` function (from osn-article-downloading)
- Article status prepended to system prompt before streaming
- Hazard checking logic still present (from pre-main_stas)

Run: `git add backend/app/worker/tasks/chat.py`
Expected: File staged

- [ ] **Step 6: Resolve services/ai-agent/app/main.py**

Run: `git diff services/ai-agent/app/main.py | head -40`
Expected: Shows ARTICLE_FETCHER_URL config route conflict

Strategy: Add article config route alongside existing routes

Merged file should have:
```python
@app.get("/config/article-fetcher-url")
def get_article_fetcher_url():
    return {"article_fetcher_url": settings.ARTICLE_FETCHER_URL}
```

Run: `git add services/ai-agent/app/main.py`
Expected: File staged

- [ ] **Step 7: Resolve services/ai-agent/pyproject.toml**

Run: `git diff services/ai-agent/pyproject.toml | head -40`
Expected: Shows dependency conflict

Strategy: Accept union of dependencies (all from both branches)

Run: `git add services/ai-agent/pyproject.toml`
Expected: File staged

- [ ] **Step 8: Resolve uv.lock**

Run: `git diff uv.lock | wc -l`
Expected: Shows large diff (lock files are large)

Strategy: Accept osn-article-downloading version (it's the most recent)

Run: `git checkout --theirs uv.lock && git add uv.lock`
Expected: Lock file staged from incoming branch

- [ ] **Step 9: Check for remaining conflicts**

Run: `git diff --name-only --diff-filter=U`
Expected: Empty output (no unresolved conflicts)

- [ ] **Step 10: Complete merge with commit**

Run: `git commit -m "merge: integrate article downloading and PDF parsing (Phase 2)"`
Expected: Merge commit created; shows files changed, insertions/deletions

---

### Task 5: Phase 2 Validation - Service Health

**Files:** None (docker operations only)

- [ ] **Step 1: Verify docker compose syntax**

Run: `docker compose config > /dev/null && echo "Config valid"`
Expected: "Config valid"

- [ ] **Step 2: Start services**

Run: `docker compose up -d`
Expected: Services starting; output shows "Creating...", "Starting..."

- [ ] **Step 3: Wait for services to stabilize**

Run: `sleep 60`
Expected: 60 seconds pass

- [ ] **Step 4: Check all services healthy**

Run: `docker compose ps`
Expected: All services showing "Up" status (not "Exited" or "Restarting")

Example:
```
NAME                   STATUS
ai-agent              Up 45 seconds
redis                 Up 50 seconds
article-fetcher       Up 40 seconds
pdf-parser            Up 38 seconds
articles-minio        Up 48 seconds
langfuse              Up 30 seconds
```

- [ ] **Step 5: Verify AI agent responds**

Run: `curl -s http://localhost:8100/health`
Expected: 200 OK response (may show `{"status": "ok"}` or similar)

- [ ] **Step 6: Check article-fetcher is running**

Run: `curl -s http://localhost:8200/health`
Expected: 200 OK response

- [ ] **Step 7: Check pdf-parser is running**

Run: `curl -s http://localhost:8300/health`
Expected: 200 OK response

---

### Task 6: Phase 2 Validation - Tool Registration

**Files:** None (curl operations only)

- [ ] **Step 1: Fetch tool list from AI agent**

Run: `curl -s http://localhost:8100/tools | jq '.[].name' | sort`
Expected: Output including:
```
rag_search
literature_citation_search
guard
hazard_checker
nmr_predictor
structure_drawing
```

- [ ] **Step 2: Verify no tool loading errors**

Run: `docker compose logs ai-agent 2>&1 | grep -i "error\|failed" | head -5`
Expected: No error messages (empty output or unrelated errors)

---

### Task 7: Phase 2 Validation - Article Pipeline

**Files:** None (integration testing only)

- [ ] **Step 1: Test article fetcher endpoint**

Run: `curl -X POST http://localhost:8200/fetch -H "Content-Type: application/json" -d '{"doi": "10.1234/test", "conversation_id": "test-conv-phase2"}' -v`
Expected: 200 OK response; job created (shows job_id in response)

- [ ] **Step 2: Check Redis job was persisted**

Run: `docker compose exec redis redis-cli lrange "conversation:test-conv-phase2:article_jobs" 0 -1`
Expected: Shows JSON array with job entry (may show empty if not immediately indexed, try after 5s delay)

- [ ] **Step 3: Test MinIO connection**

Run: `curl -s http://localhost:9000/minio/health/live`
Expected: 200 OK

- [ ] **Step 4: Verify PDF parser webhook path exists**

Run: `curl -X POST http://localhost:8300/webhook -H "Content-Type: application/json" -d '{"job_id": "test", "pdf_path": "/tmp/test.pdf"}' -v`
Expected: 200 or 422 (validation error is fine, just verifies endpoint exists)

---

### Task 8: Phase 2 Completion Checkpoint

**Files:** None (logging only)

- [ ] **Step 1: Document Phase 2 completion**

Output in implementation notes:
```
✓ Phase 2 Complete (Merge osn-article-downloading)
  Conflicts resolved:
    - .gitignore (merged)
    - compose.yml (services merged)
    - compose.production.yml (services merged)
    - backend/app/worker/tasks/chat.py (article + hazard logic kept)
    - services/ai-agent/app/main.py (article routes added)
    - services/ai-agent/pyproject.toml (dependencies merged)
    - uv.lock (accepted incoming)

  Validation passed:
    ✓ Docker compose config valid
    ✓ All services healthy
    ✓ Tools loaded (RAG + safety + article)
    ✓ Article pipeline callable

Ready for Phase 3: Merge seva-rag-gamma
```

---

## Phase 3: Merge seva-rag-gamma

### Task 9: Pre-Phase-3 Critical Validation - RAG Scope Registry

**Files:** None (code inspection)

- [ ] **Step 1: Verify seva-rag-gamma has scope registry support**

Run: `git show origin/seva-rag-gamma:services/ai-agent/app/rag.py | grep -A 5 "_get_retriever_for_scope"`
Expected: Function definition exists with `scope` parameter

If not found, run alternative:
```bash
git show origin/seva-rag-gamma:services/ai-agent/app/rag.py | grep -A 5 "_RETRIEVER_REGISTRY"
```
Expected: Shows scope-keyed registry dict (not global singleton)

- [ ] **Step 2: Verify scope parameter in retriever calls**

Run: `git show origin/seva-rag-gamma:services/ai-agent/app/agent.py | grep -B 2 -A 2 "rag_search\|_get_retriever"`
Expected: Shows scope/conversation_id parameter being passed to retriever

- [ ] **Step 3: Decision gate**

If both checks pass: ✓ **PROCEED to Phase 3 merge**

If either check fails: ✗ **ABORT** - Document the missing scope support and resolve before merging

Example abort output:
```
✗ ABORT Phase 3
Reason: seva-rag-gamma scope registry not found
Action: Verify correct branch or consult with team before proceeding
```

---

### Task 10: Merge seva-rag-gamma with Conflict Resolution

**Files:**
- `services/ai-agent/app/agent.py` (conflict expected)
- `services/ai-agent/app/config.py` (conflict expected)
- RAG data paths and indexes (merge expected)

- [ ] **Step 1: Start merge**

Run: `git merge origin/seva-rag-gamma -m "merge: upgrade RAG to gamma variant with RAGAS evaluation (Phase 3)"`
Expected: Merge conflict output showing RAG-related conflicts

- [ ] **Step 2: Resolve services/ai-agent/app/agent.py**

Run: `git diff services/ai-agent/app/agent.py | head -100`
Expected: Shows RAG tool definition conflicts

Strategy: Accept RAG-gamma's tool definitions; preserve article status context injection from Phase 2

Merged file should have:
- RAG-gamma's `rag_search` and `literature_citation_search` tools (updated)
- Article status injection into agent context (from Phase 2, preserved)
- Safety tools unchanged (from pre-main_stas)

Run: `git add services/ai-agent/app/agent.py`
Expected: File staged

- [ ] **Step 3: Resolve services/ai-agent/app/config.py**

Run: `git diff services/ai-agent/app/config.py | head -60`
Expected: Shows RAG paths and settings conflicts

Strategy: Accept RAG-gamma (it's the authoritative RAG config)

Verify merged file contains:
- `RAG_SOURCES_DIR` pointing to conversation scope structure
- `RAG_DENSE_INDEX_DIR`, `RAG_BM25_INDEX_PATH` paths correct
- `ARTICLE_FETCHER_URL` from Phase 2 preserved

Run: `git add services/ai-agent/app/config.py`
Expected: File staged

- [ ] **Step 4: Check for remaining conflicts**

Run: `git diff --name-only --diff-filter=U`
Expected: Empty output (no unresolved conflicts)

- [ ] **Step 5: Complete merge**

Run: `git commit -m "merge: upgrade RAG to gamma variant with RAGAS evaluation (Phase 3)"`
Expected: Merge commit created

---

### Task 11: Phase 3 Validation - RAG Functionality

**Files:** None (integration testing)

- [ ] **Step 1: Rebuild AI agent service (updated dependencies)**

Run: `docker compose up -d --build ai-agent`
Expected: Service rebuilding, then up

- [ ] **Step 2: Wait for RAG models to load**

Run: `sleep 30`
Expected: 30 seconds pass

- [ ] **Step 3: Verify RAG tools still callable**

Run: `curl -s http://localhost:8100/tools | jq '.[] | select(.name | contains("rag")) | .name'`
Expected:
```
rag_search
literature_citation_search
```

- [ ] **Step 4: Check for RAG initialization errors**

Run: `docker compose logs ai-agent 2>&1 | grep -i "rag\|retriever" | tail -10`
Expected: Shows RAG initialization messages, no errors

---

### Task 12: Phase 3 Validation - Article + RAG Integration

**Files:** None (integration testing)

- [ ] **Step 1: Fetch test article (Phase 3 conversation)**

Run: `curl -X POST http://localhost:8200/fetch -H "Content-Type: application/json" -d '{"doi": "10.1234/test-phase3", "conversation_id": "conv-phase3-test"}' -v`
Expected: 200 OK, job created

- [ ] **Step 2: Wait for article parsing (simulate parse completion)**

Run: `sleep 10`
Expected: Allows time for parsing queue to process

- [ ] **Step 3: Check chunks uploaded to MinIO**

Run: `docker compose exec articles-minio mc ls minio/chunks/conv-phase3-test/ 2>/dev/null || echo "Bucket check - may be empty if parse still processing"`
Expected: Lists chunk files (or empty if parsing in progress)

- [ ] **Step 4: Query RAG in same conversation (should find article)**

Run: `curl -X POST http://localhost:8100/rag_search -H "Content-Type: application/json" -d '{"query": "test article content", "conversation_id": "conv-phase3-test"}' | jq '.results[0].content' | head -20`
Expected: Returns search results (may show article chunks or empty if parsing not complete)

- [ ] **Step 5: Query RAG in different conversation (should NOT find article)**

Run: `curl -X POST http://localhost:8100/rag_search -H "Content-Type: application/json" -d '{"query": "test article content", "conversation_id": "conv-phase3-different"}' | jq '.results | length'`
Expected: Shows 0 or empty results (scope isolation working)

---

### Task 13: Phase 3 Completion Checkpoint

**Files:** None (logging)

- [ ] **Step 1: Document Phase 3 completion**

Output in implementation notes:
```
✓ Phase 3 Complete (Merge seva-rag-gamma)
  Pre-merge validation: PASSED
    ✓ Scope registry support confirmed
    ✓ Scope parameter in retriever calls confirmed

  Conflicts resolved:
    - services/ai-agent/app/agent.py (RAG tools updated, article status preserved)
    - services/ai-agent/app/config.py (RAG config accepted)

  Validation passed:
    ✓ All services healthy
    ✓ RAG tools loaded
    ✓ Article + RAG integration working
    ✓ Conversation scope isolation verified

Ready for final verification and PR
```

---

## Phase 4: Final Integration Verification

### Task 14: Post-Merge Full System Test

**Files:** None (integration testing)

- [ ] **Step 1: Verify all services running**

Run: `docker compose ps --format "table {{.Names}}\t{{.Status}}" | grep -v "Up"`
Expected: Empty output (all services should be Up)

- [ ] **Step 2: Test complete chat flow with DOI extraction**

Run:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "final-test",
    "messages": [{"role": "user", "content": "Tell me about DOI 10.1234/example"}]
  }' | head -50
```
Expected: Chat response (streaming tokens); no errors

- [ ] **Step 3: Verify Langfuse tracing active**

Run: `curl -s http://localhost:3000/api/trace-v1 2>&1 | head -5`
Expected: Langfuse responds (may show 200 or auth error, just verifying it's reachable)

- [ ] **Step 4: Check all tool categories work**

Run: `curl -s http://localhost:8100/tools | jq '.[] | .name' | wc -l`
Expected: Number >= 10 (all tools from RAG, safety, articles loaded)

---

### Task 15: Final Documentation and Commit

**Files:** None (git operations)

- [ ] **Step 1: Create summary of integration**

Document in git notes:
```bash
git notes add -m "osn-pre-main integration complete

Integrated three feature branches:
1. pre-main_stas: Safety tools + Langfuse
2. osn-article-downloading: Article fetching + PDF parsing
3. seva-rag-gamma: RAG with RAGAS evaluation

All integration points verified:
- Article chunks scoped per conversation
- RAG retriever loads conversation-specific indexes
- Safety tools orthogonal to article/RAG pipeline
- Langfuse traces all tool invocations

Ready for PR to main as release candidate
"
```

- [ ] **Step 2: Verify branch state**

Run: `git log --oneline -5`
Expected: Shows 3 merge commits (Phase 2, Phase 3) and branch creation

- [ ] **Step 3: Check uncommitted changes**

Run: `git status`
Expected: "nothing to commit, working tree clean"

- [ ] **Step 4: Final verification commit (if needed)**

Run: `git log --oneline origin/osn-pre-main..HEAD`
Expected: Shows all commits made in this session (should be merge commits + planning docs)

---

## Troubleshooting Reference

### Common Merge Conflicts

**Problem:** `compose.yml` conflict shows duplicate service names
**Solution:** Keep ALL services from both branches; don't remove any. Merge `environment`, `ports`, `depends_on` sections.

**Problem:** `uv.lock` shows too many conflicts
**Solution:** Accept the incoming version (`git checkout --theirs uv.lock`) since it's more recent.

**Problem:** `agent.py` shows tool registry conflicts
**Solution:** Accept RAG-gamma's tools (it's authoritative for RAG), preserve article status injection logic (orthogonal).

### Docker Issues

**Problem:** Services not starting after merge
**Solution:**
1. Check logs: `docker compose logs <service>`
2. Verify ports available: `lsof -i :8100` (replace port)
3. Rebuild: `docker compose up -d --build`

**Problem:** MinIO bucket not found
**Solution:**
1. Manually create bucket: `docker compose exec articles-minio mc mb minio/chunks`
2. Or wait for article-fetcher to create it on first use

### Port Conflicts

**Expected ports after Phase 2:**
- 8100: ai-agent
- 8200: article-fetcher
- 8300: pdf-parser
- 9000: articles-minio (9092 for public)
- 6379: redis
- 5432: postgres
- 3000: langfuse

Run `lsof -i -P -n | grep LISTEN` to verify availability.

---

## Success Criteria Checklist

- [ ] Phase 1: osn-pre-main created from pre-main_stas
- [ ] Phase 2: osn-article-downloading merged, all conflicts resolved, validation gates passed
- [ ] Phase 3: pre-main_stas RAG scope registry validated before merge
- [ ] Phase 3: seva-rag-gamma merged, all conflicts resolved, validation gates passed
- [ ] Article + RAG conversation scope isolation verified with curl tests
- [ ] All services healthy and running
- [ ] All tools (RAG, safety, article) loaded and callable
- [ ] No uncommitted changes; working tree clean
- [ ] Ready for PR to main

**When all checkboxes complete:** osn-pre-main is a production-ready release candidate.

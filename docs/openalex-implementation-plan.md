# OpenAlex Search Implementation Plan

## Overview
Add OpenAlex search feature as a complementary literature search tool, following the same async pipeline as Semantic Scholar (S2) search. All changes follow the TDD paradigm with tests written first.

## Critical Files to Modify

### 1. AI Agent Service (`services/ai-agent/`)

**File:** `app/tools/search.py`
- Add `openalex_search` tool function (mirrors `literature_search`)
- Accepts `query: str` and `max_results: int = 5`
- POSTs to `backend /internal/queue-background-tool` with type `"openalex_search"`
- Returns immediate "queued" message
- Handles backend errors gracefully

**File:** `app/config.py`
- Add `OPENALEX_API_KEY: str` setting (reads from .env)
- Add `OPENALEX_API_BASE: str = "https://api.openalex.org"`

**File:** `app/agent.py` (`convert_messages` function)
- Already handles `background` role (added for async pipeline)
- No changes needed

**Tests:** `services/ai-agent/tests/test_openalex_search.py`
- ✓ Already written
- Tests tool queuing, error handling, context validation

### 2. Backend Service (`backend/app/`)

**File:** `app/core/config.py`
- Add `OPENALEX_API_KEY: str = Field(default="", description="OpenAlex API key")`
- Add `OPENALEX_API_BASE: str = "https://api.openalex.org"`

**File:** `app/api/routes/articles.py`
- Add endpoint: `POST /api/v1/articles/conversations/{id}/retry-openalex-search`
- Mirrors existing `retry_s2_search` logic
- Generates dedup key from query hash
- Returns 202 (accepted), 409 (conflict), or 410 (expired)

**File:** `app/worker/tasks/continuation.py`
- Add function: `_format_openalex_results(papers: list[dict], query: str) -> str`
  - Formats OpenAlex response for display (mirrors `_format_s2_results`)
  - Extracts title, authors, year, DOI, abstract
  - Truncates long abstracts to 400 chars
- Add function: `def run_openalex_search(conversation_id: str, query: str, max_results: int = 5, original_message_id: str | None = None, dedup_key: str | None = None)`
  - Celery task (like `run_s2_search`)
  - Calls OpenAlex API via backend's `/internal/openalex-search` endpoint
  - Extracts DOIs and submits article jobs
  - Saves background message with variant="info"
  - Publishes background_update event
  - Dispatches run_agent_continuation
  - Handles errors: saves error message with variant="error"
  - On retry: updates error message in-place (using replace_message_id)
  - On success: deletes original error message
  - Always releases dedup lock in finally block

**File:** `app/api/main.py`
- Register `/internal/openalex-search` endpoint (blocking call to OpenAlex API)
- Mirrors existing `/internal/s2-search` endpoint
- No auth (Docker-internal only)
- Accepts: `{"query": str, "max_results": int}`
- Returns: `{"papers": [...]}`

**File:** `app/worker/prompts.py`
- Add: `OPENALEX_RESULTS` template (mirrors `S2_RESULTS`)
- Add: `OPENALEX_NO_RESULTS` template
- Add: `OPENALEX_FAILURE` template

**Tests:**
- ✓ `backend/tests/test_openalex_search_task.py` — Already written
- ✓ `backend/tests/test_openalex_retry_endpoint.py` — Already written

### 3. Frontend Service (`frontend/src/`)

**File:** `src/components/Chat/MessageBubble.tsx`
- Already handles `role="background"` (added for async pipeline)
- No changes needed

**File:** `src/hooks/useConversationSSE.ts`
- Already handles `background_update` event (added for async pipeline)
- No changes needed

**E2E Tests:**
- ✓ `frontend/tests/e2e-openalex-search.spec.ts` — Already written

## Implementation Sequence (TDD)

### Phase 1: AI Agent Tool
1. Implement `openalex_search` tool in `services/ai-agent/app/tools/search.py`
   - Must pass tests in `test_openalex_search.py`
2. Add settings to `app/config.py`
3. Register tool in `app/agent.py`
4. Run: `uv run pytest tests/test_openalex_search.py -v`

### Phase 2: Backend Configuration
1. Add settings to `backend/app/core/config.py`
2. Add prompt templates to `backend/app/worker/prompts.py`
3. Run: `uv run pytest backend/tests/ -v` (no failures yet, some tests will skip)

### Phase 3: Backend Internal Endpoint
1. Create `POST /internal/openalex-search` endpoint in `backend/app/api/main.py`
   - Call OpenAlex API: `GET https://api.openalex.org/works?search={query}&per_page={max_results}&api_key={key}`
   - Parse response
   - Return formatted `{"papers": [...]}`
2. Test with curl before integration

### Phase 4: Backend Celery Task
1. Implement `_format_openalex_results()` in `backend/app/worker/tasks/continuation.py`
2. Implement `run_openalex_search()` Celery task
3. Register task to handle `type="openalex_search"` in `/internal/queue-background-tool`
4. Run: `uv run pytest backend/tests/test_openalex_search_task.py -v`

### Phase 5: Backend Retry Endpoint
1. Implement `POST /api/v1/articles/conversations/{id}/retry-openalex-search` endpoint
2. Implement dedup logic (Redis SET NX EX)
3. Store query in Redis for retry support
4. Run: `uv run pytest backend/tests/test_openalex_retry_endpoint.py -v`

### Phase 6: Integration & E2E
1. Rebuild and start full stack: `docker compose up --build -d`
2. Run e2e tests: `uv run playwright test frontend/tests/e2e-openalex-search.spec.ts`
3. Manual verification:
   - Send chat message: "Search for green chemistry using OpenAlex"
   - Verify tool is called
   - Verify background message appears (~15-30s)
   - Verify agent responds
   - Verify papers download/parse (if articles have DOIs)

## Deduplication & State Management

### Redis Keys
- `openalex_last_query:{conversation_id}` (24h TTL)
  - Stores last search query for retry
- `openalex_search_active:{conversation_id}:{query_hash}` (200s TTL)
  - Prevents concurrent identical searches
  - Hash is first 16 chars of SHA256(query.lower().strip())

### HTTP Status Codes
- 202: Accepted (search queued)
- 409: Conflict (search already in progress)
- 410: Gone (query expired after 24h)

### Message Lifecycle
1. **On error:** Save background message with `variant="error"` and show Retry button
2. **On retry:**
   - First retry: Update error message in-place (same message ID)
   - If retry fails: Error message updated again with new failure reason
   - If retry succeeds: Error message deleted, results message saved
3. **No duplicates:** If multiple retries happen, only one is processed (409 blocks others)

## Error Handling

### API Call Errors
- Network timeout: "OpenAlex search unavailable: connection timeout"
- Invalid API key: "OpenAlex search unavailable: authentication failed"
- Rate limit: "OpenAlex search unavailable: rate limited, try again later"
- Other HTTP errors: "OpenAlex search unavailable: service error ({status})"

### Empty Results
- Save error message: "No papers found for '{query}'"
- Don't show Retry button (not worth retrying)

### Article Job Failures
- Handled by existing `monitor_ingestion` task
- Papers without DOI: Skipped (can't download), but still listed in results

## Testing Strategy Recap

### Unit Tests (Run on each commit)
- AI Agent: Tool returns queued, handles context, POSTs correctly
- Backend Task: Formats results, handles API errors, releases locks
- Endpoint: Returns correct status codes, generates dedup keys

### Integration Tests (Run before PR)
- Full pipeline: search → article jobs → background message → continuation
- Dedup: Concurrent searches blocked properly
- Retry: Error card updated, deleted on success

### E2E Tests (Run before merge)
- User sends OpenAlex search message
- Results appear in background card
- Agent analyzes results
- Papers download (if available)
- Retry works on simulated failure

## Migration & Rollout

### Backward Compatibility
- No breaking changes to existing APIs
- Existing S2 search unaffected
- New endpoint is purely additive

### Deployment Steps
1. Ensure `OPENALEX_API_KEY` is set in production `.env`
2. Deploy backend → ai-agent → frontend (order matters)
3. Monitor Redis for dedup key cleanup
4. Monitor task queue for performance

## Success Criteria

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] E2E tests run without manual intervention
- [ ] OpenAlex search works alongside S2 search
- [ ] Error retry mechanism works as specified
- [ ] PR passes code review
- [ ] No performance regression (<100ms added latency per search)

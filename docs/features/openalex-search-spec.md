# OpenAlex Search Feature Specification

## Overview

OpenAlex is a free, comprehensive API providing access to 250M+ scholarly research works. Unlike Semantic Scholar (S2), OpenAlex provides:
- Broader coverage (includes books, datasets, conference papers)
- More detailed metadata (affiliations, funders, topics, citations)
- No rate limiting restrictions
- Free API with optional authentication via API key

## API Characteristics

### Base URL
```
https://api.openalex.org
```

### Authentication
- Free API key from https://openalex.org/settings/api
- Passed as query parameter: `?api_key=YOUR_KEY`
- Cost: $1/day free, additional usage available

### Search Endpoint
```
GET /works?search=<query>&per_page=<n>&api_key=<key>
```

### Response Structure
```json
{
  "meta": {
    "count": 12345,
    "db_response_time_ms": 123,
    "page": 1,
    "per_page": 25
  },
  "results": [
    {
      "id": "https://openalex.org/W2741809807",
      "title": "Paper Title",
      "publication_year": 2020,
      "doi": "https://doi.org/10.1234/example",
      "abstract": "Abstract text...",
      "cited_by_count": 42,
      "type": "journal-article",
      "authorships": [
        {
          "author": {
            "display_name": "John Doe"
          },
          "institutions": [
            {
              "display_name": "University Name"
            }
          ]
        }
      ],
      "primary_location": {
        "source": {
          "display_name": "Journal Name"
        }
      },
      "topics": [
        {
          "display_name": "Molecular Chemistry"
        }
      ]
    }
  ]
}
```

### Key Differences from Semantic Scholar (S2)

| Feature | OpenAlex | S2 |
|---------|----------|---|
| Coverage | 250M+ works | Similar |
| Search | Full-text, titles | Broad field |
| Rate Limiting | None (with key) | 100 req/5min |
| Topics | Detailed topic classification | N/A |
| Cost | Free with key | Free |
| Affiliation Data | Rich | Limited |

## Feature Integration Points

### 1. Frontend
- Add toggle/button: "Search OpenAlex" alongside "Search Literature"
- Reuse existing `ArticleDownloadsCard` for article pipeline
- Display OpenAlex results in same background message format

### 2. Backend
- New Celery task: `run_openalex_search` (mirrors `run_s2_search`)
- New route: `POST /internal/queue-background-tool` supports `type="openalex_search"`
- Settings: Add `OPENALEX_API_KEY` to config

### 3. AI Agent
- New tool: `openalex_search` (mirrors `literature_search`)
- Tool dispatches async search via backend queue
- Returns immediate "queued" message

## User Stories

### Story 1: Direct Tool Call
**As a** chemist researching a topic,
**I want to** call `openalex_search` tool directly,
**So that** I can discover papers from a complementary source (beyond S2)

**Acceptance Criteria:**
- Tool accepts `query` and optional `max_results`
- Returns "queued" immediately
- Results appear as background message within 30s
- Can call both `literature_search` and `openalex_search` in same conversation

### Story 2: Error Handling & Retry
**As a** user whose OpenAlex search fails,
**I want to** see a retry button,
**So that** I can try the search again without restarting the conversation

**Acceptance Criteria:**
- Failed search shows error card with Retry button
- Retry uses same query (stored in Redis)
- Duplicate retries blocked (409 Conflict)
- Successful retry deletes error card

### Story 3: Article Pipeline Integration
**As a** user who found papers via OpenAlex,
**I want to** download and parse those papers,
**So that** I can use RAG to analyze their full content

**Acceptance Criteria:**
- Papers with DOI are automatically submitted to article-fetcher
- Article download status displayed in ArticleDownloadsCard
- Failed downloads can be retried manually
- Successful parsing triggers RAG continuation (like S2)

### Story 4: Agent Response Quality
**As a** the AI agent,
**I want to** respond to OpenAlex results with context,
**So that** the user gets value-added analysis

**Acceptance Criteria:**
- OpenAlex results appear as background message before agent re-responds
- Agent can see paper titles, authors, abstracts in message history
- Agent performs RAG analysis on parsed papers

## Technical Design

### Data Flow

```
User: "Find papers on aspirin synthesis using OpenAlex"
    ↓
openalex_search tool POSTs to backend
    ↓
Celery: run_openalex_search task
    ↓
Call api.openalex.org /works endpoint (≤5s)
    ↓
Extract DOIs, submit to article-fetcher
    ↓
Save background message "OpenAlex Results: X papers found"
    ↓
Publish background_update event
    ↓
run_agent_continuation dispatches
    ↓
Agent re-responds with initial analysis
    ↓
monitor_ingestion polls article status
    ↓
(On all parsed) trigger RAG continuation
    ↓
Agent responds again with document-level insights
```

### Configuration
```python
# app/config.py
OPENALEX_API_KEY: str = Field(default="", description="OpenAlex API key")
OPENALEX_API_BASE: str = "https://api.openalex.org"
```

### Deduplication & State Management
- Redis key: `openalex_last_query:{conversation_id}` (24h TTL) — for retry
- Redis lock: `openalex_search_active:{conversation_id}:{hash}` (200s TTL) — prevent concurrent identical searches
- DB: Save background message with `variant="info"` or `"error"` (matches S2 pattern)

## Testing Strategy

### Unit Tests
1. `test_openalex_search_tool_returns_queued` — verify tool returns immediately
2. `test_openalex_search_no_context` — handle missing conversation context
3. `test_run_openalex_search_success` — mock API call, verify message saved
4. `test_run_openalex_search_failure` — handle API error, show error card
5. `test_run_openalex_search_dedup` — test 409 on duplicate searches
6. `test_run_openalex_search_retry` — test message update on retry
7. `test_openalex_search_extracts_dois` — verify DOI extraction and article submission

### E2E Tests (Playwright)
1. User navigates to chat
2. Sends message: "search for caffeine synthesis using OpenAlex"
3. Agent calls `openalex_search` tool
4. Background message appears with results (within 30s)
5. Agent responds with initial analysis
6. Optional: Wait for papers to parse, verify RAG response
7. Optional: Click Retry on a simulated error

### Integration Tests
1. Full pipeline: search → article download → parse → RAG
2. Multiple searches in one conversation
3. Mixed S2 + OpenAlex searches
4. Error recovery and retry lifecycle

## Deployment Checklist
- [ ] Add `OPENALEX_API_KEY` to production `.env`
- [ ] Verify API key limits (if applicable)
- [ ] Monitor task queue for performance
- [ ] Confirm Redis dedup keys are cleaned up
- [ ] Test with real user conversations

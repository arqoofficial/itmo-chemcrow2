# Pre-Main-Stas Testing Guide

**Purpose:** Quick reference for testing `origin/pre-main_stas` branch in isolation before merging into `osn-pre-main`.

---

## Branch Overview

`pre-main_stas` contains the baseline for the three-phase merge:
- Safety tools (LLM Guard, hazard checker, 1H NMR predictor, RDKit drawing)
- Langfuse tracing infrastructure
- Basic RAG setup (inherited from pre-main, likely `seva-rag-beta` state)
- Nginx + docker networking improvements

---

## Quick Start

```bash
# Create temp branch for testing
git checkout -b test-pre-main_stas origin/pre-main_stas

# Start services
docker compose up -d

# Wait for services to stabilize (30-60s)
sleep 60

# Check service health
docker compose ps
```

---

## Health Checks

### 1. All Services Running
```bash
docker compose ps
# Expected: all services in "Up" state
```

### 2. AI Agent Startup
```bash
curl http://localhost:8100/health
# Expected: 200 OK
```

### 3. RAG Tools Loaded
```bash
curl http://localhost:8100/tools | jq '.[] | .name'
# Expected: rag_search, literature_citation_search (and safety tools)
```

### 4. Safety Tools Present
```bash
curl http://localhost:8100/tools | jq '.[] | .name' | grep -E "guard|hazard|nmr|drawing"
# Expected: guard, hazard_checker, nmr_predictor, structure_drawing
```

### 5. Langfuse Reachable
```bash
curl http://localhost:3000
# Expected: 200 OK (Langfuse web UI)
```

### 6. Chat Message Submission
```bash
# Submit a simple message to test message flow
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-conv-1",
    "messages": [{"role": "user", "content": "Hello, what is your name?"}]
  }'
# Expected: streaming response with message tokens
```

### 7. Tool Invocation (Hazard Check)
```bash
# Submit a message that triggers hazard checking
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-conv-1",
    "messages": [{"role": "user", "content": "List harmful chemicals"}]
  }'
# Expected: message processed, hazard checker may flag unsafe content
```

---

## Cleanup

```bash
# Stop services
docker compose down

# Remove test branch
git checkout osn-pre-main
git branch -D test-pre-main_stas
```

---

## Expected Issues (None expected if tests pass)

If any test fails:
1. Check `docker compose logs <service>` for errors
2. Verify ports aren't in use: `lsof -i :8100` (replace with relevant port)
3. Ensure enough disk space for RAG model downloads (~2GB)
4. Check Docker daemon is running and has sufficient memory

---

## Success Criteria

All health checks pass without errors → `pre-main_stas` baseline is healthy and ready for Phase 2 merge.

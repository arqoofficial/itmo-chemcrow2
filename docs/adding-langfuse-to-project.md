# Adding LangFuse (Self-Hosted) to a Docker Compose Project

A step-by-step guide for Claude Code on integrating LangFuse v3 self-hosted tracing into an existing Docker Compose project with LangChain-based services.

---

## Overview

LangFuse is an open-source LLM observability platform. Self-hosting it requires 6 containers (server, worker, PostgreSQL, ClickHouse, MinIO, Redis) plus ClickHouse config files. Once running, you create an organization and project in the UI, generate API keys, and inject them into the services that call LLMs.

---

## Step 1: Generate Secrets for `.env`

LangFuse needs three cryptographic secrets. Add these to your `.env.example` and `.env`:

```bash
# -- Langfuse: auth secrets (MUST generate unique values) --
# NEXTAUTH_SECRET:
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
NEXTAUTH_SECRET=change_me

# SALT:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
SALT=change_me

# ENCRYPTION_KEY (must be exactly 64 hex characters):
#   openssl rand -hex 32
ENCRYPTION_KEY=change_me
```

Also add initial admin credentials (used on first launch only):

```bash
LANGFUSE_INIT_USER_EMAIL=admin@example.com
LANGFUSE_INIT_USER_NAME=Admin
LANGFUSE_INIT_USER_PASSWORD=changeme
```

And the internal DB/service credentials (safe to leave as defaults for local dev):

```bash
LANGFUSE_DB_USER=postgres
LANGFUSE_DB_PASSWORD=change_me
LANGFUSE_DB_NAME=postgres

LANGFUSE_CLICKHOUSE_USER=clickhouse
LANGFUSE_CLICKHOUSE_PASSWORD=change_me

LANGFUSE_MINIO_USER=minio
LANGFUSE_MINIO_PASSWORD=change_me

NEXTAUTH_URL=http://localhost:3000
```

Finally, add placeholders for the API keys (filled in Step 5):

```bash
# -- Langfuse: API keys for your LLM services (fill after first launch) --
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=http://langfuse-server:3000
```

> **CRITICAL:** `LANGFUSE_HOST` in `.env` should be the **Docker internal hostname** (`http://langfuse-server:3000`), not `http://localhost:3000`. The `localhost` URL only works from the host machine's browser. Inside Docker containers, `localhost` points to the container itself, causing connection refused errors. The `compose.yml` should override this explicitly for services that need it (see Step 3).

---

## Step 2: Create ClickHouse Config Files

LangFuse's ClickHouse needs two XML config snippets mounted as volumes.

### `deploy/langfuse-clickhouse/macros.xml`

```xml
<clickhouse>
    <macros>
        <shard>01</shard>
        <replica>replica01</replica>
    </macros>
</clickhouse>
```

### `deploy/langfuse-clickhouse/zookeeper.xml`

```xml
<clickhouse>
    <zookeeper>
        <node>
            <host>langfuse-zookeeper</host>
            <port>2181</port>
        </node>
    </zookeeper>
</clickhouse>
```

These are required for ClickHouse's ReplicatedMergeTree engine even in single-node mode.

---

## Step 3: Add LangFuse Services to `compose.yml`

Add the following 6 services and their volumes. The order matters because of `depends_on` health checks.

### 3a. LangFuse PostgreSQL

```yaml
langfuse-db:
  image: postgres:17
  restart: unless-stopped
  environment:
    POSTGRES_USER: ${LANGFUSE_DB_USER:-postgres}
    POSTGRES_PASSWORD: ${LANGFUSE_DB_PASSWORD:-postgres}
    POSTGRES_DB: ${LANGFUSE_DB_NAME:-postgres}
  volumes:
    - langfuse-db-data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${LANGFUSE_DB_USER:-postgres}"]
    interval: 3s
    timeout: 3s
    retries: 10
```

> This is a **separate** Postgres instance from your app's main DB. Do not share them.

### 3b. ZooKeeper (for ClickHouse)

```yaml
langfuse-zookeeper:
  image: zookeeper:3.9
  restart: unless-stopped
  environment:
    ZOO_TICK_TIME: 2000
  volumes:
    - langfuse-zookeeper-data:/data
    - langfuse-zookeeper-datalog:/datalog
  healthcheck:
    test: ["CMD-SHELL", "zkServer.sh status || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
```

### 3c. ClickHouse

```yaml
langfuse-clickhouse:
  image: clickhouse/clickhouse-server:25.8
  restart: unless-stopped
  user: "101:101"
  depends_on:
    langfuse-zookeeper:
      condition: service_healthy
  environment:
    CLICKHOUSE_DB: default
    CLICKHOUSE_USER: ${LANGFUSE_CLICKHOUSE_USER:-clickhouse}
    CLICKHOUSE_PASSWORD: ${LANGFUSE_CLICKHOUSE_PASSWORD:-clickhouse}
  volumes:
    - langfuse-clickhouse-data:/var/lib/clickhouse
    - langfuse-clickhouse-logs:/var/log/clickhouse-server
    - ./deploy/langfuse-clickhouse/macros.xml:/etc/clickhouse-server/config.d/langfuse-macros.xml:ro
    - ./deploy/langfuse-clickhouse/zookeeper.xml:/etc/clickhouse-server/config.d/langfuse-zookeeper.xml:ro
  healthcheck:
    test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8123/ping"]
    interval: 5s
    timeout: 5s
    retries: 10
    start_period: 1s
```

### 3d. LangFuse MinIO (blob storage for events/media)

```yaml
langfuse-minio:
  image: cgr.dev/chainguard/minio
  restart: unless-stopped
  entrypoint: sh
  command: -c 'mkdir -p /data/langfuse && minio server --address ":9000" --console-address ":9001" /data'
  environment:
    MINIO_ROOT_USER: ${LANGFUSE_MINIO_USER:-minio}
    MINIO_ROOT_PASSWORD: ${LANGFUSE_MINIO_PASSWORD:-miniosecret}
  ports:
    - "9090:9000"
  volumes:
    - langfuse-minio-data:/data
  healthcheck:
    test: ["CMD", "mc", "ready", "local"]
    interval: 1s
    timeout: 5s
    retries: 5
    start_period: 1s
```

> This is separate from any app-level MinIO. Port-map to a different host port (e.g. `9090`) to avoid conflicts.

### 3e. LangFuse Redis (cache)

```yaml
langfuse-cache:
  image: redis:7
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 3s
    timeout: 3s
    retries: 10
```

> **Important:** This is a **separate** Redis from your app's Redis. If your app's `.env` sets `REDIS_AUTH` or `REDIS_CONNECTION_STRING`, LangFuse will read those too (since it uses `env_file: .env`). You **must** explicitly override `REDIS_CONNECTION_STRING` and `REDIS_HOST`/`REDIS_PORT` in the `langfuse-server` and `langfuse-worker` environment blocks (see below) to point at `langfuse-cache`, not your app Redis. Otherwise LangFuse will try to AUTH against a Redis that has no password set, and fail silently.

### 3f. LangFuse Server

```yaml
langfuse-server:
  image: langfuse/langfuse:3
  restart: unless-stopped
  depends_on:
    langfuse-db:
      condition: service_healthy
    langfuse-clickhouse:
      condition: service_healthy
    langfuse-minio:
      condition: service_healthy
    langfuse-cache:
      condition: service_healthy
  ports:
    - "3000:3000"
  env_file:
    - .env
  environment:
    DATABASE_URL: postgresql://${LANGFUSE_DB_USER:-postgres}:${LANGFUSE_DB_PASSWORD:-postgres}@langfuse-db:5432/${LANGFUSE_DB_NAME:-postgres}
    NEXTAUTH_URL: ${NEXTAUTH_URL:-http://localhost:3000}
    NEXTAUTH_SECRET: ${NEXTAUTH_SECRET}
    SALT: ${SALT}
    ENCRYPTION_KEY: ${ENCRYPTION_KEY}
    CLICKHOUSE_URL: http://langfuse-clickhouse:8123
    CLICKHOUSE_MIGRATION_URL: clickhouse://langfuse-clickhouse:9000
    CLICKHOUSE_USER: ${LANGFUSE_CLICKHOUSE_USER:-clickhouse}
    CLICKHOUSE_PASSWORD: ${LANGFUSE_CLICKHOUSE_PASSWORD:-clickhouse}
    CLICKHOUSE_CLUSTER_ENABLED: "false"
    # CRITICAL: override any REDIS_CONNECTION_STRING from .env
    REDIS_CONNECTION_STRING: redis://langfuse-cache:6379/0
    REDIS_HOST: langfuse-cache
    REDIS_PORT: "6379"
    LANGFUSE_CACHE_ENABLED: "true"
    # S3 event upload (points at langfuse-minio, not your app MinIO)
    LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
    LANGFUSE_S3_EVENT_UPLOAD_REGION: auto
    LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: ${LANGFUSE_MINIO_USER:-minio}
    LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: ${LANGFUSE_MINIO_PASSWORD:-miniosecret}
    LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://langfuse-minio:9000
    LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
    LANGFUSE_S3_EVENT_UPLOAD_PREFIX: "events/"
    # S3 media upload
    LANGFUSE_S3_MEDIA_UPLOAD_BUCKET: langfuse
    LANGFUSE_S3_MEDIA_UPLOAD_REGION: auto
    LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID: ${LANGFUSE_MINIO_USER:-minio}
    LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY: ${LANGFUSE_MINIO_PASSWORD:-miniosecret}
    LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT: http://localhost:9090
    LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE: "true"
    LANGFUSE_S3_MEDIA_UPLOAD_PREFIX: "media/"
    # Initial admin
    LANGFUSE_INIT_USER_EMAIL: ${LANGFUSE_INIT_USER_EMAIL:-admin@example.com}
    LANGFUSE_INIT_USER_NAME: ${LANGFUSE_INIT_USER_NAME:-Admin}
    LANGFUSE_INIT_USER_PASSWORD: ${LANGFUSE_INIT_USER_PASSWORD:-changeme}
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3000/api/public/health"]
    interval: 10s
    timeout: 5s
    retries: 10
    start_period: 60s
```

### 3g. LangFuse Worker

```yaml
langfuse-worker:
  image: langfuse/langfuse-worker:3
  restart: unless-stopped
  depends_on:
    langfuse-db:
      condition: service_healthy
    langfuse-clickhouse:
      condition: service_healthy
    langfuse-minio:
      condition: service_healthy
    langfuse-cache:
      condition: service_healthy
  env_file:
    - .env
  environment:
    DATABASE_URL: postgresql://${LANGFUSE_DB_USER:-postgres}:${LANGFUSE_DB_PASSWORD:-postgres}@langfuse-db:5432/${LANGFUSE_DB_NAME:-postgres}
    NEXTAUTH_URL: ${NEXTAUTH_URL:-http://localhost:3000}
    SALT: ${SALT}
    ENCRYPTION_KEY: ${ENCRYPTION_KEY}
    CLICKHOUSE_URL: http://langfuse-clickhouse:8123
    CLICKHOUSE_MIGRATION_URL: clickhouse://langfuse-clickhouse:9000
    CLICKHOUSE_USER: ${LANGFUSE_CLICKHOUSE_USER:-clickhouse}
    CLICKHOUSE_PASSWORD: ${LANGFUSE_CLICKHOUSE_PASSWORD:-clickhouse}
    CLICKHOUSE_CLUSTER_ENABLED: "false"
    # CRITICAL: same Redis override as langfuse-server
    REDIS_CONNECTION_STRING: redis://langfuse-cache:6379/0
    REDIS_HOST: langfuse-cache
    REDIS_PORT: "6379"
    LANGFUSE_CACHE_ENABLED: "true"
    LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
    LANGFUSE_S3_EVENT_UPLOAD_REGION: auto
    LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: ${LANGFUSE_MINIO_USER:-minio}
    LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: ${LANGFUSE_MINIO_PASSWORD:-miniosecret}
    LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://langfuse-minio:9000
    LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
    LANGFUSE_S3_EVENT_UPLOAD_PREFIX: "events/"
    LANGFUSE_S3_MEDIA_UPLOAD_BUCKET: langfuse
    LANGFUSE_S3_MEDIA_UPLOAD_REGION: auto
    LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID: ${LANGFUSE_MINIO_USER:-minio}
    LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY: ${LANGFUSE_MINIO_PASSWORD:-miniosecret}
    LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT: http://localhost:9090
    LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE: "true"
    LANGFUSE_S3_MEDIA_UPLOAD_PREFIX: "media/"
```

### 3h. Volumes

Add to your `volumes:` section:

```yaml
volumes:
  langfuse-db-data:
  langfuse-zookeeper-data:
  langfuse-zookeeper-datalog:
  langfuse-clickhouse-data:
  langfuse-clickhouse-logs:
  langfuse-minio-data:
```

---

## Step 4: Add the `langfuse` Python Package to Your Services

For each Python service that makes LLM calls and should send traces:

```bash
# In the service's directory (e.g. services/ai-agent/)
uv add "langfuse>=4.0.0"
```

Or manually add `"langfuse>=4.0.0"` to the `dependencies` list in that service's `pyproject.toml`, then run `uv lock` from the repo root.

---

## Step 5: First Launch — Create Organization, Project, and API Keys

### 5a. Start the stack

```bash
docker compose up --build -d
```

Wait for LangFuse to be healthy. It takes ~60 seconds on first launch (DB migrations + ClickHouse setup). Check:

```bash
docker compose logs -f langfuse-server
# Look for: "Listening on port 3000"
```

### 5b. Open LangFuse in the browser

Open `http://localhost:3000` in your browser.

> You can use the **Playwright MCP** to automate this if running headless. Example:
> ```
> browser_navigate to http://localhost:3000
> ```

### 5c. Log in

Use the initial admin credentials from `.env`:
- Email: `admin@example.com` (or whatever `LANGFUSE_INIT_USER_EMAIL` is set to)
- Password: `changeme` (or whatever `LANGFUSE_INIT_USER_PASSWORD` is set to)

### 5d. Create an Organization

After logging in, LangFuse will prompt you to create an organization if none exists. Give it any name (e.g. your project name).

### 5e. Create a Project

Inside the organization, create a project. Name it something meaningful (e.g. `ai-agent`, `pdf-parser`, or one shared project name).

### 5f. Generate API Keys

1. Go to **Settings** (gear icon) in the LangFuse UI
2. Navigate to **API Keys**
3. Click **Create API Key**
4. Copy the **Secret Key** (`sk-lf-...`) and **Public Key** (`pk-lf-...`)

### 5g. Update `.env` with the keys

```bash
LANGFUSE_SECRET_KEY=sk-lf-XXXXXXXX
LANGFUSE_PUBLIC_KEY=pk-lf-XXXXXXXX
LANGFUSE_HOST=http://langfuse-server:3000
```

> **WARNING:** The LangFuse UI shows a "Host" or "API URL" field — it will display `http://localhost:3000`. **This URL is invalid for Docker containers.** Always use `http://langfuse-server:3000` (the Docker service name) in your `.env` and service configs. The `localhost` URL only works from the host machine's browser, not from inside Docker.

### 5h. Restart the services that send traces

```bash
docker compose restart ai-agent pdf-parser
# Or restart any other services that use the Langfuse keys
```

This is necessary because the services read `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` at startup. Without a restart, they still have the empty values.

---

## Step 6: Add Tracing Code to Your Python Services

### Pattern A: LangChain CallbackHandler (recommended for LangChain/LangGraph)

```python
# tracing.py
import logging
from your_config import settings

logger = logging.getLogger(__name__)


def get_langfuse_handler():
    """Return a Langfuse CallbackHandler if configured, else None."""
    if not (settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_HOST):
        return None

    import os
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST

    from langfuse.langchain import CallbackHandler
    return CallbackHandler()


def get_langfuse_config() -> dict:
    """Return a LangChain config dict with Langfuse callbacks, or {} if not configured."""
    handler = get_langfuse_handler()
    if handler is None:
        return {}
    return {"callbacks": [handler]}


def check_langfuse_auth() -> bool:
    """Check Langfuse auth at startup. Returns True if OK."""
    if not (settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY):
        logger.warning("Langfuse tracing disabled — set LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY")
        return False
    try:
        from langfuse import Langfuse
        client = Langfuse(
            secret_key=settings.LANGFUSE_SECRET_KEY,
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            host=settings.LANGFUSE_HOST,
        )
        client.auth_check()
        logger.info("Langfuse tracing enabled — host=%s", settings.LANGFUSE_HOST)
        return True
    except Exception:
        logger.exception("Langfuse auth check failed — tracing disabled")
        return False
```

Usage in FastAPI startup:

```python
from tracing import check_langfuse_auth, get_langfuse_config

@app.on_event("startup")
async def startup():
    check_langfuse_auth()

# In your LLM call endpoints:
lf_config = get_langfuse_config()
result = await agent.ainvoke(input, config=lf_config)

# For sync calls, flush after:
for cb in lf_config.get("callbacks", []):
    if hasattr(cb, "flush"):
        cb.flush()
```

### Pattern B: Direct Langfuse client (for non-LangChain services)

```python
def _build_langfuse_handler():
    if not settings.LANGFUSE_PUBLIC_KEY:
        return None
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        lf = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL,
        )
        if not lf.auth_check():
            log.warning("Langfuse auth_check failed — tracing disabled")
            return None
        return CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL,
        )
    except Exception:
        log.warning("Langfuse unavailable — tracing disabled")
        return None
```

### Config model (add to your service's `config.py` / `Settings`)

```python
# Langfuse observability (optional)
LANGFUSE_PUBLIC_KEY: str = ""
LANGFUSE_SECRET_KEY: str = ""
LANGFUSE_HOST: str = "http://langfuse-server:3000"
```

---

## Step 7: Override `LANGFUSE_HOST` in `compose.yml` for Each Service

In each service's `environment:` block in `compose.yml`, **explicitly set** the internal hostname:

```yaml
ai-agent:
  environment:
    # .env often has LANGFUSE_HOST=http://localhost:3000 for browser use;
    # inside containers, localhost != Langfuse. Override explicitly.
    - LANGFUSE_HOST=http://langfuse-server:3000
```

This is critical. Even if `.env` has the correct value, a future user might change it to `localhost:3000` for the browser. The compose override makes the internal URL authoritative for containers.

---

## Pitfalls and Gotchas

### The localhost Trap
`LANGFUSE_HOST=http://localhost:3000` works in `.env` for the browser UI but **breaks** inside Docker containers. Always override with the Docker service name in compose.

### Redis Collision
If your app uses `REDIS_AUTH` or `REDIS_CONNECTION_STRING` in `.env`, LangFuse's `env_file: .env` will pick those up. The LangFuse containers will try to authenticate against your app Redis instead of `langfuse-cache`. Always explicitly set `REDIS_CONNECTION_STRING`, `REDIS_HOST`, and `REDIS_PORT` in both `langfuse-server` and `langfuse-worker` environment blocks.

### LangFuse Strips Empty Env Vars
LangFuse deletes environment variables with value `""` before parsing. If your `.env` has `REDIS_AUTH=` (empty), LangFuse ignores it. But if it has `REDIS_AUTH=somepassword`, LangFuse will use it. This is why the explicit override in compose is necessary.

### ClickHouse Needs Config Files
Without `macros.xml` and `zookeeper.xml`, ClickHouse fails to start. These are tiny files but **required**.

### First Startup Is Slow
LangFuse runs DB migrations on first boot. The healthcheck has `start_period: 60s` for this reason. Don't assume it's broken if it takes a minute.

### API Keys Are Per-Project
Each LangFuse project has its own API keys. If you have multiple services (e.g. `ai-agent` and `pdf-parser`), you can either:
- Use one shared project and one set of keys (simpler)
- Create separate projects with separate keys (better isolation in the UI)

### Graceful Degradation
Always make LangFuse optional. If keys are missing or auth fails, log a warning and continue without tracing. Never let LangFuse unavailability break your LLM service.

---

## Quick Checklist

- [ ] Generated `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY` and added to `.env`
- [ ] Created `deploy/langfuse-clickhouse/macros.xml` and `zookeeper.xml`
- [ ] Added all 6 LangFuse services + volumes to `compose.yml`
- [ ] Added `langfuse` Python package to services that need tracing
- [ ] Ran `docker compose up --build -d` and waited for healthy status
- [ ] Opened `http://localhost:3000`, logged in with init credentials
- [ ] Created organization and project in LangFuse UI
- [ ] Generated API keys (Settings -> API Keys)
- [ ] Added `LANGFUSE_SECRET_KEY` and `LANGFUSE_PUBLIC_KEY` to `.env`
- [ ] Verified `LANGFUSE_HOST` is `http://langfuse-server:3000` (not localhost!) in `.env`
- [ ] Added `LANGFUSE_HOST=http://langfuse-server:3000` override in compose for each LLM service
- [ ] Restarted LLM services: `docker compose restart <service-name>`
- [ ] Verified traces appear in LangFuse UI after making an LLM call

---

## Automating Step 5 with Playwright MCP

If you have the Playwright MCP available, you can automate the browser steps:

```
1. browser_navigate to http://localhost:3000
2. browser_snapshot to see the login page
3. browser_fill_form with email and password fields
4. browser_click the login button
5. browser_snapshot to see the dashboard
6. Navigate to Settings -> API Keys
7. browser_click "Create API Key"
8. browser_snapshot to capture the generated keys
9. Copy sk-lf-... and pk-lf-... values into .env
```

This is useful when running on a remote server or in CI where you can't easily open a browser.

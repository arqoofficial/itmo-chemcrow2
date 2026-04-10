# Fix: nginx 502 Bad Gateway After Container Restarts

## Problem

When Docker containers restart (e.g. after `docker compose down` / `up`, or after running `prestart`), nginx inside the frontend container caches the old IP of the `backend` container at startup. If the backend gets a new IP, nginx keeps proxying to the dead old IP → **502 Bad Gateway** on all `/api` calls.

nginx resolves upstream hostnames **once at startup** and caches them indefinitely by default. Docker may assign a different IP to the backend container on the next run.

## Quick Fix (when it happens)

Reload nginx inside the running frontend container to force DNS re-resolution:

```bash
docker compose exec frontend nginx -s reload
```

## Permanent Fix

Add a `resolver` directive to `frontend/nginx-ip.conf` so nginx re-resolves Docker's internal DNS periodically:

```nginx
server {
    listen 80;

    # Use Docker's internal DNS resolver, re-resolve every 10s
    resolver 127.0.0.11 valid=10s;

    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri /index.html =404;
    }

    location /api/v1/events/ {
        set $backend_upstream http://backend:8000;
        proxy_pass $backend_upstream/api/v1/events/;
        # ... rest of config
    }

    location /api {
        set $backend_upstream http://backend:8000;
        proxy_pass $backend_upstream/api;
        # ... rest of config
    }
}
```

> **Important:** nginx only respects the `resolver` + `valid=` for dynamic re-resolution when the upstream is stored in a **variable** (`set $var`). With a hardcoded `proxy_pass http://backend:8000/...`, it still resolves once at startup even if `resolver` is present. Use `set $upstream ...; proxy_pass $upstream/...;` to activate dynamic re-resolution.

## Root Cause Checklist

If you see 502 after a restart:

1. **Check if nginx DNS cache is stale** — curl from inside the container works but nginx doesn't:
   ```bash
   docker compose exec frontend curl -s http://backend:8000/api/v1/utils/health-check/
   ```
   If this returns `true` but the browser gets 502, stale DNS is the cause.

2. **Quick reload:**
   ```bash
   docker compose exec frontend nginx -s reload
   ```

3. **Check `prestart` ran** — if the DB has no users, `prestart` was skipped:
   ```bash
   docker compose exec db psql -U postgres -d app -c 'SELECT email FROM "user" LIMIT 5;'
   ```
   If empty, run:
   ```bash
   docker compose run --rm prestart
   ```

## Why `prestart` Sometimes Doesn't Run

`prestart` is defined as a one-shot service in `compose.yml`. Running `docker compose up` does **not** re-run services that have already completed. After a `docker compose down -v` (volumes removed) you must explicitly re-run it:

```bash
docker compose run --rm prestart
docker compose up -d
```

Or add it to your startup script so it always runs before bringing up the stack.

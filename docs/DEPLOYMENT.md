# TwinSphere AI — Deployment Guide

This guide covers deploying TwinSphere to a server or cloud environment.
It does **not** deploy anything automatically — complete the steps below on
your own infrastructure with your own credentials.

---

## Architecture recap

| Component | Tech | Default port | Notes |
|-----------|------|-------------|-------|
| Frontend | React 18 + Vite, served by nginx | 3000 (container) / 5173 (dev) | Static SPA |
| Backend | FastAPI + uvicorn | 8000 | REST + WebSocket |
| Database | SQLite (dev) or PostgreSQL 16 | — / 5432 | SQLite file or compose volume |

The frontend talks to the backend via same-origin `/api`, `/health`, and `/ws`
proxied by nginx (container) or the Vite dev server (local).

---

## Path 1 — Docker Compose (recommended for servers)

### 1. Prepare the environment

```bash
cp .env.example .env
# generate a strong secret
python -c "import secrets; print(secrets.token_urlsafe(48))"
# edit .env: set JWT_SECRET, APP_ENV=production, CORS_ORIGINS, POSTGRES_PASSWORD
```

Required `.env` values for production:

| Variable | Value |
|----------|-------|
| `APP_ENV` | `production` |
| `JWT_SECRET` | ≥ 32-char random string (never the dev default) |
| `CORS_ORIGINS` | your frontend origin, e.g. `https://twin.example.com` |
| `POSTGRES_PASSWORD` | strong password (if using the Postgres profile) |

### 2. Start services

```bash
# SQLite (simplest)
docker compose up -d --build

# PostgreSQL
docker compose --profile postgres up -d --build
# then set DATABASE_URL=postgresql+psycopg2://twin:${POSTGRES_PASSWORD}@postgres:5432/twinsphere
```

### 3. Run migrations (explicit, safe)

The backend runs `init_db()` (create_all) on first boot.  For Alembic-managed
schema (recommended for production upgrades):

```bash
docker compose exec backend alembic upgrade head
```

### 4. Create the first administrator

Demo users are **disabled** in production.  Bootstrap an admin:

```bash
docker compose exec backend \
  env BOOTSTRAP_ADMIN_PASSWORD='<strong-password>' \
  python -m app.services.bootstrap_admin --username admin --email you@example.com
```

### 5. Verify

```bash
curl http://localhost:8000/health
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/system/status
```

### 6. Validate Compose syntax (without building)

```bash
docker compose config
```

This prints the resolved configuration and fails if required variables
(`JWT_SECRET`, `POSTGRES_PASSWORD`) are missing.

---

## Path 2 — manual (no Docker)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # or pip install -r requirements.txt on Linux
export APP_ENV=production
export JWT_SECRET='<strong-secret>'
export DATABASE_URL='postgresql+psycopg2://user:pass@host:5432/twinsphere'
export CORS_ORIGINS='https://twin.example.com'
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Use a process manager (systemd, NSSM, pm2) for restart-on-failure.

### Frontend

```bash
cd frontend
npm ci
npm run build          # produces dist/
# serve dist/ with any static host (nginx, Caddy, S3+CloudFront, …)
# proxy /api, /health, /ws to the backend
```

Example nginx site (see `frontend/nginx.conf` for the full container config):

```nginx
server {
    listen 443 ssl;
    server_name twin.example.com;
    root /var/www/twinsphere/dist;
    location / { try_files $uri $uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; }
    location /health { proxy_pass http://127.0.0.1:8000; }
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

---

## HTTPS / TLS

- Terminate TLS at the reverse proxy (nginx, Caddy, ALB).
- Set `HSTS_ENABLED=true` only when serving over HTTPS.
- The backend sets security headers (nosniff, frame-options, CSP, etc.) when
  `SECURITY_HEADERS_ENABLED=true` (default).

## WebSockets

- The backend upgrades `/ws` after an auth message (`{"type":"auth","token":"<jwt>"}`).
- The reverse proxy must forward `Upgrade` / `Connection` headers and allow
  long read timeouts (see nginx config above).
- Frontend WS URL: same-origin `/ws` by default; override with `VITE_WS_URL`
  at build time if the backend is on a different host.

## Environment variables

Never bake `.env` or secrets into images.  Pass them via the compose
`environment:` block or your process manager's environment.  The frontend
build only sees `VITE_*` variables — **never** put backend credentials there.

## CORS

Set `CORS_ORIGINS` to the exact frontend origin(s).  A wildcard `*` is
refused at startup (Phase 10 §12).

## Health checks

- `GET /health` — liveness: returns `status`, `backend`, `database`,
  `simulation_engine`, `ai_engine`, `version`.  Does **not** expose secrets.
- `GET /api/system/status` — readiness-style detail (requires auth).
- Docker healthcheck probes `/health` every 30 s.

## Logs

- Structured Python logging (`%(asctime)s %(levelname)s %(name)s: %(message)s`).
- Every request gets an `X-Request-ID` (client-supplied or generated);
  unhandled errors log the full traceback server-side and return a generic
  500 to the client.
- Docker: `docker compose logs -f backend`.

## Persistent storage

| Profile | Volume | Path |
|---------|--------|------|
| SQLite (default) | `twin-data` | `/data/twinsphere.db` in container |
| PostgreSQL | `pgdata` | `/var/lib/postgresql/data` |

Back up the volume or run `pg_dump` on a schedule (see `docs/OPERATIONS.md`).

## Rollback

1. `docker compose down` (keeps volumes).
2. `git checkout <previous-tag>`.
3. `docker compose up -d --build`.
4. `docker compose exec backend alembic downgrade -1` if the schema changed.

## Vercel / static hosts (frontend only)

Vercel, Netlify, or S3+CloudFront can host the frontend static build.
They do **not** run the FastAPI backend or PostgreSQL — deploy those to a
separate VM, container service, or platform (Fly.io, Railway, Render, ECS).
Point `VITE_API_URL` / `VITE_WS_URL` at the backend origin at build time, or
proxy through a same-origin reverse proxy.

---

## What this guide does NOT do

- It does not deploy to a live production service (no credentials were used).
- It does not configure a real LLM provider (the deterministic analyst
  fallback works without one).
- It does not connect real IoT sensors or emergency services — all data is
  simulated.

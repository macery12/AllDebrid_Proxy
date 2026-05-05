# Backend Notes — Vite SPA Integration

This document tracks changes made to `frontend/app.py` and any remaining work
needed to run the new Vite + React frontend in production.

---

## Changes already applied

### `frontend/app.py` — new JSON API v2 routes

A `# JSON API v2` section was appended to the end of `frontend/app.py`
(before `if __name__ == "__main__"`). These routes serve the Vite SPA:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v2/auth/setup-status` | public | First-time setup flag |
| POST | `/v2/auth/login` | public | JSON login + first-time admin creation |
| POST | `/v2/auth/logout` | session | Destroys Flask session |
| GET | `/v2/auth/me` | session | Returns current user object |
| GET | `/v2/health` | public | Proxies FastAPI `/health` |
| GET | `/v2/tasks` | member | Lists tasks (admin: all, member: own) |
| POST | `/v2/tasks` | member | Creates task from magnet / URL |
| POST | `/v2/tasks/from-torrent` | member | Creates task from `.torrent` upload |
| GET | `/v2/tasks/<id>` | member | Returns single task JSON |
| POST | `/v2/tasks/<id>/sse-token` | member | Obtains short-lived FastAPI SSE token |
| POST | `/v2/tasks/<id>/select` | member | Submits file selection |
| POST | `/v2/tasks/<id>/cancel` | member | Cancels running task |
| DELETE | `/v2/tasks/<id>` | member | Deletes task (`?purge_files=true`) |
| GET | `/v2/tasks/<id>/files` | session | Returns filesystem file listing as JSON |
| GET/GET | `/app/` + `/app/<path>` | public | Serves Vite SPA (`frontend/static/dist/`) |

All `/v2/` routes return JSON and never `flash()` or redirect.  
`login_manager.unauthorized_handler` still redirects for the old HTML routes;
the SPA's `api/client.ts` detects the resulting redirect (or 401) and sends
the user to `/login`.

---

## Build process

```bash
# From repo root
cd frontend-v2
npm install
npm run build
# Outputs to: frontend/static/dist/
```

The Vite config (`vite.config.ts`) sets `build.outDir = '../frontend/static/dist'`.

---

## Production serving

`frontend/app.py` now exposes `/app/` and `/app/<path>` routes that serve the
built SPA from `frontend/static/dist/`. This means:

- Flask at port 9732 handles HTML, API (old `/tasks/`, etc.), downloads (`/d/`), and the new `/v2/` JSON API.
- The SPA lives at `https://your-host/app/` (or whatever nginx rewrites).
- Old Jinja routes (`/`, `/tasks/<id>`, etc.) are **unaffected** — both UIs
  co-exist until the old routes are removed.

### Nginx change (optional)

If you want the SPA to live at `/` instead of `/app/`, add this to `nginx/debrid.conf`:

```nginx
# Rewrite bare / to the SPA
location / {
    try_files $uri @spa;
}

location @spa {
    proxy_pass http://flask:9732;
    # Flask's /app/<path> catch-all serves index.html for unknown paths
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Host $host;
}
```

Alternatively, update Flask's `serve_vite_spa` route to respond on `/` instead
of `/app/` once the old Jinja routes are decommissioned.

---

## Dev workflow

```bash
# Terminal 1 — FastAPI backend
docker-compose up api worker

# Terminal 2 — Flask frontend
cd frontend && python app.py

# Terminal 3 — Vite dev server (http://localhost:5173)
cd frontend-v2 && npm run dev
```

Vite proxies:
- `/v2/*` → `http://localhost:5000` (Flask)
- `/api/*` → `http://localhost:8080` (FastAPI, for SSE)
- `/d/*` → `http://localhost:5000` (Flask file downloads)

---

## Remaining work (optional)

- [ ] Decommission old Jinja routes once the SPA is confirmed stable
- [ ] Move SPA root from `/app/` to `/` in Flask + nginx
- [ ] Add Content-Security-Policy header that covers the SPA's origin
- [ ] Automated CI step: `npm run build` as part of Docker image build
      (see `Dockerfile.frontend` — currently it copies `frontend/` only)
- [ ] `Dockerfile.frontend` should `COPY frontend-v2 /app/frontend-v2` and
      run `npm ci && npm run build` so the dist is baked in at image build time

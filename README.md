# AllDebrid Proxy

A self-hosted proxy that integrates with [AllDebrid](https://alldebrid.com) to download torrents and direct links at full speed, then re-serve the files to anyone you share the task link with — including in-browser video streaming.

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [User Roles & Access Control](#user-roles--access-control)
- [Download Sources](#download-sources)
- [Admin Panel](#admin-panel)
- [HTTPS Setup (Strongly Recommended)](#https-setup-strongly-recommended)
- [API Reference](#api-reference)
- [Development & Testing](#development--testing)
- [Upgrading](#upgrading)

---

## Architecture

The application is composed of six Docker services that communicate over isolated networks:

| Service | Container | Image | Purpose |
|---|---|---|---|
| `api` | `proxy_api` | Custom (FastAPI) | REST API, task management, SSE |
| `frontend` | `proxy_frontend` | Custom (Flask + Gunicorn) | Web UI, file serving, streaming |
| `worker` | `proxy_worker` | Custom (Python) | AllDebrid polling + aria2 dispatch |
| `db` | `proxy_db` | `postgres:15` | Users, tasks, files (persistent) |
| `redis` | `proxy_redis` | `redis:alpine` | Task queue, pub/sub, caching |
| `aria2` | `proxy_aria2` | `p3terx/aria2-pro` | Multi-connection file downloader |

```
Browser ──► [Frontend :9732] ──► [API :9731] ──► [Worker]
                                    │                │
                                  [DB]           [Aria2 :16800]
                                  [Redis] ◄──────────┘
```

A shared bind-mount (`STORAGE_PATH` → `/srv/storage`) is used by every container so that downloaded files are immediately accessible to the frontend for serving.

---

## Features

### 📥 Downloads
- **Magnet links & torrents** — paste a magnet link or upload a `.torrent` file to start a download
- **Premium file hosts** — debrid unlocks and caches files from 30+ supported hosts including Mega, Rapidgator, 1fichier, Google Drive, and more
- **Direct links** — paste any supported URL and let AllDebrid handle the rest
- **No duplicates** — submitting the same link reuses the existing task automatically

### 📺 Streaming & Files
- Stream browser-native formats (`.mp4`, `.webm`, `.mp3`, etc.) directly — no transcoding required (more format support coming soon)
- Download individual files or grab everything as a `.tar.gz` archive

### 📊 Dashboard
- Live download progress with speed and ETA
- Storage usage at a glance
- Task and file stats updated in real time

### 🔐 Accounts & Roles
- Three access levels: **admin**, **member**, and **user** (see [User Roles](#user-roles--access-control))
- First-run wizard to create the initial admin account
- Per-user download history and stats

### 🛡️ Security
- CSRF protection, login rate limiting, and safe file serving out of the box
- No sensitive paths or credentials ever exposed to the browser
---

## Quick Start

### Prerequisites
- Docker and Docker Compose v2
- An [AllDebrid](https://alldebrid.com) account and API key

### 1. Clone & configure

```bash
git clone https://github.com/macery12/AllDebrid_Proxy.git
cd AllDebrid_Proxy
cp .env.example .env
```

Open `.env` and set **at minimum** the three secrets:

```dotenv
WORKER_API_KEY=<random string, min 8 chars>
FLASK_SECRET=<random string>
ALLDEBRID_API_KEY=<your AllDebrid API key>
```

> **Tip:** `python -c "import secrets; print(secrets.token_hex(32))"` generates a secure random value.

### 2. Start

```bash
docker compose up -d
```

The `migrations` service runs Alembic automatically before the API starts, so the database schema is always up to date.

### 3. First-time setup

Navigate to **http://localhost:9732/login** — since no users exist yet, you'll be redirected to a one-time admin account creation wizard. Once your account is created, it is recommended to proceed to the next step to set up SSL before accessing the service remotely.

### 4. Add downloads

- Paste a magnet link or URL into the input box and click **Create Task**.
- You'll be redirected to the task page where download progress is shown in real time.
- Once the download completes, click **Open Files** to browse your proxied files.
---

## Configuration

All configuration is driven by environment variables defined in `.env` (or passed directly to Docker Compose).

| Variable | Default | Description |
|---|---|---|
| `WORKER_API_KEY` | `change-me` | Shared secret between the frontend and the API. **Must be changed.** |
| `FLASK_SECRET` | `change-me` | Flask session signing key. **Must be changed.** |
| `ALLDEBRID_API_KEY` | _(empty)_ | Your AllDebrid API key. |
| `ALLDEBRID_AGENT` | `Generic-PC` | User-agent string reported to AllDebrid. |
| `STORAGE_PATH` | `/srv/storage` | Host path bind-mounted as `/srv/storage` in all containers. |
| `STORAGE_ROOT` | `/srv/storage` | In-container path used by the API and worker. Should match the mount target. |
| `LOW_SPACE_FLOOR_GB` | `10` | Warning threshold for available disk space (GB). |
| `ARIA2_RPC_URL` | `http://aria2:16800/jsonrpc` | Aria2 JSON-RPC endpoint. |
| `ARIA2_RPC_SECRET` | `change-me` | Aria2 RPC authentication secret. |
| `ARIA2_SPLITS` | `4` | Parallel connections per file download. |
| `PER_TASK_MAX_ACTIVE` | `2` | Max simultaneous active downloads per task. |
| `DATABASE_URL` | _(postgres default)_ | SQLAlchemy connection string. |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string. |
| `API_PORT` | `9731` | Host port exposed for the FastAPI service. |
| `FRONTEND_PORT` | `9732` | Host port exposed for the Flask frontend. |
| `ARIA2_RPC_PORT` | `16800` | Host port exposed for the aria2 RPC interface. |
| `RETENTION_DAYS` | `7` | Days before completed tasks are auto-purged. |
| `PARTIAL_MAX_AGE_HOURS` | `24` | Hours before incomplete/stalled downloads are cleaned up. |

---

## User Roles & Access Control

Every request to the application requires a valid session. There are three roles:

| Role | Home/tasks page | Admin dashboard | User management | Download pages |
|---|:---:|:---:|:---:|:---:|
| **admin** | ✅ | ✅ | ✅ | ✅ |
| **member** | ✅ | ❌ | ❌ | ✅ |
| **user** | ❌ | ❌ | ❌ | ✅ |

- **Admin** — full access. Can create tasks, upload files, manage users, and view the admin dashboard.
- **Member** — can create tasks and download files, but cannot access admin pages.
- **User** — download-only. Useful for sharing specific task links with friends without giving them the ability to create new downloads.

Users attempting to access pages above their permission level see an "Access Denied" page.

---

## Download Sources

### Magnet Links
Paste any `magnet:?xt=urn:btih:…` URI. AllDebrid fetches and caches the torrent, then the worker downloads each file via aria2.

### Direct Links (HTTP/HTTPS)
Paste a direct URL. AllDebrid unlocks it (removing rate limits and captchas from supported hosters), then aria2 downloads it at full speed.

### Torrent File Upload
- Drag-and-drop or select one or more `.torrent` files (max 10 MB each).
- The backend parses the file **entirely in memory** using `bencodepy`, extracts the SHA-1 infohash and all tracker tiers, builds a magnet URI, and discards the original bytes — the `.torrent` file is never written to disk or stored in the database.

### Admin File Upload
- Available only to **admin** users from the main page.
- Upload any file up to **10 GB**.
- The file is saved to `/srv/storage/<task-id>/files/<filename>` and immediately available as a completed task.
- A shareable download link is created that works exactly like any other task link.

---

## Admin Panel

Access the admin panel at `/admin` (admin role required).

### Dashboard (`/admin`)
- System-wide task counts by status
- Active download progress
- Storage utilization

### Task List (`/admin/tasks`)
- View all tasks across all users
- Cancel or delete tasks

### User Management (`/admin/users`)
- Create new users and assign roles (admin / member / user)
- Reset passwords
- Promote or demote users
- Delete users (you cannot delete your own account)
- View per-user statistics (tasks created, files downloaded, bytes downloaded)

---

## HTTPS Setup (Strongly Recommended)

> ⚠️ **Running the proxy over plain HTTP means that login credentials, session cookies, and every file you download are transmitted in the clear.** Anyone on the same network — or any hop between your server and the browser — can read or modify them. **Always use HTTPS when the service is reachable from outside your local machine.**

The included `nginx/debrid.conf` is a production-ready Nginx configuration that handles:

- Automatic HTTP → HTTPS redirect (port 80 → 443)
- TLS 1.2 / 1.3 termination via a free Let's Encrypt certificate (Certbot)
- Reverse proxy to the API (`:9731`) with SSE-safe settings (buffering off, 1-hour read timeout)
- Reverse proxy to the frontend (`:9732`) with range-request passthrough for video seeking
- Support for uploads up to 10 GB (`client_max_body_size 10G`)

### Step 1 — Point a domain at your server

Create an **A record** (and optionally `AAAA` for IPv6) for your domain or subdomain pointing to your server's public IP. DNS changes can take a few minutes to propagate.

### Step 2 — Install Nginx and Certbot

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

### Step 3 — Obtain a TLS certificate

```bash
sudo certbot --nginx -d debrid.example.com
```

Certbot will:
1. Verify domain ownership via HTTP challenge
2. Issue a free Let's Encrypt certificate
3. Set up a cron job / systemd timer to auto-renew the certificate before it expires

### Step 4 — Install the config file

Copy the sample config, replacing `<domain>` with your actual domain name (e.g. `debrid.example.com`):

```bash
DOMAIN=debrid.example.com

sed "s/<domain>/$DOMAIN/g" nginx/debrid.conf \
  | sudo tee /etc/nginx/sites-available/debrid.conf > /dev/null

sudo ln -s /etc/nginx/sites-available/debrid.conf \
           /etc/nginx/sites-enabled/debrid.conf

sudo nginx -t
sudo systemctl reload nginx
```

### Step 5 — Verify

Open `https://debrid.example.com` in your browser. You should see a valid padlock icon (TLS certificate issued to your domain). HTTP requests will be redirected to HTTPS automatically.

### Keeping certificates up to date

Certbot installs an auto-renewal timer. You can test it at any time:

```bash
sudo certbot renew --dry-run
```

### What is protected by HTTPS?

Once HTTPS is enabled, the following are encrypted end-to-end between the browser and Nginx:

| What | Why it matters |
|---|---|
| Login credentials | Password never sent in the clear |
| Session cookie | Cannot be hijacked by a passive observer |
| File downloads | Content cannot be read or tampered with in transit |
| Video streams | Seekable range requests are encrypted |
| API responses | Task lists, user data, and stats are private |

## API Reference

All API endpoints are prefixed with `/api` and require the `X-Worker-Key` header set to the value of `WORKER_API_KEY` (or a valid admin session cookie when called through the frontend proxy).

### Tasks

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tasks` | Create a new download task (magnet or link) |
| `GET` | `/api/tasks/{task_id}` | Get task details and file list |
| `GET` | `/api/tasks/{task_id}/events` | SSE stream of real-time task events |
| `POST` | `/api/tasks/{task_id}/select` | Select specific files to download (select mode) |
| `POST` | `/api/tasks/{task_id}/cancel` | Cancel a running task |
| `DELETE` | `/api/tasks/{task_id}` | Delete a task and its files |
| `POST` | `/api/tasks/upload` | Upload a file directly as a new task (admin only) |

### Statistics

**`GET /api/stats`** — Returns real-time system statistics.

```json
{
  "timestamp": 1234567890.0,
  "tasks": { "total": 100, "queued": 5, "downloading": 3, "completed": 85, "failed": 2 },
  "files": { "total": 500, "downloading": 8, "completed": 480 },
  "downloads": { "active_count": 8, "total_bytes": 10737418240, "downloaded_bytes": 5368709120, "progress_pct": 50 },
  "storage": { "free_bytes": 107374182400, "reserved_bytes": 5368709120 }
}
```

No sensitive information (API keys, tokens, file paths, credentials) is ever included in API responses.

### Users & Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/verify` | Verify username/password credentials |
| `GET` | `/api/users/check` | Check whether any users exist (first-run detection) |
| `GET` | `/api/users` | List all users |
| `POST` | `/api/users` | Create a new user |
| `POST` | `/api/users/{user_id}/reset-password` | Reset a user's password |
| `POST` | `/api/users/{user_id}/role` | Set a user's role |
| `DELETE` | `/api/users/{user_id}` | Delete a user |

### Health

**`GET /health`** — Returns `{"ok": true}` when the API and storage mount are healthy.

---

## Development & Testing

### Running tests

```bash
pip install -r requirements.txt -r frontend/requirements.txt
python -m pytest tests/ -v
```

The test suite covers:
- Path-traversal and symlink-escape protection (`validate_file_path`, `safe_task_base`)
- CSRF token validation on all state-changing POST routes
- Security response headers
- Login rate limiting
- Task naming logic

### Project layout

```
.
├── app/                  # FastAPI backend
│   ├── main.py           # App factory, middleware, exception handlers
│   ├── api.py            # API router (tasks, users, stats, SSE)
│   ├── models.py         # SQLAlchemy ORM models
│   ├── schemas.py        # Pydantic request/response schemas
│   ├── config.py         # Pydantic settings (loaded from .env)
│   ├── auth.py           # API key & SSE token verification
│   ├── validation.py     # Input validation, path-traversal checks
│   ├── constants.py      # Enums and limits
│   ├── task_naming.py    # Auto-generated task labels
│   ├── rate_limiter.py   # Simple in-memory rate limiter
│   ├── ws_manager.py     # WebSocket / Redis pub-sub manager
│   └── providers/
│       └── alldebrid.py  # AllDebrid API client
├── worker/               # Background download worker
│   ├── worker.py         # Main polling loop
│   ├── downloader.py     # Aria2 download dispatch & progress tracking
│   ├── scheduler.py      # Queue management and task scheduling
│   └── aria2rpc.py       # Aria2 JSON-RPC client
├── frontend/             # Flask web UI
│   ├── app.py            # Routes, auth, file serving, streaming
│   └── templates/        # Jinja2 HTML templates
├── alembic/              # Database migrations
├── nginx/debrid.conf     # Sample Nginx reverse-proxy config
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.frontend
├── Dockerfile.worker
├── requirements.txt      # Shared Python dependencies
└── .env.example          # Configuration template
```

---

## Upgrading

Database migrations are applied automatically by the `migrations` service on every `docker compose up`. To apply them manually:

```bash
docker compose exec api alembic upgrade head
```

After pulling a new version:

```bash
git pull
docker compose build
docker compose up -d
```

All existing data (tasks, users, downloaded files) is preserved in the `db_data` Docker volume and the `STORAGE_PATH` bind-mount.

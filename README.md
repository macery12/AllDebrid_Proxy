# AllDebrid Proxy

A production-ready proxy service for AllDebrid that enables efficient torrent downloading, file management, and sharing through a clean web interface.

## 🎯 Features

- **🚀 Automated Downloads**: Submit magnet links and automatically download all files
- **📋 Selective Downloads**: Choose specific files from a torrent before downloading
- **📊 Real-time Progress**: Live progress tracking with Server-Sent Events (SSE)
- **🔐 Secure Authentication**: Password-protected web interface
- **📦 Docker Deployment**: Easy deployment with Docker Compose
- **💾 Smart Storage**: Configurable storage limits with disk space monitoring
- **🔄 Task Management**: Queue, pause, resume, and cancel downloads
- **🎨 Web Interface**: User-friendly Flask-based frontend
- **⚡ High Performance**: Multi-threaded downloads with aria2

## 🏗️ Architecture

The system consists of five main services:

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Frontend  │─────▶│     API      │─────▶│   Worker    │
│   (Flask)   │      │  (FastAPI)   │      │  (Python)   │
└─────────────┘      └──────────────┘      └─────────────┘
                            │                      │
                            ▼                      ▼
                     ┌──────────┐          ┌──────────┐
                     │PostgreSQL│          │  aria2   │
                     └──────────┘          └──────────┘
                            │
                            ▼
                     ┌──────────┐
                     │  Redis   │
                     └──────────┘
```

- **Frontend**: User-facing web interface for task management
- **API**: RESTful API with real-time SSE endpoints
- **Worker**: Background process for AllDebrid integration and download orchestration
- **PostgreSQL**: Task and metadata storage
- **Redis**: Pub/sub for real-time updates and task queue
- **aria2**: High-performance download engine

## 📋 Prerequisites

- Docker and Docker Compose
- AllDebrid API key ([get one here](https://alldebrid.com/apikeys/))
- At least 10GB free disk space (configurable)

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/macery12/AllDebrid_Proxy.git
cd AllDebrid_Proxy
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env  # Edit with your preferred editor
```

**Important:** Change these values:
- `WORKER_API_KEY`: Generate a strong random key
- `FLASK_SECRET`: Generate a strong random key
- `ALLDEBRID_API_KEY`: Your AllDebrid API key
- `ARIA2_RPC_SECRET`: Generate a strong random key
- `LOGIN_USERS`: Set your username and password (format: `username:password;`)

### 3. Start Services

```bash
docker-compose up -d
```

### 4. Access the Interface

Open your browser and navigate to:
- **Frontend**: http://localhost:9732
- **API Docs**: http://localhost:9731/docs

Default credentials (if not changed): `TestUser` / `password`

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `WORKER_API_KEY` | API key for worker authentication | `change-me` | ✅ |
| `FLASK_SECRET` | Flask session secret key | `change-me` | ✅ |
| `ALLDEBRID_API_KEY` | Your AllDebrid API key | - | ✅ |
| `ALLDEBRID_AGENT` | User agent for AllDebrid API | `Generic-PC` | ❌ |
| `STORAGE_ROOT` | Root directory for downloads | `/srv/storage` | ❌ |
| `LOW_SPACE_FLOOR_GB` | Minimum free space in GB | `10` | ❌ |
| `ARIA2_SPLITS` | Number of connections per download | `4` | ❌ |
| `PER_TASK_MAX_ACTIVE` | Max concurrent downloads per task | `2` | ❌ |
| `POSTGRES_USER` | PostgreSQL username | `alldebrid` | ❌ |
| `POSTGRES_PASSWORD` | PostgreSQL password | `alldebrid` | ✅ |
| `REDIS_URL` | Redis connection URL | `redis://redis:6379/0` | ❌ |
| `FRONTEND_PORT` | Frontend web interface port | `9732` | ❌ |

### Storage Configuration

By default, files are stored in `/srv/storage` on the host machine. To change this:

1. Update `STORAGE_ROOT` in `.env`
2. Update volume mounts in `docker-compose.yml`:

```yaml
volumes:
  - /your/custom/path:/srv/storage
```

### User Management

Users are configured via the `LOGIN_USERS` environment variable:

```bash
# Single user
LOGIN_USERS=admin:strongpassword123;

# Multiple users
LOGIN_USERS=admin:pass1;user2:pass2;user3:pass3;
```

## 📚 Usage

### Creating a Download Task

1. Log in to the web interface
2. Paste a magnet link
3. Choose download mode:
   - **Auto**: Downloads all files automatically
   - **Select**: Lets you choose which files to download
4. Click "Create Task"

### Monitoring Progress

- Tasks page shows real-time progress
- File-level progress tracking
- Storage usage indicators
- Download speed monitoring

### Accessing Downloaded Files

Files are accessible through:
- Web interface: `/d/{task_id}/`
- Direct download: `/d/{task_id}/raw/{filename}`
- Bulk download: `/d/{task_id}.tar.gz`

### API Usage

The API is available at `http://localhost:9731/api`

**Create a task:**
```bash
curl -X POST http://localhost:9731/api/tasks \
  -H "X-Worker-Key: your-worker-key" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "auto",
    "source": "magnet:?xt=urn:btih:...",
    "label": "My Download"
  }'
```

**Get task status:**
```bash
curl http://localhost:9731/api/tasks/{task_id} \
  -H "X-Worker-Key: your-worker-key"
```

**Stream progress updates (SSE):**
```bash
curl -N http://localhost:9731/api/tasks/{task_id}/events
```

See full API documentation at http://localhost:9731/docs

## 🔧 Maintenance

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f worker
docker-compose logs -f frontend
```

### Restarting Services

```bash
# All services
docker-compose restart

# Specific service
docker-compose restart worker
```

### Backing Up Data

```bash
# Backup database
docker-compose exec db pg_dump -U alldebrid alldebrid > backup.sql

# Backup downloads
tar -czf downloads_backup.tar.gz /srv/storage
```

### Updating

```bash
git pull
docker-compose pull
docker-compose up -d --build
```

## 🛠️ Development

### Running Locally

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up database:
```bash
alembic upgrade head
```

3. Run services:
```bash
# API
uvicorn app.main:app --reload

# Worker
python -m worker.worker

# Frontend
python frontend/app.py
```

### Code Quality

Run linters and type checkers:
```bash
# Type checking
mypy app worker

# Code formatting
black app worker frontend

# Linting
ruff check app worker
```

## 🐛 Troubleshooting

### Common Issues

**"WORKER_API_KEY must be changed from default"**
- Solution: Set a unique value for `WORKER_API_KEY` in `.env`

**"AllDebrid API error"**
- Check your `ALLDEBRID_API_KEY` is valid
- Verify your AllDebrid subscription is active
- Check AllDebrid API status

**"Storage not writable"**
- Verify `/srv/storage` permissions
- Check available disk space
- Ensure Docker has access to the mount point

**"Connection refused" errors**
- Wait for all services to start (use `docker-compose ps`)
- Check service logs with `docker-compose logs`
- Verify no port conflicts

### Health Checks

Check service health:
```bash
# API health
curl http://localhost:9731/health

# Frontend health
curl http://localhost:9732/debug/config
```

## 📖 Documentation

- [Code Review](CODE_REVIEW.md) - Detailed code analysis and recommendations
- [API Documentation](http://localhost:9731/docs) - Interactive API docs (when running)
- [Architecture Guide](docs/architecture.md) - System design details (coming soon)

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This software is provided for educational and personal use only. Users are responsible for complying with AllDebrid's Terms of Service and applicable laws regarding copyright and file sharing.

## 🙏 Acknowledgments

- [AllDebrid](https://alldebrid.com) - Premium link generator service
- [aria2](https://aria2.github.io/) - Download utility
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [Flask](https://flask.palletsprojects.com/) - Web framework

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/macery12/AllDebrid_Proxy/issues)
- **Discussions**: [GitHub Discussions](https://github.com/macery12/AllDebrid_Proxy/discussions)

---

Made with ❤️ by the community

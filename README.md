# AllDebrid_Proxy

A proxy service for AllDebrid that uses PyLoad download manager with AllDebrid plugin integration. This allows you to proxy AllDebrid files and share them with friends for faster downloads.

## Features

- Uses PyLoad with built-in AllDebrid plugin for reliable downloads
- Supports magnet links and direct file URLs
- Web-based interface for managing downloads
- Automatic file unlocking through AllDebrid
- Multi-file selection support
- Progress tracking and status monitoring

## Prerequisites

- Docker and Docker Compose
- AllDebrid account (for PyLoad AllDebrid plugin configuration)

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/macery12/AllDebrid_Proxy.git
cd AllDebrid_Proxy
```

### 2. Configure Environment

Copy the example environment file and update it with your settings:

```bash
cp .env.example .env
```

Edit `.env` and configure the following:

- `WORKER_API_KEY`: Set a secure API key for worker authentication
- `PYLOAD_URL`: PyLoad service URL (default: http://pyload:8000)
- `PYLOAD_USERNAME`: PyLoad username (default: pyload - change via web UI after first login)
- `PYLOAD_PASSWORD`: PyLoad password (default: pyload - change via web UI after first login)
- `LOGIN_USERS`: Set username:password pairs for frontend access
- `FLASK_SECRET`: Set a secure secret key

**Note**: PyLoad configuration is saved in `./config/pyload` directory. The default PyLoad credentials are `pyload/pyload` and should be changed via the web interface after first login.

### 3. Configure PyLoad AllDebrid Plugin

After starting the services, you'll need to configure PyLoad with your AllDebrid account:

1. Access PyLoad web interface at `http://localhost:8000`
2. Login with default credentials: **username: `pyload`, password: `pyload`**
3. **Change your password** in Settings → General → Password
4. Go to Settings → Accounts
5. Add your AllDebrid account:
   - Click "Add Account"
   - Select "AllDebrid" from the provider list
   - Enter your AllDebrid API key or credentials
   - Save the configuration

To get your AllDebrid API key:
- Visit https://alldebrid.com/account/
- Go to API section
- Copy your API key

### 4. Start Services

```bash
docker-compose up -d
```

This will start:
- PostgreSQL database
- Redis cache
- PyLoad download manager
- API server (port 9731)
- Worker process
- Frontend web interface (port 9732)

### 5. Access the Application

- Frontend: http://localhost:9732
- API: http://localhost:9731
- PyLoad: http://localhost:8000

## How It Works

1. **Submit Downloads**: Add magnet links or direct URLs through the web interface
2. **PyLoad Processing**: Links are sent to PyLoad which uses the AllDebrid plugin to unlock and process them
3. **File Selection**: Choose which files to download (in select mode) or download all (in auto mode)
4. **Download**: Files are downloaded directly through PyLoad's AllDebrid integration
5. **Access Files**: Downloaded files are stored in `/srv/storage` and accessible through the frontend

## Architecture

- **API**: FastAPI-based REST API for task management
- **Worker**: Background process that manages PyLoad interactions
- **PyLoad**: Download manager with AllDebrid plugin integration
- **Frontend**: Flask-based web interface for user interaction
- **Database**: PostgreSQL for persistent task storage
- **Cache**: Redis for real-time updates and pub/sub

## Development

To run in development mode with logging:

```bash
docker-compose up
```

Enable debug logging:
```bash
export DEBUG_DOWNLOADS=1
docker-compose up worker
```

## Troubleshooting

### PyLoad Connection Issues
- Ensure PyLoad service is running: `docker-compose ps`
- Check PyLoad logs: `docker-compose logs pyload`
- Verify PyLoad credentials in `.env`
- **Authentication**: PyLoad 0.5+ uses HTTP Basic Auth. Ensure username and password are correct.

### AllDebrid Not Working
- Verify AllDebrid account is configured in PyLoad
- Check PyLoad account settings for AllDebrid status
- Ensure AllDebrid API key is valid

### Download Failures
- Check worker logs: `docker-compose logs worker`
- Verify storage permissions
- Ensure sufficient disk space

### API Errors
- **404 Not Found**: Ensure you're using PyLoad 0.5+ which uses HTTP Basic Auth instead of `/api/login`
- **401 Unauthorized**: Check PyLoad credentials in `.env` (username/password must match PyLoad account)
- **Connection refused**: Ensure PyLoad container is running

## License

See LICENSE file for details.

# AllDebrid_Proxy
a poorly chatgpt'ed together alldebrid proxy to proxy alldebrid files and be able to send them to friends for faster download

## Features

### 📊 Real-Time Stats Dashboard
- **Live System Monitoring**: Real-time statistics updated every 3 seconds
- **Active Downloads**: Monitor currently downloading files and tasks
- **Queue Status**: See queued tasks waiting to start
- **Storage Metrics**: Track available disk space and reserved storage
- **Download Progress**: Visual progress bars showing overall download status
- **Worker Health**: System status indicators with automatic health checks
- **Performance Metrics**: Comprehensive stats about tasks, files, and system resources
- **Security First**: No sensitive information (API keys, tokens) exposed to frontend

### 📥 Multi-Source Download Support
- **Torrent File Upload**: Upload .torrent files directly - they're converted to magnet links and immediately discarded (not stored)
- **Magnet Links**: Full support for BitTorrent magnet links via AllDebrid
- **Direct Links**: Support for HTTP/HTTPS direct download links via AllDebrid
- **Multi-Source Submission**: Submit multiple sources at once (torrent files, magnets, or links)
- **Smart Task Reuse**: Automatically reuses existing downloads to save bandwidth
- **Error Handling**: Proper error messages for unsupported or failed links

### 🔐 User System
- **Database-backed authentication** - Users are stored in PostgreSQL instead of environment variables
- **Role-based access control**:
  - **Admin users**: Full access to all pages including admin dashboard, user management, and download pages
  - **Regular users**: Access to create tasks and download files
- **First-time setup**: Automatic admin account creation on first startup
- **User statistics**: Track magnets processed, downloads, and total bytes downloaded per user

### 🚀 Getting Started

#### First-Time Setup

On first startup, when no users exist in the database:
1. Start the application with `docker-compose up`
2. Navigate to the login page at `http://localhost:9732/login`
3. You will be prompted to create the first admin account
4. Enter a username and password to create your admin account
5. After creation, you can log in and manage additional users from the **Admin > Users** page

#### Existing Installation Migration

If you were previously using `LOGIN_USERS` environment variable:

1. **Backup your data** (optional but recommended)
   ```bash
   docker-compose exec db pg_dump -U alldebrid alldebrid > backup.sql
   ```

2. **Remove LOGIN_USERS from .env**
   ```bash
   # Edit .env and remove this line:
   # LOGIN_USERS=TestUser:password;
   ```

3. **Run database migration**
   ```bash
   docker-compose exec adproxy_api alembic upgrade head
   ```

4. **Restart services**
   ```bash
   docker-compose restart
   ```

5. **Create your admin account** via the first-time setup flow

#### Updating to Link Support Version

If you're upgrading from a version before link support was added:

1. **Run the new database migration**
   ```bash
   docker-compose exec adproxy_api alembic upgrade head
   ```
   
   This adds the `source_type` field to the task table to support both magnets and links.

2. **Restart services**
   ```bash
   docker-compose restart
   ```

All existing magnet-based tasks will continue to work normally with the new version.

### 👥 User Management (Admin Only)

Admins can manage users at `/admin/users`:

- **Create new users** (admin or regular)
- **View user statistics** (magnets processed, downloads, bytes downloaded)
- **Reset user passwords**
- **Promote/demote users** to/from admin role
- **Delete users** (except yourself)

### 📊 User Statistics

Each user has statistics tracked automatically:
- **Total magnets processed**: Incremented when a new task is created
- **Total downloads**: Incremented when a file download completes
- **Total bytes downloaded**: Sum of all downloaded file sizes

Statistics are viewable in the Admin > Users page.

### 📂 Torrent File Upload

Upload `.torrent` files directly through the web interface for seamless conversion to magnet links:

**How It Works:**
1. **Upload**: Select one or more `.torrent` files (up to 10MB each)
2. **Extract**: System automatically extracts info hash and tracker URLs
3. **Convert**: Generates a proper magnet link with all trackers
4. **Discard**: Torrent file is immediately deleted from memory (not stored anywhere)
5. **Process**: The magnet link is used to create a download task via AllDebrid

**Security Features:**
- ✅ Torrent files are **never stored** on disk or in database
- ✅ Files are processed entirely in memory
- ✅ Strict file size limit (10MB max per file)
- ✅ File type validation (must be `.torrent` extension)
- ✅ Bencode format validation
- ✅ Automatic cleanup after conversion

**Usage:**
- Upload multiple torrent files at once
- Combine with manual magnet/URL input in the same submission
- Same smart deduplication and task reuse as other sources

**Technical Details:**
- Uses `bencodepy` library for torrent parsing
- Extracts SHA-1 info hash and all tracker tiers
- Preserves display name in magnet link
- Compatible with single and multi-tracker torrents

### 🔒 Security & Access Control

**All users must be logged in** to access any part of the website.

**Admin Users can:**
- ✅ Access all admin pages (`/admin`, `/admin/users`, `/admin/tasks`)
- ✅ Create and manage tasks (main page `/` with magnet submission)
- ✅ View all tasks in the system
- ✅ Manage user accounts
- ✅ Access download pages (`/d/`)

**Regular Users can:**
- ✅ Access download pages **only** (`/d/<task_id>/`)
- ✅ Download and stream files
- ❌ Cannot create new tasks
- ❌ Cannot access admin dashboard
- ❌ Cannot access the main page

**Authentication Required:**
- Download routes (`/d/<task_id>/`) require login (accessible to both admins and users)
- All other routes require admin privileges

Regular users trying to access admin-only pages will see an "Access Denied" page explaining their permissions.

### 🛠️ Technical Details

For detailed information about the user system implementation, database schema, and API changes, see [USER_SYSTEM.md](USER_SYSTEM.md).

### 📝 Configuration

Key environment variables (see `.env.example`):

```bash
# Core
WORKER_API_KEY=change-me          # API key for backend communication
FLASK_SECRET=change-me             # Flask session secret

# Database (users stored here)
DATABASE_URL=postgresql+psycopg2://alldebrid:alldebrid@db:5432/alldebrid

# AllDebrid
ALLDEBRID_API_KEY=change-me
ALLDEBRID_AGENT=Generic-PC

# Storage
STORAGE_ROOT=/srv/storage
```

**Note**: The `LOGIN_USERS` environment variable is no longer used. All user management is now done through the web interface.

### 🐳 Docker Deployment

The application consists of multiple services:
- `adproxy_frontend`: Web UI (Flask)
- `adproxy_api`: Backend API (FastAPI)
- `adproxy_worker`: Download worker
- `db`: PostgreSQL database (user data + tasks)
- `redis`: Message queue and caching

All services are configured via `docker-compose.yml`.

### 📡 API Endpoints

#### Statistics Endpoint

**GET `/api/stats`** - Get comprehensive system statistics

Returns real-time statistics about the system including:
- **Tasks**: Total, queued, downloading, completed, failed, canceled
- **Files**: Total, downloading, completed, failed
- **Downloads**: Active downloads, progress, bytes downloaded/total
- **Storage**: Free space, reserved space, low space threshold
- **Users**: Aggregate user statistics
- **Queue**: Redis queue length
- **Health**: Worker health status

**Authentication**: Requires valid worker API key via `X-Worker-Key` header (backend) or admin session (frontend proxy at `/api/stats`)

**Example Response**:
```json
{
  "timestamp": 1234567890.0,
  "tasks": {
    "total": 100,
    "queued": 5,
    "downloading": 3,
    "active": 3,
    "completed": 85,
    "failed": 2
  },
  "files": {
    "total": 500,
    "downloading": 8,
    "completed": 480
  },
  "downloads": {
    "active_count": 8,
    "total_bytes": 10737418240,
    "downloaded_bytes": 5368709120,
    "progress_pct": 50
  },
  "storage": {
    "free_bytes": 107374182400,
    "reserved_bytes": 5368709120
  }
}
```

**Security Note**: This endpoint does not expose any sensitive information such as API keys, tokens, file paths, or user credentials.

### 📚 Additional Documentation

- [USER_SYSTEM.md](USER_SYSTEM.md) - Detailed user system documentation and migration guide
- [.env.example](.env.example) - Environment configuration template



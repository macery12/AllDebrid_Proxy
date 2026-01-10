# AllDebrid_Proxy
a poorly chatgpt'ed together alldebrid proxy to proxy alldebrid files and be able to send them to friends for faster download

## Features

### 📥 Multi-Source Download Support (NEW!)
- **Magnet Links**: Full support for BitTorrent magnet links via AllDebrid
- **Direct Links**: Support for HTTP/HTTPS direct download links via AllDebrid
- **Multi-Source Submission**: Submit multiple magnets or links at once (one per line)
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

### 📚 Additional Documentation

- [USER_SYSTEM.md](USER_SYSTEM.md) - Detailed user system documentation and migration guide
- [.env.example](.env.example) - Environment configuration template



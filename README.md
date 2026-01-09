# AllDebrid_Proxy
a poorly chatgpt'ed together alldebrid proxy to proxy alldebrid files and be able to send them to friends for faster download

## Features

### 🔐 User System (NEW!)
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

**Admin Users can:**
- Access all admin pages (`/admin`, `/admin/users`, `/admin/tasks`)
- Create and manage any task
- View all tasks in the system
- Manage user accounts
- Access download pages

**Regular Users can:**
- Create and manage their own tasks
- Access the home page to create new downloads
- Access download routes (see below)

**Public Access (no authentication required):**
- Download routes (`/d/<task_id>/`) remain public for easy file sharing
- Anyone with the link can download files

This design allows you to share download links with friends without requiring them to have accounts.

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



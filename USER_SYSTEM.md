# User System Migration Guide

This guide explains the new database-backed user system and how to migrate from the old `LOGIN_USERS` environment variable.

## What's New

### Database-Backed Authentication
- Users are now stored in PostgreSQL instead of environment variables
- More secure password hashing with Werkzeug
- User data persists across container restarts

### Role-Based Access Control
Two user roles are supported:

**Admin Users:**
- Create and manage tasks
- Access admin dashboard
- Manage users (create, delete, promote/demote)
- View all tasks and statistics
- Access user management interface

**Regular Users:**
- Create and manage their own tasks  
- Access download routes (no authentication required)
- View their own tasks

### User Statistics Tracking
Each user has statistics tracked automatically:
- Total magnets processed
- Total downloads completed
- Total bytes downloaded

### First-Time Setup
When no users exist in the database, the login page automatically switches to first-time setup mode, prompting you to create the initial admin account.

## Migration Steps

### 1. Update Your Environment File

Remove the old `LOGIN_USERS` variable from your `.env` file:

```bash
# OLD (remove this)
LOGIN_USERS=TestUser:password;admin:admin123;

# The new system doesn't use this variable
```

### 2. Run Database Migration

The migration will create three new tables: `user`, `user_stats`, and add `user_id` column to `task`.

```bash
# If using Docker Compose
docker-compose exec adproxy_api alembic upgrade head

# Or locally
alembic upgrade head
```

### 3. Create Your First Admin Account

1. Navigate to the login page
2. You'll see a "First-Time Setup" screen
3. Enter username and password for your admin account
4. Click "Create Admin Account"
5. Log in with your new credentials

### 4. Add Additional Users (Optional)

As an admin:
1. Navigate to Admin > Users
2. Fill in username and password
3. Check "Admin" if you want to create another admin
4. Click "Create User"

## User Management

### Admin Interface

Access the user management interface at `/admin/users` (admin only).

**Available Actions:**
- **Create User**: Add new users with optional admin privileges
- **Reset Password**: Change a user's password
- **Promote/Demote**: Toggle admin status for users
- **Delete User**: Remove a user (cannot delete yourself)
- **View Statistics**: See download statistics for each user

### User Statistics

Statistics are automatically tracked when:
- A task is created (increments `total_magnets_processed`)
- A file download completes (increments `total_downloads` and `total_bytes_downloaded`)

## API Changes

### Task Creation

The API now accepts an optional `user_id` field to track which user created a task:

```json
POST /api/tasks
{
  "mode": "auto",
  "source": "magnet:?xt=urn:btih:...",
  "label": "My Download",
  "user_id": 1
}
```

The frontend automatically includes the current user's ID when creating tasks.

### Backward Compatibility

Tasks created without a `user_id` (e.g., via direct API calls) are still supported. They simply won't be attributed to any user for statistics purposes.

## Security Considerations

### Password Storage
- Passwords are hashed using Werkzeug's `generate_password_hash` with PBKDF2
- Never stored in plain text
- Original passwords cannot be recovered

### Session Management
- Flask-Login handles session management
- Sessions are stored in encrypted cookies
- Sessions expire when browser is closed (default)

### Download Routes
- Download routes (`/d/*`) remain unauthenticated for easy sharing
- Task creation and management require authentication
- Admin features require admin role

## Troubleshooting

### "No users found" on Every Login
This means the database wasn't migrated properly. Run:
```bash
alembic upgrade head
```

### Cannot Access Admin Pages
Make sure your user has admin privileges. Only the first user created during setup is an admin. Other users must be promoted by an existing admin.

### "User already exists" Error
Usernames must be unique. Choose a different username.

### Lost Admin Password
If you lose admin access:
1. Connect to the database directly
2. Run: `UPDATE "user" SET is_admin = true WHERE username = 'yourusername';`
3. Or create a new admin user via SQL if needed

## Database Schema

### User Table
```sql
CREATE TABLE "user" (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE
);
```

### User Stats Table
```sql
CREATE TABLE user_stats (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    total_downloads INTEGER NOT NULL DEFAULT 0,
    total_magnets_processed INTEGER NOT NULL DEFAULT 0,
    total_bytes_downloaded BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Task Table Updates
```sql
ALTER TABLE task ADD COLUMN user_id INTEGER REFERENCES "user"(id) ON DELETE CASCADE;
CREATE INDEX ix_task_user_id ON task(user_id);
```

## Additional Notes

- The migration is backward compatible - existing tasks won't break
- Download links can still be shared publicly
- User stats are updated in real-time as downloads complete
- Admins can see all tasks; regular users see their own tasks (implementation can be extended if needed)

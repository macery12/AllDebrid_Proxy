# AllDebrid_Proxy
a poorly chatgpt'ed together alldebrid proxy to proxy alldebrid files and be able to send them to friends for faster download

## Features

### User System
- **Database-backed authentication** - Users are stored in PostgreSQL instead of environment variables
- **Role-based access control**:
  - **Admin users**: Full access to all pages including admin dashboard, user management, and download pages
  - **Regular users**: Access to create tasks and download files
- **First-time setup**: Automatic admin account creation on first startup
- **User statistics**: Track magnets processed, downloads, and total bytes downloaded per user

### Getting Started

On first startup, when no users exist in the database:
1. Navigate to the login page
2. You will be prompted to create the first admin account
3. Enter a username and password to create your admin account
4. After creation, you can log in and manage additional users from the Admin > Users page

### User Management (Admin Only)

Admins can:
- Create new users (admin or regular)
- View user statistics (magnets processed, downloads, bytes downloaded)
- Reset user passwords
- Promote/demote users to/from admin role
- Delete users

### Migration from Environment Variables

If you were previously using `LOGIN_USERS` environment variable:
1. Remove `LOGIN_USERS` from your `.env` file
2. Run the database migration: `alembic upgrade head`
3. On first login, create your admin account
4. Add other users through the Admin > Users interface


# Configuration Directory

This directory stores persistent configuration for services.

## PyLoad Configuration

The `pyload/` subdirectory contains PyLoad's configuration files, including:
- User credentials
- Plugin settings
- AllDebrid account configuration
- Download history

**Note**: This directory is excluded from version control (`.gitignore`) to protect your credentials and settings.

### Initial Setup

On first startup, PyLoad will create its configuration files in `./config/pyload/`.

Default credentials:
- Username: `pyload`
- Password: `pyload`

**Important**: Change these credentials via the PyLoad web interface at `http://localhost:8000` after first login.

### Backup

To backup your PyLoad configuration:
```bash
tar -czf pyload-config-backup.tar.gz config/pyload/
```

To restore:
```bash
tar -xzf pyload-config-backup.tar.gz
```

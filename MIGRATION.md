# Migration Guide: AllDebrid Direct API to PyLoad

This document explains how to migrate from the old AllDebrid direct API implementation to the new PyLoad-based implementation.

## What Changed?

### Before (Old Implementation)
- Direct AllDebrid API calls from the worker
- Aria2 daemon for downloading files
- Custom AllDebrid client (`app/providers/alldebrid.py`)
- Configuration: `ALLDEBRID_API_KEY`, `ALLDEBRID_AGENT`, `ARIA2_RPC_URL`, `ARIA2_RPC_SECRET`

### After (New Implementation)
- PyLoad download manager with AllDebrid plugin
- PyLoad handles AllDebrid integration and downloads
- Simplified PyLoad provider (`app/providers/pyload_provider.py`)
- Configuration: `PYLOAD_URL`, `PYLOAD_USERNAME`, `PYLOAD_PASSWORD`

## Why This Change?

1. **Better Reliability**: PyLoad's AllDebrid plugin is actively maintained and fully supported
2. **Simpler Architecture**: One service (PyLoad) instead of two (AllDebrid + Aria2)
3. **Built-in Support**: PyLoad natively supports AllDebrid, no custom client needed
4. **Easier Maintenance**: PyLoad handles updates to AllDebrid API automatically

## Migration Steps

### 1. Update Your `.env` File

Remove these old variables:
```env
ALLDEBRID_API_KEY=...
ALLDEBRID_AGENT=...
ARIA2_RPC_URL=...
ARIA2_RPC_SECRET=...
ARIA2_SPLITS=...
```

Add these new variables:
```env
PYLOAD_URL=http://pyload:8000
PYLOAD_USERNAME=admin
PYLOAD_PASSWORD=your_secure_password
```

### 2. Configure PyLoad with AllDebrid

After starting the services with `docker-compose up -d`:

1. Access PyLoad at `http://localhost:8000`
2. Login with your PyLoad credentials (from `.env`)
3. Go to **Settings → Accounts**
4. Click **Add Account**
5. Select **AllDebrid** from the provider list
6. Enter your AllDebrid API key (get it from https://alldebrid.com/account/)
7. Save the configuration

### 3. Restart Services

```bash
docker-compose down
docker-compose up -d
```

## What Stays the Same?

- **API Endpoints**: All existing API endpoints remain unchanged
- **Frontend Interface**: No changes to the web UI
- **Database Schema**: No migration needed
- **Workflow**: Same process for adding magnets/links and downloading files
- **Storage**: Files still stored in `/srv/storage`

## Compatibility Notes

- **Magnet Links**: Still fully supported via PyLoad
- **Direct Links**: Still fully supported via PyLoad
- **File Selection**: Select mode and auto mode both work the same
- **Progress Tracking**: Same real-time progress updates

## Troubleshooting

### PyLoad won't start
- Check logs: `docker-compose logs pyload`
- Ensure port 8000 is not in use
- Verify PyLoad credentials in `.env`

### AllDebrid not working in PyLoad
- Ensure AllDebrid account is active
- Verify API key is correct in PyLoad settings
- Check PyLoad account page shows AllDebrid as "enabled"

### Downloads failing
- Check worker logs: `docker-compose logs worker`
- Verify PyLoad can reach AllDebrid servers
- Ensure AllDebrid account has premium status

## Rollback Plan

If you need to rollback to the old implementation:

1. Checkout the previous commit:
   ```bash
   git checkout 362ce35
   ```

2. Update your `.env` with old variables (ALLDEBRID_API_KEY, etc.)

3. Restart services:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

## Support

For issues related to:
- **PyLoad**: Check [PyLoad documentation](https://github.com/pyload/pyload)
- **AllDebrid Plugin**: Check PyLoad's AllDebrid plugin settings
- **This Proxy**: Open an issue on GitHub

## Summary

This migration simplifies the architecture while maintaining all existing functionality. The main change is that PyLoad now handles both AllDebrid integration and downloading, instead of using separate AllDebrid client and Aria2 services.

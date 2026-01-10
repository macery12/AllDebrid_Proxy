# Troubleshooting Guide

## 401 "Invalid key" Error

If you're getting a 401 Unauthorized error with `{detail: "Invalid key"}`, the WORKER_API_KEY is not properly configured.

### Quick Fix

1. **Check your .env file**:
   ```bash
   cat .env | grep WORKER_API_KEY
   ```

2. **Ensure it's NOT set to the default**:
   ```bash
   # BAD (will fail)
   WORKER_API_KEY=change-me
   
   # GOOD (use a secure random string)
   WORKER_API_KEY=my_secure_random_key_123456
   ```

3. **Restart services**:
   ```bash
   docker-compose restart
   ```

### Detailed Debugging

#### Step 1: Check Frontend Startup Logs

```bash
docker-compose logs frontend | head -50
```

Look for:
- ✅ `WORKER_API_KEY configured (length: X chars)` - Good!
- ❌ `WARNING: WORKER_API_KEY environment variable is not set!` - Need to set it
- ❌ `WARNING: WORKER_API_KEY is still set to the default 'change-me'!` - Need to change it

#### Step 2: Enable Debug Logging

Add to your `.env` file:
```bash
DEBUG=1
```

Then restart:
```bash
docker-compose restart frontend
```

Check logs again:
```bash
docker-compose logs -f frontend
```

You should see detailed request logging including:
- `Headers: ['X-Worker-Key']` - Header is being sent
- `Worker key present: True` - Key exists
- `Worker key pattern: abcd...xyz` - Shows first/last 4 chars

#### Step 3: Check Backend Logs

```bash
docker-compose logs adproxy_api | grep -C 3 "401"
```

This will show exactly why the backend is rejecting the key.

#### Step 4: Verify Environment Variable

Check that docker-compose is passing the environment variable:

```bash
docker-compose exec frontend env | grep WORKER
```

Should show:
```
WORKER_API_KEY=your_key_here
WORKER_BASE_URL=http://adproxy_api:8080
```

### Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| .env file doesn't exist | Frontend starts but no key | Copy `.env.example` to `.env` |
| Key still "change-me" | Startup warning | Set to a secure value |
| Key mismatch | 401 error | Ensure same key in all services |
| .env not being read | Variables not set | Check `env_file:` in docker-compose.yml |
| Wrong backend URL | Connection refused | Check WORKER_BASE_URL matches service name |

### Testing Authentication

Once configured, test the `/debug/config` endpoint:

```bash
curl -u your_username:your_password http://localhost:9732/debug/config
```

Should return:
```json
{
  "worker_base_url": "http://adproxy_api:8080",
  "worker_key_present": true,
  "storage_root": "/srv/storage"
}
```

If `worker_key_present` is `false`, the WORKER_API_KEY is not being loaded.

### Still Having Issues?

1. Check all services are using the same `.env` file
2. Verify no typos in environment variable names
3. Ensure no extra spaces or quotes around the value
4. Try a simple value first (e.g., `test123`) to rule out special character issues
5. Check docker-compose.yml has `env_file: - .env` under frontend and api services

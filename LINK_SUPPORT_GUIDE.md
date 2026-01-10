# Link and Magnet Support Implementation

## Overview
This implementation adds comprehensive support for both magnet links and direct HTTP/HTTPS URLs to the AllDebrid Proxy, allowing users to download files from both BitTorrent and direct link sources.

## Features Added

### 1. Multi-Source Support
- **Magnet Links**: Full support for BitTorrent magnet links (existing functionality enhanced)
- **Direct Links**: New support for HTTP/HTTPS direct download links via AllDebrid
- **Multi-Source Submission**: Users can paste multiple links/magnets at once (one per line, max 10)

### 2. Smart Task Management
- **Task Reuse**: Automatically reuses existing downloads to save bandwidth
- **Unique Identifiers**: Uses infohash for magnets, SHA-1 hash for links
- **Type Tracking**: Database tracks source type (magnet or link) for proper handling

### 3. Enhanced Error Handling
- Validation for both magnet and link formats
- Proper error messages for unsupported links
- Failed source tracking in multi-source submissions
- AllDebrid API error handling

## Technical Implementation

### Database Changes
A new migration adds the `source_type` field to the Task table:
```sql
ALTER TABLE task ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'magnet';
```

### API Changes

#### Validation
New validation functions in `app/validation.py`:
- `validate_source(source: str)` - Validates a single magnet or URL
- `validate_sources(sources: str)` - Validates multiple sources (newline-separated)

#### AllDebrid Client
New methods in `app/providers/alldebrid.py`:
- `upload_links(links: List[str])` - Upload multiple links for unlocking
- `unlock_link(link: str)` - Unlock a single link for direct download
- `get_link_info(link: str)` - Get file information before unlocking

#### Worker Changes
The worker now handles two workflows:

**Magnet Workflow:**
1. Upload magnet to AllDebrid
2. Poll for file list resolution
3. Unlock individual files via magnet ID + file index
4. Download files via aria2

**Link Workflow:**
1. Get link info from AllDebrid (filename, size)
2. Create single file task entry
3. Unlock link directly for download URL
4. Download file via aria2

### Frontend Changes

#### UI Updates
The submission form now:
- Accepts multiple sources (one per line)
- Shows helpful placeholder text
- Validates max 10 sources
- Displays detailed success/error messages

#### Multi-Source Handling
When submitting multiple sources:
1. Frontend splits input by newlines
2. Creates separate task for each source
3. Adds index suffix to labels (e.g., "Movie (1/3)")
4. Shows summary of created/reused/failed tasks
5. Redirects to task view (single) or admin page (multiple)

## Usage Examples

### Single Magnet
```
magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12&dn=example
```

### Single Link
```
https://example.com/files/archive.zip
```

### Multiple Sources
```
magnet:?xt=urn:btih:abc123...
https://example.com/file1.zip
https://example.com/file2.zip
magnet:?xt=urn:btih:def456...
```

## Migration Guide

### For New Installations
No special steps needed - the database migration runs automatically.

### For Existing Installations

1. **Backup your database** (recommended):
   ```bash
   docker-compose exec db pg_dump -U alldebrid alldebrid > backup.sql
   ```

2. **Run the migration**:
   ```bash
   docker-compose exec adproxy_api alembic upgrade head
   ```

3. **Restart services**:
   ```bash
   docker-compose restart
   ```

### Backward Compatibility
- All existing magnet-based tasks continue to work
- The `source_type` field defaults to 'magnet' for existing tasks
- User statistics field `total_magnets_processed` now tracks all sources (magnets + links)

## Constants and Configuration

### New Constants in `app/constants.py`
```python
class SourceType:
    MAGNET = "magnet"
    LINK = "link"
    ALL_TYPES = [MAGNET, LINK]

class Limits:
    MAX_SOURCES_PER_SUBMISSION = 10  # Max sources in one submission
```

## Error Handling

### Validation Errors
- Invalid magnet format: "Invalid magnet link format"
- Invalid URL: "URL must start with http:// or https://"
- Mixed invalid sources: Shows line-by-line errors

### AllDebrid Errors
- Link not supported: "Failed to unlock link: <error details>"
- Upload failed: "magnet_upload_failed: <error details>"
- Timeout: "timeout_no_files" (for magnets waiting for resolution)

### Frontend Errors
- Too many sources: "Too many sources (maximum 10 allowed)"
- No sources: "Please enter at least one magnet link or URL"

## Testing Checklist

- [ ] Submit single magnet link
- [ ] Submit single HTTP/HTTPS link
- [ ] Submit multiple mixed sources
- [ ] Test with unsupported link (should fail gracefully)
- [ ] Test with >10 sources (should reject)
- [ ] Verify task reuse for duplicate magnets
- [ ] Verify task reuse for duplicate links
- [ ] Check error messages for failed sources
- [ ] Verify download completion for both types
- [ ] Test backward compatibility with existing tasks

## Troubleshooting

### Link not supported by AllDebrid
**Symptom**: Task fails with "link_info_failed" or "unlock_failed"
**Solution**: AllDebrid may not support that file host. Try a different host or check AllDebrid's supported hosts list.

### Migration fails
**Symptom**: `alembic upgrade head` fails
**Solution**: 
1. Check database connection
2. Verify you're running from the correct container
3. Check for conflicting migrations

### Tasks stuck in "resolving"
**Symptom**: Link-based tasks stuck in resolving state
**Solution**: Check AllDebrid API logs for errors. The link may be invalid or rate-limited.

## Architecture Diagram

```
User Input → Frontend → API → Worker → AllDebrid → aria2 → Storage
    ↓           ↓        ↓       ↓         ↓
Validation  Multi-Task  DB   Type-Switch  Download
            Creation         (Magnet/Link)
```

## Code Structure

```
app/
├── validation.py       # Source validation (magnet/link)
├── providers/
│   └── alldebrid.py   # AllDebrid API client
├── utils.py           # Hash generation, identifiers
├── constants.py       # SourceType, Limits
├── models.py          # Task model with source_type
└── api.py             # Task creation endpoint

worker/
└── worker.py          # Type-specific workflows

frontend/
├── app.py             # Multi-source submission
└── templates/
    └── index.html     # Updated UI

alembic/versions/
└── 0004_add_source_type.py  # Database migration
```

## Future Enhancements

Potential improvements for future versions:
- Support for more source types (FTP, torrents, etc.)
- Batch link checking before submission
- Link preview/metadata display
- Per-source progress tracking in UI
- Support for password-protected links
- Integration with more debrid services

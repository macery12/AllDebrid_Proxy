# Video Streaming Debugging Guide

This guide helps you diagnose and fix video streaming issues in AllDebrid Proxy.

## Common Issue: Grey Screen / Video Won't Play

If your video loads but shows a grey screen and won't play, follow these steps:

### Step 1: Check Video Format Compatibility

Not all video formats work well in web browsers. Browser support varies:

**✅ Best Formats (Full Browser Support):**
- MP4 (H.264 codec) - Recommended
- WebM (VP8/VP9 codec)
- M4V

**⚠️ Limited Support:**
- MKV (Matroska) - May work in some browsers but not recommended for web
- AVI - Old format, poor browser support
- MOV - Works in Safari, limited elsewhere
- WMV, FLV - Legacy formats, minimal support

**Solution:** If using MKV or other formats, consider transcoding to MP4:
```bash
# Using ffmpeg to convert to MP4
ffmpeg -i input.mkv -c:v copy -c:a aac output.mp4
```

### Step 2: Use the Debug Button

1. Navigate to the video player page
2. Click the "🐛 Debug Info" button
3. Review the information displayed:
   - File size (ensure it's not 0 bytes)
   - MIME type detection
   - Browser compatibility notes
   - Recommendations

### Step 3: Check Browser Console

1. Open browser Developer Tools (F12)
2. Go to Console tab
3. Look for errors related to:
   - Network errors (CORS, 404, 403)
   - Codec errors ("format not supported")
   - Decoding errors ("decoding failed")

### Step 4: Verify File Integrity

Ensure the file is fully downloaded:
- Check if there's a "⏳ Downloading..." indicator
- File size should match expected size
- No `.aria2` control file present

### Step 5: Test Direct Download

Try downloading the file and playing it locally:
1. Click "Download" button on video player
2. Play the file with VLC or another media player
3. If it doesn't play locally, the file may be corrupted

### Step 6: Check Network/Server Issues

**CORS Headers:** The streaming endpoint now includes proper CORS headers. If you're using a reverse proxy (nginx), ensure it's not stripping these headers.

**Range Requests:** Video seeking requires HTTP Range request support. The server now properly handles:
- `Range: bytes=0-1023` requests
- Partial content (206) responses
- Accept-Ranges header

**Nginx Configuration:** If using the provided `debrid.conf`, ensure:
```nginx
# These headers are critical for video streaming
add_header Access-Control-Allow-Origin "*" always;
add_header Accept-Ranges bytes always;
proxy_set_header Range $http_range;
```

### Step 7: Advanced Debugging

**Check the debug endpoint directly:**
```bash
curl https://your-domain/debug/video/<task_id>/<relpath>
```

This returns JSON with detailed file information.

**Test video element state:**
Open browser console on the video player and run:
```javascript
const video = document.getElementById('videoPlayer');
console.log({
  readyState: video.readyState,  // Should be 4 when ready
  networkState: video.networkState,  // Should be 1 or 2
  error: video.error,  // Should be null
  currentSrc: video.currentSrc
});
```

## Common Error Codes

| Error Code | Meaning | Solution |
|------------|---------|----------|
| MEDIA_ERR_ABORTED (1) | User aborted download | Reload page |
| MEDIA_ERR_NETWORK (2) | Network error | Check connection, server logs |
| MEDIA_ERR_DECODE (3) | Decoding failed | File corrupted or unsupported codec |
| MEDIA_ERR_SRC_NOT_SUPPORTED (4) | Format not supported | Convert to MP4/WebM |

## Video Codec Issues

If the container format is supported but video still won't play, check the codec:

**Browser-Compatible Codecs:**
- **Video:** H.264, VP8, VP9, AV1
- **Audio:** AAC, MP3, Opus, Vorbis

**Incompatible Codecs:**
- **Video:** H.265/HEVC (limited support), MPEG-2, DivX, XviD
- **Audio:** AC3, DTS, FLAC (in some browsers)

Check codec with ffprobe:
```bash
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 video.mkv
```

## Server-Side Checks

**File Permissions:** Ensure the web server can read the files:
```bash
ls -la /srv/storage/<task_id>/files/
```

**Disk Space:** Check if download completed:
```bash
df -h /srv/storage
```

**Aria2 Status:** Check if download is complete:
```bash
# .aria2 control file should not exist
ls /srv/storage/<task_id>/files/*.aria2
```

## Still Having Issues?

1. **Check logs:**
   ```bash
   docker logs adproxy_frontend
   ```

2. **Test with a known-good video:**
   - Download a sample MP4: https://sample-videos.com/
   - Upload and test playback

3. **Browser compatibility:**
   - Try different browsers (Chrome, Firefox, Safari)
   - Try incognito/private mode
   - Disable browser extensions

4. **Network path:**
   - If behind reverse proxy, check proxy logs
   - Verify no intermediate caching breaking Range requests
   - Test direct access to frontend (bypass nginx)

## Recent Fixes Applied

This version includes:
- ✅ Proper CORS headers for video streaming
- ✅ Enhanced MIME type detection for video formats
- ✅ Improved error messages and logging
- ✅ Debug endpoint for troubleshooting
- ✅ Better Range request handling
- ✅ OPTIONS preflight support for CORS

## Transcoding Recommendation

For best compatibility, transcode videos to web-friendly format:

```bash
# Fast conversion (copy video if H.264, transcode audio)
ffmpeg -i input.mkv -c:v copy -c:a aac -movflags +faststart output.mp4

# Full re-encode for maximum compatibility
ffmpeg -i input.mkv -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k -movflags +faststart output.mp4
```

The `-movflags +faststart` is important for web streaming as it moves metadata to the beginning of the file.

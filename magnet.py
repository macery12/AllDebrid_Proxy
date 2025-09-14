from __future__ import annotations
import hashlib, urllib.parse
try:
    import bencodepy
except Exception:
    bencodepy = None

def torrent_to_magnet(torrent_bytes: bytes, include_trackers: bool = False) -> str:
    if bencodepy is None:
        raise RuntimeError("bencodepy not installed. Add it to requirements.txt")
    data = bencodepy.decode(torrent_bytes)
    info = data[b'info']
    benc = bencodepy.encode(info)
    infohash = hashlib.sha1(benc).hexdigest()
    dn = None
    if b'name' in info:
        try:
            dn = info[b'name'].decode('utf-8', 'ignore')
        except Exception:
            dn = None
    parts = [f"magnet:?xt=urn:btih:{infohash}"]
    if dn:
        parts.append("dn="+urllib.parse.quote(dn))
    if include_trackers and b'announce' in data:
        tr = data[b'announce']
        if isinstance(tr, bytes):
            parts.append("tr="+urllib.parse.quote(tr.decode('utf-8', 'ignore')))
    return "&".join(parts)

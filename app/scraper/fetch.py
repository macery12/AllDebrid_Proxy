import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _data_dir() -> str:
    from app.config import settings
    return settings.SCRAPER_DATA_DIR


def _downloads_dir() -> str:
    d = os.path.join(_data_dir(), "downloads")
    os.makedirs(d, exist_ok=True)
    return d


def _auth_file() -> str:
    return os.path.join(_data_dir(), "auth.json")


def _bluecog_base_url() -> str:
    from app.config import settings
    return settings.BLUECOGURL.rstrip("/")


def _uploads_host() -> str:
    base = _bluecog_base_url()
    host = base.split("//", 1)[-1]
    return f"uploads.{host}"


def _bluecog_host() -> str:
    base = _bluecog_base_url()
    return base.split("//", 1)[-1]


# Link text patterns tried in order — covers English, Russian, and generic fallback
_TORRENT_LINK_PATTERNS = [
    "Download Torrent",
    re.compile(r"download\s*torrent", re.IGNORECASE),
    re.compile(r"скачать\s*торрент", re.IGNORECASE),
    re.compile(r"torrent", re.IGNORECASE),
    re.compile(r"торрент", re.IGNORECASE),
]


def _get_with_retry(session, url, headers, retries=4, base_wait=10):
    # GET with exponential back-off on 429 / 503 responses
    for attempt in range(retries):
        r = session.get(url, headers=headers)
        if r.status_code in (429, 503) and attempt < retries - 1:
            wait = base_wait * (2 ** attempt)
            print(f"  Rate limited ({r.status_code}), retrying in {wait}s...")
            time.sleep(wait)
            continue
        return r
    return r


def load_cookies():
    with open(_auth_file()) as f:
        return json.load(f)["cookies"]


def build_session(url, cookies):
    session = requests.Session()
    bluecog_base = _bluecog_base_url()
    host = _bluecog_host()
    uploads = _uploads_host()
    headers = {
        "Referer": url,
        "Origin": bluecog_base,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    }
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c["domain"].lstrip("."))
        if host in c.get("domain", ""):
            session.cookies.set(c["name"], c["value"], domain=uploads)
    return session, headers


def get_uploads_url(page_url):
    uploads_url = None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(storage_state=_auth_file())
        page = context.new_page()
        page.goto(page_url)
        page.wait_for_load_state("networkidle")

        uploads = _uploads_host()

        def handle_request(request):
            nonlocal uploads_url
            if uploads in request.url and "/torrents/" in request.url:
                uploads_url = request.url

        context.on("request", handle_request)
        page_title = page.title()

        clicked = False
        for pattern in _TORRENT_LINK_PATTERNS:
            locator = page.get_by_role("link", name=pattern)
            try:
                locator.first.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError:
                continue
            try:
                with page.expect_popup(timeout=60_000) as popup_info:
                    locator.first.click(timeout=60_000)
                popup = popup_info.value
                popup.wait_for_load_state("networkidle")
                clicked = True
                break
            except PlaywrightTimeoutError:
                continue

        browser.close()

    return uploads_url, page_title


def fetch_torrent(url: str, old_filename: str = None):
    download_dir = _downloads_dir()
    os.makedirs(download_dir, exist_ok=True)
    cookies = load_cookies()
    session, headers = build_session(url, cookies)

    print(f"Visiting: {url}")
    uploads_url, page_title = get_uploads_url(url)

    if not uploads_url:
        print("Error: could not intercept uploads URL")
        return None, None, "Could not intercept uploads URL", None

    r = _get_with_retry(session, uploads_url, headers)
    if r.status_code != 200:
        print(f"Error: directory listing returned {r.status_code}")
        return None, None, f"Directory listing returned {r.status_code}", None

    soup = BeautifulSoup(r.text, "html.parser")
    torrent_href = next(
        (a["href"] for a in soup.find_all("a", href=True) if a["href"].endswith(".torrent")),
        None,
    )

    if not torrent_href:
        print("Error: no .torrent file found in listing")
        return None, None, "No .torrent file found in listing", None

    torrent_url = (
        torrent_href if torrent_href.startswith("http")
        else uploads_url.rstrip("/") + "/" + torrent_href.lstrip("/")
    )
    filename = torrent_url.split("/")[-1].split("?")[0]

    if old_filename and old_filename == filename:
        return filename, False, None, page_title  # no update needed

    r2 = _get_with_retry(session, torrent_url, headers)
    if r2.status_code != 200:
        print(f"Error: download returned {r2.status_code}")
        return None, None, f"Download returned {r2.status_code}", None

    if old_filename:
        old_path = os.path.join(download_dir, old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
            print(f"Removed old: {old_filename}")

    save_path = os.path.join(download_dir, filename)
    with open(save_path, "wb") as f:
        f.write(r2.content)
    print(f"Downloaded: {save_path}")

    return filename, True, None, page_title

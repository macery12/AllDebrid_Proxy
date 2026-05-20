import os
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from fetch import get_uploads_url, build_session, load_cookies

# Two separate RSS feed URLs — both are optional; a missing URL skips that feed.
RSS_UPDATES_URL = os.environ.get("RSS_UPDATES_URL", "").strip()
RSS_RELEASES_URL = os.environ.get("RSS_RELEASES_URL", "").strip()

if not RSS_UPDATES_URL and not RSS_RELEASES_URL:
    raise SystemExit(
        "At least one of RSS_UPDATES_URL or RSS_RELEASES_URL must be set."
    )

# Runtime data directory — same convention as fetch.py.
_DATA_DIR = os.environ.get("SCRAPER_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(_DATA_DIR, "downloads")
LOG_FILE = os.path.join(_DATA_DIR, "downloaded.json")
DELAY_MIN = 30  # minimum seconds between Playwright sessions
DELAY_MAX = 60  # maximum seconds between Playwright sessions


def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def fetch_rss(url):
    print(f"Fetching RSS: {url}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, "lxml-xml")
    items = []
    for item in soup.find_all("item"):
        link_tag = item.find("link")
        link = link_tag.text.strip() if link_tag and link_tag.text.strip() else ""
        # lxml-xml sometimes parses <link> as a NavigableString with no text;
        # fall back to the guid if needed.
        if not link:
            guid_tag = item.find("guid")
            link = guid_tag.text.strip() if guid_tag else ""
        items.append({
            "title": item.find("title").text.strip() if item.find("title") else "",
            "link": link,
            "date": item.find("pubDate").text.strip() if item.find("pubDate") else "",
        })
    return [i for i in items if i["link"]]  # drop items with no link


def download_torrent(page_url, session, headers, old_filename=None):
    uploads_url, _ = get_uploads_url(page_url)
    if not uploads_url:
        return None, None, "Could not intercept uploads URL"

    r = session.get(uploads_url, headers=headers)
    if r.status_code != 200:
        return None, None, f"Directory listing returned {r.status_code}"

    soup = BeautifulSoup(r.text, "html.parser")
    torrent_href = next(
        (a["href"] for a in soup.find_all("a", href=True) if a["href"].endswith(".torrent")),
        None
    )

    if not torrent_href:
        return None, None, "No .torrent file found in listing"

    torrent_url = (
        torrent_href if torrent_href.startswith("http")
        else uploads_url.rstrip("/") + "/" + torrent_href.lstrip("/")
    )

    filename = torrent_url.split("/")[-1].split("?")[0]

    # filename unchanged — no update needed
    if old_filename and old_filename == filename:
        return filename, False, None

    r2 = session.get(torrent_url, headers=headers)
    if r2.status_code != 200:
        return None, None, f"Download returned {r2.status_code}"

    # remove old torrent if being replaced
    if old_filename:
        old_path = os.path.join(DOWNLOAD_DIR, old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
            print(f"  Removed old: {old_filename}")

    save_path = os.path.join(DOWNLOAD_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(r2.content)

    return filename, True, None


def wait_with_countdown(seconds):
    print(f"  Waiting {seconds}s before next item...")
    for remaining in range(seconds, 0, -1):
        print(f"  {remaining}s remaining...", end="\r")
        time.sleep(1)
    print()


def run_feed(feed_url, feed_label, log, cookies):
    """Fetch one RSS feed and process every item.

    Both feeds use the same logic:
    - Item not in log  → always download (create).
    - Item in log, torrent filename changed → download new, remove old (update).
    - Item in log, torrent filename unchanged → skip.

    Returns an updated copy of *log* and a results summary dict.
    """
    items = fetch_rss(feed_url)
    print(f"\nFound {len(items)} items in {feed_label} feed\n")

    all_items = []
    for item in items:
        existing = log.get(item["link"])
        item["old_filename"] = existing["filename"] if existing else None
        item["is_new"] = existing is None
        all_items.append(item)

    new_count = sum(1 for i in all_items if i["is_new"])
    check_count = sum(1 for i in all_items if not i["is_new"])
    print(f"  {new_count} new, {check_count} checking for updates\n")

    results = {"downloaded": [], "updated": [], "skipped": [], "failed": []}

    for i, item in enumerate(all_items, 1):
        label = "NEW" if item["is_new"] else "CHK"
        print(f"[{i}/{len(all_items)}] [{label}] {item['title']}")

        session, headers = build_session(item["link"], cookies)
        filename, updated, error = download_torrent(
            item["link"], session, headers, item["old_filename"]
        )

        if error:
            print(f"  ✗ Failed: {error}")
            results["failed"].append({"title": item["title"], "error": error})

        elif updated is False:
            print(f"  — No update: {filename}")
            results["skipped"].append(item["title"])

        else:
            status = "Downloaded" if item["is_new"] else "Updated"
            print(f"  ✓ {status}: {filename}")
            log[item["link"]] = {
                "title": item["title"],
                "filename": filename,
                "downloaded_at": datetime.now().isoformat(),
            }
            save_log(log)
            results["downloaded" if item["is_new"] else "updated"].append(item["title"])

        if i < len(all_items):
            wait_with_countdown(random.randint(DELAY_MIN, DELAY_MAX))

    return log, results


def print_summary(label, results):
    print("=" * 40)
    print(
        f"[{label}] Done. "
        f"{len(results['downloaded'])} new, "
        f"{len(results['updated'])} updated, "
        f"{len(results['skipped'])} unchanged, "
        f"{len(results['failed'])} failed."
    )
    if results["updated"]:
        print("\nUpdated:")
        for t in results["updated"]:
            print(f"  ↑ {t}")
    if results["failed"]:
        print("\nFailed:")
        for f in results["failed"]:
            print(f"  ✗ {f['title']}: {f['error']}")


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    log = load_log()
    cookies = load_cookies()

    # --- Updates feed first (never run simultaneously with releases) ---
    if RSS_UPDATES_URL:
        print("\n" + "=" * 40)
        print("PHASE 1: UPDATES FEED")
        print("=" * 40)
        log, results = run_feed(RSS_UPDATES_URL, "updates", log, cookies)
        print_summary("UPDATES", results)
    else:
        print("RSS_UPDATES_URL not set — skipping updates feed.")

    # --- Releases feed second ---
    if RSS_RELEASES_URL:
        print("\n" + "=" * 40)
        print("PHASE 2: RELEASES FEED")
        print("=" * 40)
        log, results = run_feed(RSS_RELEASES_URL, "releases", log, cookies)
        print_summary("RELEASES", results)
    else:
        print("RSS_RELEASES_URL not set — skipping releases feed.")


if __name__ == "__main__":
    main()

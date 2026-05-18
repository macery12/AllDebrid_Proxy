import os
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from datetime import datetime
from fetch import get_uploads_url, build_session, load_cookies

_bluecog_url = os.environ.get("BLUECOGURL")
if not _bluecog_url:
    raise SystemExit("BLUECOGURL environment variable is required but not set.")
RSS_URL = _bluecog_url.rstrip("/") + "/rss.xml"
DOWNLOAD_DIR = "./downloads"
LOG_FILE = "./downloaded.json"
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

def fetch_rss():
    print(f"Fetching RSS: {RSS_URL}")
    r = requests.get(RSS_URL)
    soup = BeautifulSoup(r.content, "lxml-xml")
    items = []
    for item in soup.find_all("item"):
        items.append({
            "title": item.find("title").text.strip(),
            "link": item.find("link").text.strip(),
            "date": item.find("pubDate").text.strip() if item.find("pubDate") else "",
        })
    return items

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

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    log = load_log()
    cookies = load_cookies()

    items = fetch_rss()
    print(f"\nFound {len(items)} items in RSS feed\n")

    # tag each item as new, needs update check, etc
    all_items = []
    for item in items:
        existing = log.get(item["link"])
        item["old_filename"] = existing["filename"] if existing else None
        item["is_new"] = existing is None
        all_items.append(item)

    new_count = sum(1 for i in all_items if i["is_new"])
    check_count = sum(1 for i in all_items if not i["is_new"])
    print(f"{new_count} new, {check_count} checking for updates\n")

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

    print("=" * 40)
    print(f"Done. {len(results['downloaded'])} new, {len(results['updated'])} updated, "
          f"{len(results['skipped'])} unchanged, {len(results['failed'])} failed.")

    if results["updated"]:
        print("\nUpdated:")
        for t in results["updated"]:
            print(f"  ↑ {t}")

    if results["failed"]:
        print("\nFailed:")
        for f in results["failed"]:
            print(f"  ✗ {f['title']}: {f['error']}")

if __name__ == "__main__":
    main()

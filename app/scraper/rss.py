import os
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from app.scraper.fetch import get_uploads_url, build_session, load_cookies


def _data_dir() -> str:
    from app.config import settings
    return settings.SCRAPER_DATA_DIR


def _downloads_dir() -> str:
    d = os.path.join(_data_dir(), "downloads")
    os.makedirs(d, exist_ok=True)
    return d


def _log_file() -> str:
    return os.path.join(_data_dir(), "downloaded.json")


def _rss_updates_url() -> str:
    return os.environ.get("RSS_UPDATES_URL", "").strip()


def _rss_releases_url() -> str:
    return os.environ.get("RSS_RELEASES_URL", "").strip()


DELAY_MIN = 30  # minimum seconds between Playwright sessions
DELAY_MAX = 60  # maximum seconds between Playwright sessions


def load_log():
    log_file = _log_file()
    if os.path.exists(log_file):
        with open(log_file) as f:
            return json.load(f)
    return {}


def save_log(log):
    with open(_log_file(), "w") as f:
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
        if not link:
            guid_tag = item.find("guid")
            link = guid_tag.text.strip() if guid_tag else ""
        items.append({
            "title": item.find("title").text.strip() if item.find("title") else "",
            "link": link,
            "date": item.find("pubDate").text.strip() if item.find("pubDate") else "",
        })
    return [i for i in items if i["link"]]


def download_torrent(page_url, session, headers, old_filename=None):
    uploads_url, _ = get_uploads_url(page_url)
    if not uploads_url:
        return None, None, "Could not intercept uploads URL"

    r = session.get(uploads_url, headers=headers)
    if r.status_code != 200:
        return None, None, f"Directory listing returned {r.status_code}"

    from bs4 import BeautifulSoup as _BS
    soup = _BS(r.text, "html.parser")
    torrent_href = next(
        (a["href"] for a in soup.find_all("a", href=True) if a["href"].endswith(".torrent")),
        None,
    )

    if not torrent_href:
        return None, None, "No .torrent file found in listing"

    torrent_url = (
        torrent_href if torrent_href.startswith("http")
        else uploads_url.rstrip("/") + "/" + torrent_href.lstrip("/")
    )
    filename = torrent_url.split("/")[-1].split("?")[0]

    if old_filename and old_filename == filename:
        return filename, False, None

    r2 = session.get(torrent_url, headers=headers)
    if r2.status_code != 200:
        return None, None, f"Download returned {r2.status_code}"

    download_dir = _downloads_dir()
    if old_filename:
        old_path = os.path.join(download_dir, old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
            print(f"  Removed old: {old_filename}")

    save_path = os.path.join(download_dir, filename)
    with open(save_path, "wb") as f:
        f.write(r2.content)

    return filename, True, None


def _wait_with_countdown(seconds):
    print(f"  Waiting {seconds}s before next item...")
    for remaining in range(seconds, 0, -1):
        print(f"  {remaining}s remaining...", end="\r")
        time.sleep(1)
    print()


def run_feed(feed_url, feed_label, log, cookies):
    items = fetch_rss(feed_url)
    print(f"\nFound {len(items)} items in {feed_label} feed\n")

    for item in items:
        existing = log.get(item["link"])
        item["old_filename"] = existing["filename"] if existing else None
        item["is_new"] = existing is None

    new_count = sum(1 for i in items if i["is_new"])
    check_count = sum(1 for i in items if not i["is_new"])
    print(f"  {new_count} new, {check_count} checking for updates\n")

    results = {"downloaded": [], "updated": [], "skipped": [], "failed": []}

    for idx, item in enumerate(items, 1):
        label = "NEW" if item["is_new"] else "CHK"
        print(f"[{idx}/{len(items)}] [{label}] {item['title']}")
        session, headers = build_session(item["link"], cookies)
        filename, updated, error = download_torrent(item["link"], session, headers, item["old_filename"])

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

        if idx < len(items):
            _wait_with_countdown(random.randint(DELAY_MIN, DELAY_MAX))

    return log, results


def main():
    rss_updates = _rss_updates_url()
    rss_releases = _rss_releases_url()
    if not rss_updates and not rss_releases:
        print("At least one of RSS_UPDATES_URL or RSS_RELEASES_URL must be set — skipping RSS.")
        return

    os.makedirs(_downloads_dir(), exist_ok=True)
    log = load_log()
    cookies = load_cookies()

    if rss_updates:
        print("\n" + "=" * 40 + "\nPHASE 1: UPDATES FEED\n" + "=" * 40)
        log, results = run_feed(rss_updates, "updates", log, cookies)
        _print_summary("UPDATES", results)
    else:
        print("RSS_UPDATES_URL not set — skipping updates feed.")

    if rss_releases:
        print("\n" + "=" * 40 + "\nPHASE 2: RELEASES FEED\n" + "=" * 40)
        log, results = run_feed(rss_releases, "releases", log, cookies)
        _print_summary("RELEASES", results)
    else:
        print("RSS_RELEASES_URL not set — skipping releases feed.")


def _print_summary(label, results):
    print("=" * 40)
    print(f"[{label}] Done. {len(results['downloaded'])} new, {len(results['updated'])} updated, {len(results['skipped'])} unchanged, {len(results['failed'])} failed.")
    if results["updated"]:
        print("\nUpdated:")
        for t in results["updated"]:
            print(f"  ↑ {t}")
    if results["failed"]:
        print("\nFailed:")
        for f in results["failed"]:
            print(f"  ✗ {f['title']}: {f['error']}")

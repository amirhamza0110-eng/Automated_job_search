"""
Daily job watcher for one or more websites.
It checks configured pages for new postings matching keywords.
When a new job appears, it generates a WhatsApp share link and opens WhatsApp Web.

Usage:
  python automation.py        # run once
  python automation.py --loop # keep checking every day

Configure SEARCH_URLS and JOB_KEYWORDS for your target site.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen_jobs.json"
REPORT_FILE = BASE_DIR / "job_report.html"
CHECK_INTERVAL_SECONDS = 60 * 60 * 24  # 1 day

# Configure your target pages here.
SEARCH_URLS = [
    "https://bjitgroup.com/career",
]

# Add words that identify the jobs you care about.
JOB_KEYWORDS = [
    "job",
    "vacancy",
    "career",
    "hiring",
    "developer",
    "engineer",
    "python",
    "devops",
    "it",
]

# If you want a WhatsApp message pre-addressed to a specific phone,
# use the full international phone number without + or spaces.
# For example: "15551234567" for +1 555 123 4567.
WHATSAPP_PHONE_NUMBER = "+8801785210338"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_seen_jobs() -> dict[str, Any]:
    if not SEEN_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("Seen jobs file is corrupt; rebuilding it.")
        return {}


def save_seen_jobs(data: dict[str, Any]) -> None:
    SEEN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def format_timestamp(timestamp: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def build_html_report(jobs: dict[str, Any]) -> None:
    rows: list[str] = []
    for job_id, job in sorted(jobs.items(), key=lambda item: item[1].get("first_seen", 0), reverse=True):
        title = html.escape(job["title"])
        url = html.escape(job["url"])
        source = html.escape(job.get("source", ""))
        first_seen = format_timestamp(job.get("first_seen", 0))
        message = f"New job found: {job['title']}\n{job['url']}"
        whatsapp_link = build_whatsapp_url(message)
        rows.append(
            f"""
            <tr>
                <td><a href="{url}" target="_blank">{title}</a></td>
                <td>{source}</td>
                <td>{first_seen}</td>
                <td><a class="button" href="{html.escape(whatsapp_link)}" target="_blank">Send</a></td>
            </tr>
            """
        )

    if not rows:
        rows_html = "<tr><td colspan=\"4\">No jobs found yet.</td></tr>"
    else:
        rows_html = "\n".join(rows)

    html_content = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
        <title>Job Search Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 24px; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background: #f4f4f4; }}
            .button {{ display: inline-block; padding: 8px 12px; background: #25D366; color: white; text-decoration: none; border-radius: 5px; }}
            .button:hover {{ background: #1ebe5d; }}
        </style>
    </head>
    <body>
        <h1>Job Search Report</h1>
        <p>Open the link in a browser and click "Send" to share the vacancy via WhatsApp.</p>
        <table>
            <thead>
                <tr>
                    <th>Job Title</th>
                    <th>Source Page</th>
                    <th>First Seen</th>
                    <th>Share</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """

    REPORT_FILE.write_text(html_content, encoding="utf-8")
    logging.info("Wrote HTML report to %s", REPORT_FILE)


def fetch_page(url: str) -> str:
    logging.info("Fetching %s", url)
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return response.text


def build_job_id(title: str, url: str) -> str:
    digest = hashlib.sha256(f"{title}|{url}".encode("utf-8")).hexdigest()
    return digest


def extract_job_posts(html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, str]] = []

    for link in soup.find_all("a", href=True):
        text = link.get_text(separator=" ", strip=True)
        if not text:
            continue
        lower = text.lower()
        if any(keyword.lower() in lower for keyword in JOB_KEYWORDS):
            href = link["href"].strip()
            full_url = urljoin(base_url, href)
            candidates.append(
                {
                    "title": text,
                    "url": full_url,
                }
            )

    for heading_tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        for heading in soup.find_all(heading_tag):
            text = heading.get_text(separator=" ", strip=True)
            if not text:
                continue
            lower = text.lower()
            if any(keyword.lower() in lower for keyword in JOB_KEYWORDS):
                anchor = heading.find_parent("a")
                if anchor and anchor.get("href"):
                    full_url = urljoin(base_url, anchor["href"].strip())
                else:
                    full_url = base_url
                candidates.append(
                    {
                        "title": text,
                        "url": full_url,
                    }
                )

    unique: dict[str, dict[str, str]] = {}
    for job in candidates:
        key = f"{job['title']}|{job['url']}"
        if key not in unique:
            unique[key] = job
    return list(unique.values())


def build_whatsapp_url(message: str) -> str:
    encoded = quote_plus(message)
    if WHATSAPP_PHONE_NUMBER:
        return f"https://api.whatsapp.com/send?phone={WHATSAPP_PHONE_NUMBER}&text={encoded}"
    return f"https://web.whatsapp.com/send?text={encoded}"


def send_whatsapp_notification(job: dict[str, str]) -> None:
    message = f"New job found: {job['title']}\n{job['url']}"
    whatsapp_url = build_whatsapp_url(message)
    logging.info("New job detected: %s", job["title"])
    logging.info("Opening WhatsApp link: %s", whatsapp_url)
    webbrowser.open(whatsapp_url)


def check_for_new_jobs(seen_jobs: dict[str, Any]) -> dict[str, Any]:
    for url in SEARCH_URLS:
        try:
            html = fetch_page(url)
        except Exception as exc:
            logging.error("Failed to fetch %s: %s", url, exc)
            continue

        jobs = extract_job_posts(html, url)
        logging.info("Found %d candidate posts on %s", len(jobs), url)

        for job in jobs:
            job_id = build_job_id(job["title"], job["url"])
            if job_id in seen_jobs:
                continue
            seen_jobs[job_id] = {
                "title": job["title"],
                "url": job["url"],
                "source": url,
                "first_seen": int(time.time()),
            }
            send_whatsapp_notification(job)

    return seen_jobs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily website job watcher with WhatsApp link alerts.")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Keep running and check once per day.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CHECK_INTERVAL_SECONDS,
        help="Interval between checks in seconds when --loop is enabled.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seen_jobs = load_seen_jobs()

    while True:
        seen_jobs = check_for_new_jobs(seen_jobs)
        save_seen_jobs(seen_jobs)
        build_html_report(seen_jobs)

        if not args.loop:
            break

        logging.info("Waiting %d seconds for the next check.", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

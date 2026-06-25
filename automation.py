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
import logging
import re
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
REPORT_FILE = BASE_DIR / "index.html"
CHECK_INTERVAL_SECONDS = 60 * 60 * 24  # 1 day

# Configure your target pages here.
SEARCH_URLS = [
    "https://datasoft-bd.com",
    "https://brainstation-23.easy.jobs/",
    "https://career.southtechgroup.com/"
    "https://tigerit.com",
    "https://riseuplabs.com/jobs/",
    "https://nascenia.com/category/career/",
    "https://career.cefalo.com/#jobs"
    "https://enosisbd.pinpointhq.com/#js-careers-jobs-block",
    "https://genexinfosys.com/position.php"
]
# Only match vacancy postings for these roles.
JOB_TITLE_PATTERNS = [
    r"\bdevops engineer\b",
    r"\bnetwork engineer\b",
    r"\bSoftware QA Engineer\b",
    r"\bSr. DevOps Engineer\b",
    r"\bit engineer\b",
    r"\bcloud engineer\b",
    r"\bsite reliability engineer\b",
    r"\bsupport engineer\b",
    r"\bsr\.\s+\w+\s+engineer\b",  # Generic: Sr. {something} Engineer
    r"\b\w+\s+engineer\b",  # Generic: {something} Engineer
    r"\b\w+\s+developer\b",  # Generic: {something} Developer
]
JOB_TITLE_REGEX = [re.compile(pattern, re.IGNORECASE) for pattern in JOB_TITLE_PATTERNS]
JOB_CONTEXT_PATTERNS = [
    r"\bcareer\b",
    r"\bcareers\b",
    r"\bjob\b",
    r"\bvacancy\b",
    r"\bvacancies\b",
    r"\bopening\b",
    r"\bopenings\b",
    r"\bposition\b",
    r"\bapply\b",
    r"\bopportunity\b",
    r"\bhiring\b",
    r"\brecruit\b",
    r"\bjoin us\b",
    r"\bjoin our team\b",
    r"\bwork with us\b",
    r"\bjobs\b",
]
JOB_CONTEXT_REGEX = [re.compile(pattern, re.IGNORECASE) for pattern in JOB_CONTEXT_PATTERNS]
JOB_URL_SEGMENTS = [
    "/career",
    "/careers",
    "/job",
    "/jobs",
    "/vacancy",
    "/vacancies",
    "/apply",
    "/opening",
    "/openings",
    "/position",
    "/hiring",
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


def format_timestamp(timestamp: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def build_html_report(jobs: list[dict[str, Any]]) -> None:
    cards: list[str] = []
    for job in sorted(jobs, key=lambda job: job.get("first_seen", 0), reverse=True):
        title = html.escape(job["title"])
        url = html.escape(job["url"])
        source = html.escape(job.get("source", ""))
        first_seen = format_timestamp(job.get("first_seen", 0))
        # Create a message for THIS specific job only
        message = f"New job found: {job['title']}\n{job['url']}"
        whatsapp_link = build_whatsapp_url(message)
        cards.append(
            f"""
            <div class="job-card">
                <h3 class="job-title"><a href="{url}" target="_blank">{title}</a></h3>
                <div class="job-details">
                    <p class="job-source"><strong>Company:</strong> {source}</p>
                    <p class="job-date"><strong>Found:</strong> {first_seen}</p>
                </div>
                <div class="job-actions">
                    <a class="btn-view" href="{url}" target="_blank">View Job</a>
                    <a class="btn-whatsapp" href="{html.escape(whatsapp_link)}" target="_blank">Share on WhatsApp</a>
                </div>
            </div>
            """
        )

    if not cards:
        cards_html = '<div class="no-jobs"><p>No matching jobs found today.</p></div>'
    else:
        cards_html = "\n".join(cards)

    job_count = len(jobs)
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Job Search Report</title>
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Poppins', sans-serif;
                background-color: #f8f9fa;
                padding: 30px 20px;
                color: #333;
            }}
            
            .container {{
                max-width: 1000px;
                margin: 0 auto;
            }}
            
            .header {{
                background-color: #ffffff;
                border-radius: 8px;
                padding: 40px 30px;
                margin-bottom: 30px;
                text-align: center;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            }}
            
            .welcome {{
                color: #2c3e50;
                font-size: 2.2rem;
                font-weight: 700;
                margin-bottom: 10px;
            }}
            
            .subtitle {{
                color: #666;
                font-size: 1.1rem;
                font-weight: 400;
                margin-bottom: 20px;
            }}
            
            .job-count-badge {{
                display: inline-block;
                background-color: #007bff;
                color: white;
                padding: 8px 20px;
                border-radius: 25px;
                font-weight: 600;
                font-size: 0.95rem;
            }}
            
            .jobs-container {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
                gap: 20px;
            }}
            
            .job-card {{
                background-color: #ffffff;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
                transition: box-shadow 0.3s ease;
                border-left: 4px solid #007bff;
            }}
            
            .job-card:hover {{
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
            }}
            
            .job-title {{
                margin-bottom: 15px;
            }}
            
            .job-title a {{
                color: #007bff;
                text-decoration: none;
                font-size: 1.1rem;
                font-weight: 600;
            }}
            
            .job-title a:hover {{
                text-decoration: underline;
                color: #0056b3;
            }}
            
            .job-details {{
                margin-bottom: 15px;
                padding-bottom: 15px;
                border-bottom: 1px solid #e9ecef;
            }}
            
            .job-details p {{
                font-size: 0.95rem;
                margin-bottom: 8px;
                color: #555;
            }}
            
            .job-source, .job-date {{
                word-break: break-word;
            }}
            
            .job-actions {{
                display: flex;
                gap: 10px;
            }}
            
            .btn-view, .btn-whatsapp {{
                flex: 1;
                padding: 10px 15px;
                border: none;
                border-radius: 6px;
                text-decoration: none;
                font-weight: 600;
                text-align: center;
                cursor: pointer;
                font-size: 0.95rem;
                transition: all 0.3s ease;
            }}
            
            .btn-view {{
                background-color: #6c757d;
                color: white;
            }}
            
            .btn-view:hover {{
                background-color: #5a6268;
            }}
            
            .btn-whatsapp {{
                background-color: #25D366;
                color: white;
            }}
            
            .btn-whatsapp:hover {{
                background-color: #20ba5a;
            }}
            
            .no-jobs {{
                background-color: #ffffff;
                padding: 60px 20px;
                text-align: center;
                border-radius: 8px;
                color: #999;
                font-size: 1.1rem;
            }}
            
            .footer {{
                text-align: center;
                margin-top: 30px;
                color: #999;
                font-size: 0.9rem;
            }}
            
            @media (max-width: 768px) {{
                .welcome {{
                    font-size: 1.8rem;
                }}
                
                .jobs-container {{
                    grid-template-columns: 1fr;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 class="welcome">Welcome to Your Job Search Dashboard</h1>
                <p class="subtitle">Latest job opportunities matching your profile</p>
                <div class="job-count-badge">
                    {job_count} Job Position{'s' if job_count != 1 else ''} Found
                </div>
            </div>
            
            <div class="jobs-container">
                {cards_html}
            </div>
            
            <div class="footer">
                <p>Last updated: {format_timestamp(int(time.time()))}</p>
            </div>
        </div>
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


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def has_job_title(text: str) -> bool:
    return any(regex.search(text) for regex in JOB_TITLE_REGEX)


def has_job_context(text: str) -> bool:
    return any(regex.search(text) for regex in JOB_CONTEXT_REGEX)


def is_job_link(text: str, href: str) -> bool:
    normalized_text = normalize_text(text)
    normalized_href = href.lower()

    title_in_text = has_job_title(normalized_text)
    context_in_text = has_job_context(normalized_text)
    title_in_href = has_job_title(normalized_href)
    context_in_href = has_job_context(normalized_href)
    
    # Check for allowed path patterns (handles both absolute and relative URLs)
    allowed_path = any(
        segment in normalized_href or segment.lstrip("/") in normalized_href
        for segment in JOB_URL_SEGMENTS
    )

    return (
        (title_in_text and (context_in_text or allowed_path))
        or (title_in_href and (context_in_text or context_in_href or allowed_path))
    )


def extract_job_posts(html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, str]] = []

    # Extract jobs from links (original logic)
    for link in soup.find_all("a", href=True):
        text = link.get_text(separator=" ", strip=True)
        if not text:
            continue
        href = link["href"].strip()
        if not is_job_link(text, href):
            continue

        full_url = urljoin(base_url, href)
        candidates.append(
            {
                "title": text,
                "url": full_url,
            }
        )

    # Also extract jobs from headings (h1, h2, h3, h4) that match job title patterns
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = heading.get_text(separator=" ", strip=True)
        if not text or len(text) < 3:
            continue
        
        normalized_text = normalize_text(text)
        # Check if this heading contains a job title
        if has_job_title(normalized_text):
            candidates.append(
                {
                    "title": text,
                    "url": base_url,
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


def send_whatsapp_notifications(jobs: list[dict[str, str]]) -> None:
    if not jobs:
        return

    lines: list[str] = []
    for index, job in enumerate(jobs, start=1):
        lines.append(f"{index}. {job['title']}\n{job['url']}")

    message = "New jobs found:\n\n" + "\n\n".join(lines)
    whatsapp_url = build_whatsapp_url(message)
    logging.info("Opening WhatsApp link for %d new jobs", len(jobs))
    webbrowser.open(whatsapp_url)


def check_for_new_jobs() -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []

    for url in SEARCH_URLS:
        try:
            html = fetch_page(url)
        except Exception as exc:
            logging.error("Failed to fetch %s: %s", url, exc)
            continue

        jobs = extract_job_posts(html, url)
        logging.info("Found %d candidate posts on %s", len(jobs), url)

        for job in jobs:
            all_jobs.append(
                {
                    "title": job["title"],
                    "url": job["url"],
                    "source": url,
                    "first_seen": int(time.time()),
                }
            )

    return all_jobs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily website job watcher.")
    return parser.parse_args()


def main() -> None:
    jobs = check_for_new_jobs()
    if not jobs:
        logging.info("No matching jobs found.")
    else:
        build_html_report(jobs)
        logging.info("Report generated with %d jobs", len(jobs))


if __name__ == "__main__":
    main()

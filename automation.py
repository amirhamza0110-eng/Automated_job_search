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
        message = f"New job found: {job['title']}\n{job['url']}"
        whatsapp_link = build_whatsapp_url(message)
        cards.append(
            f"""
            <div class="job-card">
                <div class="job-header">
                    <h3><a href="{url}" target="_blank" class="job-title">{title}</a></h3>
                    <span class="job-source">📌 {source}</span>
                </div>
                <div class="job-meta">
                    <span class="job-date">🕐 {first_seen}</span>
                </div>
                <div class="job-actions">
                    <a class="whatsapp-btn" href="{html.escape(whatsapp_link)}" target="_blank">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style="display:inline;margin-right:5px;">
                            <path d="M8 0C3.6 0 0 3.6 0 8c0 1.4.4 2.8 1.1 4L0 16l4.2-1.1C5.2 15.6 6.6 16 8 16c4.4 0 8-3.6 8-8S12.4 0 8 0zm4.5 11.4c-.2.6-1.2 1.1-2 1.3-.6.1-1.4.2-2.2-.2-.5-.2-1.1-.5-1.9-1-.3-.3-.6-.6-.8-.9-.2-.3-.4-.6-.5-1-.1-.4-.2-.8-.1-1.2.1-.4.5-.8.9-1.1.2-.2.4-.3.4-.5s0-.4-.1-.6c-.1-.2-.4-.5-.5-.6-.1-.1-.3-.2-.5-.1-.5.2-1 .5-1.3.9-.3.4-.4.9-.3 1.4.1 1 .5 1.9 1.2 2.6.7.7 1.6 1.1 2.6 1.2.5 0 1-.1 1.5-.3.5-.2.9-.5 1.2-.9.3-.4.4-1 .3-1.5z"/>
                        </svg>
                        Share on WhatsApp
                    </a>
                </div>
            </div>
            """
        )

    if not cards:
        cards_html = '<div class="empty-state"><p>🔍 No matching jobs found today. Check back later!</p></div>'
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
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 40px 20px;
            }}
            
            .container {{
                max-width: 900px;
                margin: 0 auto;
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 50px;
                color: white;
            }}
            
            .welcome-heading {{
                font-size: 2.5rem;
                font-weight: 700;
                color: #fff;
                margin-bottom: 15px;
                text-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
                letter-spacing: -0.5px;
            }}
            
            .subtitle {{
                font-size: 1.1rem;
                color: rgba(255, 255, 255, 0.9);
                font-weight: 400;
                margin-bottom: 10px;
            }}
            
            .job-count {{
                display: inline-block;
                background: rgba(255, 255, 255, 0.2);
                color: white;
                padding: 8px 16px;
                border-radius: 50px;
                font-size: 0.95rem;
                font-weight: 500;
                backdrop-filter: blur(10px);
            }}
            
            .jobs-container {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}
            
            .job-card {{
                background: white;
                border-radius: 12px;
                padding: 24px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
                transition: all 0.3s ease;
                border-left: 5px solid #667eea;
            }}
            
            .job-card:hover {{
                transform: translateY(-5px);
                box-shadow: 0 12px 30px rgba(0, 0, 0, 0.15);
            }}
            
            .job-header {{
                margin-bottom: 16px;
            }}
            
            .job-title {{
                color: #333;
                text-decoration: none;
                font-size: 1.2rem;
                font-weight: 600;
                margin: 0;
                line-height: 1.4;
                transition: color 0.2s;
            }}
            
            .job-title:hover {{
                color: #667eea;
            }}
            
            .job-header h3 {{
                margin: 0 0 10px 0;
            }}
            
            .job-source {{
                display: inline-block;
                color: #666;
                font-size: 0.9rem;
                font-weight: 500;
            }}
            
            .job-meta {{
                display: flex;
                gap: 15px;
                margin-bottom: 16px;
                padding-bottom: 16px;
                border-bottom: 1px solid #f0f0f0;
            }}
            
            .job-date {{
                color: #999;
                font-size: 0.85rem;
                display: flex;
                align-items: center;
                gap: 5px;
            }}
            
            .job-actions {{
                display: flex;
                gap: 10px;
            }}
            
            .whatsapp-btn {{
                flex: 1;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #25D366 0%, #20ba5a 100%);
                color: white;
                padding: 12px 20px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 600;
                font-size: 0.95rem;
                transition: all 0.3s ease;
                border: none;
                cursor: pointer;
                box-shadow: 0 2px 10px rgba(37, 211, 102, 0.2);
            }}
            
            .whatsapp-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(37, 211, 102, 0.3);
            }}
            
            .whatsapp-btn:active {{
                transform: translateY(0);
            }}
            
            .empty-state {{
                text-align: center;
                padding: 60px 20px;
                color: white;
            }}
            
            .empty-state p {{
                font-size: 1.3rem;
                font-weight: 500;
            }}
            
            .footer {{
                text-align: center;
                color: rgba(255, 255, 255, 0.7);
                font-size: 0.9rem;
                margin-top: 40px;
            }}
            
            @media (max-width: 768px) {{
                .welcome-heading {{
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
                <h1 class="welcome-heading">💼 Job Opportunities</h1>
                <p class="subtitle">Your daily job search companion</p>
                <div class="job-count">
                    Found <strong>{job_count}</strong> matching position{'s' if job_count != 1 else ''}
                </div>
            </div>
            
            <div class="jobs-container">
                {cards_html}
            </div>
            
            <div class="footer">
                <p>✨ Last updated: {format_timestamp(int(time.time()))}</p>
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

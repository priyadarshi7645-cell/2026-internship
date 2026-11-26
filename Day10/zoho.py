# zoho_scraper.py

import re
import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree
from urllib.parse import urljoin

import pandas as pd
import dateparser
from dateparser.search import search_dates
from playwright.sync_api import sync_playwright

# ---------------- CONFIGURATION ----------------

COMPANY = "Zoho"

CAREERS_URL = "https://www.zoho.com/careers/"
RSS_URL = "https://careers.zohocorp.com/jobs/Careers/rss"

OUTPUT_DIR = Path("zoho_output")
OUTPUT_DIR.mkdir(exist_ok=True)

CSV_FILE = OUTPUT_DIR / "zoho_current_openings_trimmed.csv"
DB_FILE = OUTPUT_DIR / "zoho_jobs.db"

# ---------------------------------------------


def clean_text(text):
    """Remove unnecessary spaces and line breaks."""
    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def extract_posted_date(text):
    """Extract a real posting date from the job listing text."""

    if not text:
        return None

    settings = {
        "RELATIVE_BASE": datetime.now(),
        "PREFER_DATES_FROM": "past",
        "DATE_ORDER": "DMY",
        "RETURN_AS_TIMEZONE_AWARE": False,
    }

    try:
        matches = search_dates(
            text,
            settings=settings,
            languages=["en"],
        )

        if matches:
            for matched_text, parsed_date in matches:
                matched_text = matched_text.strip()

                # Avoid accidentally interpreting unrelated numbers
                # such as job IDs as dates.
                if (
                    re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", matched_text)
                    or re.search(
                        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
                        matched_text,
                        re.I,
                    )
                    or re.search(r"\b(?:today|yesterday|\d+\s+days?\s+ago)\b",
                                 matched_text, re.I)
                ):
                    return parsed_date.date()

    except Exception as e:
        print("Date extraction error:", e)

    return None


def get_job_description(page, fallback=""):
    """Extract visible text from the job detail page."""
    description = page.locator("#cw-rich-description")
    if not description.count():
        return clean_text(fallback)
    return clean_text(description.inner_text(timeout=5000))


def get_location(text):
    """Basic location extraction from job text."""

    if not text:
        return ""

    location_patterns = [
        r"\bChennai\b",
        r"\bTenkasi\b",
        r"\bCoimbatore\b",
        r"\bBengaluru\b",
        r"\bBangalore\b",
        r"\bHyderabad\b",
        r"\bMumbai\b",
        r"\bDelhi\b",
        r"\bPune\b",
        r"\bAhmedabad\b",
        r"\bSalem\b",
        r"\bTirunelveli\b",
        r"\bMadurai\b",
        r"\bIndia\b",
        r"\bTamil Nadu\b",
    ]

    found = []

    for pattern in location_patterns:
        matches = re.findall(pattern, text, flags=re.I)

        for match in matches:
            normalized = match.strip()

            if normalized and normalized not in found:
                found.append(normalized)

    return ", ".join(found[:5])


def collect_job_links(page):
    """Extract job data from Zoho's published careers-page job-card tags."""

    page.goto(
        CAREERS_URL,
        wait_until="networkidle",
        timeout=90000,
    )
    page.locator("#jobs").wait_for(state="visible", timeout=30000)
    cards = page.locator("#jobs #rec_job_listing_div li.rec-job-info")
    candidates = []

    for i in range(cards.count()):
        card = cards.nth(i)
        link = card.locator("a.rec-inner-links")
        title_element = card.locator(".rec-job-title")
        preview_element = card.locator(".zrsite_Job_Description")
        country_element = card.locator(".jbcountry")
        try:
            title = clean_text(title_element.inner_text(timeout=3000))
            href = link.get_attribute("href")
            description_preview = (
                clean_text(preview_element.inner_text(timeout=3000))
                if preview_element.count()
                else ""
            )
            country = (
                country_element.get_attribute("data-attr")
                or clean_text(country_element.inner_text(timeout=3000))
                if country_element.count()
                else ""
            )
            if not title or not href:
                continue
            full_url = urljoin(CAREERS_URL, href)
            if not full_url.startswith("https://"):
                continue

            candidates.append({
                "title": title,
                "url": full_url,
                "country": clean_text(country),
                "description_preview": description_preview,
            })
        except Exception as e:
            print(f"Could not read Zoho job card {i + 1}: {e}")

    # Remove duplicate URLs
    unique = {}

    for job in candidates:
        unique[job["url"]] = job

    return list(unique.values())


def get_rss_posted_dates(page):
    """Read Zoho's published job dates from its official careers RSS feed."""
    response = page.request.get(RSS_URL, timeout=30000)
    if not response.ok:
        raise RuntimeError(
            f"Zoho careers RSS request failed with HTTP {response.status}."
        )

    root = ElementTree.fromstring(response.body())
    posted_dates = {}
    for item in root.findall("./channel/item"):
        url = item.findtext("link", "").strip().split("?", 1)[0].rstrip("/")
        published = item.findtext("pubDate", "").strip()
        if not url or not published:
            continue
        try:
            posted_dates[url] = parsedate_to_datetime(published).date()
        except (TypeError, ValueError):
            print(f"Ignoring RSS item with invalid publication date: {published}")

    print(f"Published dates available in Zoho RSS: {len(posted_dates)}")
    return posted_dates


def scrape_zoho_jobs():
    results = []
    missing_dates = 0

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )

        print("Opening Zoho Careers...")

        jobs = collect_job_links(page)
        rss_posted_dates = get_rss_posted_dates(page)

        print(f"Current openings found on the careers page: {len(jobs)}")

        for index, job in enumerate(jobs, start=1):

            title = job["title"]
            url = job["url"]
            country = job["country"]

            print(f"\n[{index}/{len(jobs)}] Checking: {title}")

            # Prefer the official feed date; fall back to a visible card date.
            normalized_url = url.split("?", 1)[0].rstrip("/")
            posted_date = rss_posted_dates.get(normalized_url)
            if posted_date is None:
                posted_date = extract_posted_date(job["description_preview"])

            if posted_date is None:
                print("Publication date unavailable; keeping the active listing.")
                missing_dates += 1

            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )

                page.wait_for_timeout(1500)

                description = get_job_description(
                    page,
                    fallback=job["description_preview"],
                )
                location = get_location(description)
                if not location:
                    location = get_location(job["description_preview"])
                if not location:
                    location = country

                results.append({
                    "Job Title": title,
                    "Job Description": description,
                    "Location": location,
                    "Posted Date": (
                        posted_date.strftime("%Y-%m-%d")
                        if posted_date
                        else ""
                    ),
                    "Company": COMPANY,
                    "Job URL": url,
                })

                print("Added:", title)

            except Exception as e:
                print("Failed to open job details:", e)

        browser.close()

    return results, missing_dates


def save_csv_and_database(data):

    df = pd.DataFrame(data)

    required_columns = [
        "Job Title",
        "Job Description",
        "Location",
        "Posted Date",
        "Company",
        "Job URL",
    ]

    if df.empty:
        df = pd.DataFrame(columns=required_columns)
    else:
        df = df[required_columns]
        for column in required_columns:
            df[column] = df[column].map(clean_text)

        # Remove duplicates based on Job URL.
        df = df.drop_duplicates(subset=["Job URL"])

        df["_sort_date"] = pd.to_datetime(df["Posted Date"], errors="coerce")
        df = df.sort_values(
            by="_sort_date",
            ascending=False,
            na_position="last",
        ).drop(columns="_sort_date")

    # Save CSV
    df.to_csv(
        CSV_FILE,
        index=False,
        encoding="utf-8-sig",
    )

    # Save SQLite database
    with sqlite3.connect(DB_FILE) as conn:

        df.to_sql(
            "zoho_jobs",
            conn,
            if_exists="replace",
            index=False,
        )

    print("\n========== FINAL RESULT ==========")
    print("Company:", COMPANY)
    if not df.empty:
        dates = pd.to_datetime(df["Posted Date"], errors="coerce").dropna()
        date_range = (
            f"{dates.min().date()} to {dates.max().date()}"
            if not dates.empty
            else "Unknown"
        )
    else:
        date_range = "No current openings found"
    print("Publication date range:", date_range)
    print("Total jobs:", len(df))
    print("CSV saved:", CSV_FILE)
    print("Database saved:", DB_FILE)

    if not df.empty:
        print("\nJob postings:")
        print(df[["Job Title", "Location", "Posted Date"]].to_string(index=False))

    return df


if __name__ == "__main__":

    scraped_jobs, missing_dates = scrape_zoho_jobs()

    final_df = save_csv_and_database(scraped_jobs)

    print("\nCurrent listings without a publication date:", missing_dates)

    print("\nScraping completed.")

from datetime import date, datetime, timedelta
from urllib.parse import quote_plus, urljoin
import os
import re
import sqlite3
import sys

import pandas as pd
from playwright.sync_api import sync_playwright


# Change these values to select roles and the posting date window.
ROLES = [
    "Cloud Engineer",
    "Software Engineer"
]
LAST_N_DAYS = 30
MAX_SEARCH_PAGES = 5

os.makedirs("output", exist_ok=True)

INDIA_STATES = {
    "Haryana", "Telangana", "Karnataka", "Tamil Nadu", "Maharashtra",
    "Delhi", "Kerala", "Gujarat", "Rajasthan", "Uttar Pradesh",
    "West Bengal", "Andhra Pradesh", "Madhya Pradesh", "Punjab", "Odisha"
}

COLUMNS = [
    "Company", "Job_Title", "Country", "City", "State",
    "Posting_Date", "Job_Description", "Job_URL"
]


def collect_search_links(browser, role):
    page = browser.new_page()
    urls = set()
    search_succeeded = False

    for page_number in range(MAX_SEARCH_PAGES):
        search_url = (
            "https://careers.wipro.com/search/?"
            f"q={quote_plus(role)}&locationsearch=India"
            "&searchResultView=LIST"
        )
        if page_number:
            search_url += f"&pageNumber={page_number}"

        print(f"\nSearching: {role} | Page {page_number + 1}")
        for attempt in range(1, 4):
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                search_succeeded = True
                break
            except Exception as error:
                print(f"Search attempt {attempt}/3 failed: {error}")
                if attempt == 3:
                    break
                page.wait_for_timeout(2000 * attempt)

        if not search_succeeded:
            break

        try:
            page.wait_for_timeout(3000)
            links_before = len(urls)
            for anchor in page.locator("a").all():
                href = anchor.get_attribute("href")
                if href and "/job/" in href:
                    urls.add(urljoin("https://careers.wipro.com", href))

            print(f"Links collected: {len(urls)}")
            if len(urls) == links_before:
                print("No new job links found; stopping pagination.")
                break

        except Exception as error:
            print("Could not read search results:", error)
            break

    page.close()
    return urls, search_succeeded


def parse_posting_date(value):
    if not value:
        return None

    for date_format in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), date_format).date()
        except ValueError:
            continue
    return None


def extract_description(text):
    description_match = re.search(
        r"\bJob Description\b\s*(.*?)(?=\s+Reinvent your world\b|\s+Wipro\.com\s+Explore All Jobs|$)",
        text,
        re.I
    )
    if not description_match:
        return ""

    description = description_match.group(1).strip()

    # Some Wipro pages repeat title/location metadata before the actual overview.
    overview_start = re.search(
        r"\b(?:Role Overview|Role Purpose)\s*:?",
        description,
        re.I
    )
    if overview_start:
        description = description[overview_start.start():].strip()

    return description


def append_jobs_to_sqlite(df, database_path):
    with sqlite3.connect(database_path) as connection:
        df.head(0).to_sql("jobs", connection, if_exists="append", index=False)
        connection.execute(
            "DELETE FROM jobs WHERE rowid NOT IN "
            "(SELECT MIN(rowid) FROM jobs GROUP BY Job_URL)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_url ON jobs (Job_URL)"
        )

        column_names = ", ".join(f'"{column}"' for column in df.columns)
        placeholders = ", ".join("?" for _ in df.columns)
        insert_sql = f"INSERT OR IGNORE INTO jobs ({column_names}) VALUES ({placeholders})"
        cursor = connection.executemany(
            insert_sql,
            df.itertuples(index=False, name=None)
        )
        return cursor.rowcount


def extract_job(page, url, role, cutoff_date):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        text = re.sub(r"\s+", " ", page.locator("body").inner_text())

        try:
            title = page.locator("h1").first.inner_text().strip()
            title = re.sub(r"^Job\s*Title\s*:\s*", "", title, flags=re.I)
        except Exception:
            title = ""

        if not title:
            title_match = re.search(
                r"(?:^|\s)Job Title\s*:\s*([^\r\n]+?)(?=\s+(?:City|State/Province|Job Family|Role Overview)|$)",
                text,
                re.I
            )
            title = title_match.group(1).strip() if title_match else ""

        city_match = re.search(r"City:\s*(.*?)\s+State/Province:", text, re.I)
        state_match = re.search(
            r"State/Province:\s*(.*?)\s+Posting Start Date:", text, re.I
        )
        date_match = re.search(r"Posting Start Date:\s*([\d/]+)", text, re.I)

        city = city_match.group(1).strip() if city_match else ""
        state = state_match.group(1).strip() if state_match else ""
        posting_date_raw = date_match.group(1) if date_match else ""

        parsed_date = parse_posting_date(posting_date_raw)
        if parsed_date is None:
            print("Posting date missing or invalid:", url)
            return None
        if parsed_date < cutoff_date:
            return None

        if state not in INDIA_STATES:
            print("Non-India location:", city, state)
            return None

        description = extract_description(text)
        if not description:
            print("Job description missing:", url)

        return {
            "Company": "Wipro",
            "Job_Title": title,
            "Country": "India",
            "City": city,
            "State": state,
            "Posting_Date": parsed_date.isoformat(),
            "Job_Description": description,
            "Job_URL": url,
            "_Role_Search": role,
        }

    except Exception as error:
        print("Job error:", url, error)
        return None


jobs = []
cutoff_date = date.today() - timedelta(days=LAST_N_DAYS)
print(f"Posting cutoff: {cutoff_date.isoformat()} (last {LAST_N_DAYS} day(s))")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)

    job_urls = set()
    successful_searches = 0
    for role in ROLES:
        role_urls, search_succeeded = collect_search_links(browser, role)
        successful_searches += int(search_succeeded)
        job_urls.update(role_urls)

    existing_output = "output/wipro_india_jobs.csv"
    if not job_urls and os.path.exists(existing_output):
        try:
            previous_df = pd.read_csv(existing_output, encoding="utf-8-sig")
            if "Job_URL" in previous_df.columns:
                job_urls.update(previous_df["Job_URL"].dropna().astype(str))
                if job_urls:
                    print(f"Reusing {len(job_urls)} saved job URLs because search returned no links.")
        except Exception as error:
            print("Could not read saved job URLs:", error)

    if not job_urls:
        browser.close()
        print(
            "No job URLs were found from search or the existing CSV. "
            "Check network access; existing output files were not replaced."
        )
        sys.exit(1)

    print(f"\nUnique job URLs to inspect: {len(job_urls)}")

    job_page = browser.new_page()
    for url in sorted(job_urls):
        print("\nOpening:", url)
        matched_role = next(
            (role for role in ROLES if role.lower().replace(" ", "-") in url.lower()),
            "Multi-role search"
        )

        extracted = extract_job(job_page, url, matched_role, cutoff_date)
        if extracted:
            jobs.append(extracted)
            print("Successfully collected:", extracted["Job_Title"], extracted["City"])

    job_page.close()
    browser.close()


df = pd.DataFrame(jobs, columns=COLUMNS)

if "_Role_Search" in df.columns:
    df = df.drop(columns=["_Role_Search"])

df = df.drop_duplicates(subset=["Job_URL"])

file_path = "output/wipro_india_jobs.csv"
try:
    df.to_csv(file_path, index=False, encoding="utf-8-sig")
except PermissionError:
    file_path = "output/wipro_india_jobs_updated.csv"
    df.to_csv(file_path, index=False, encoding="utf-8-sig")
    print("Primary CSV is locked; saved the updated data to:", file_path)

print("\nTotal Jobs Collected:", len(df))
print("CSV saved at:", file_path)

database_path = "output/wipro_india_jobs.db"
new_rows = append_jobs_to_sqlite(df, database_path)

print(f"SQLite database saved at: {database_path} ({new_rows} new rows added)")

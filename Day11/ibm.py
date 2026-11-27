#!/usr/bin/env python3
"""Collect recent India job postings from IBM Careers into SQLite and CSV."""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


HEADLESS = True
MAX_PAGES_PER_ROLE = 5
PAGE_SIZE = "30"
LOOKBACK_DAYS = 30
CAREERS_URL = "https://www.ibm.com/in-en/careers/search"
JOB_HOST = "https://careers.ibm.com"
SEARCH_CARD = "a.bx--card-group__card"
ROLE_TITLES = [
    "Software Engineer",
    "Data Analyst",
    "Data Engineer",
    "Business Analyst",
    "Cloud Engineer",
    "Analyst",
]
ROLE_PATTERNS = [
    re.compile(r"\bsoftware[\s-]+engineer\b", re.I),
    re.compile(r"\bdata[\s-]+analyst\b", re.I),
    re.compile(r"\bdata[\s-]+engineer\b", re.I),
    re.compile(r"\bbusiness[\s-]+analyst\b", re.I),
    re.compile(r"\bcloud[\s-]+engineer\b", re.I),
    re.compile(r"\banalyst\b", re.I),
]

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
DB_PATH = OUTPUT_DIR / "ibm_jobs_data.db"
CSV_PATH = OUTPUT_DIR / "ibm_jobs.csv"
IST = timezone(timedelta(hours=5, minutes=30))

COLUMNS = [
    "company",
    "job_title",
    "job_description",
    "location",
    "city",
    "state",
    "country",
    "posted_date",
    "job_url",
]


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = sorted(
        (key.lower(), value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"source", "ref", "utm_source", "utm_medium", "utm_campaign"}
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/").lower(),
         urlencode(query), "")
    )


def parse_iso_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(IST)
        return parsed.date()
    except ValueError:
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None


def jsonld_job_postings(page) -> list[dict]:
    found: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if any(str(item).lower() == "jobposting" for item in types):
                found.append(value)
            for key, child in value.items():
                if key in {"@graph", "mainEntity", "itemListElement"}:
                    visit(child)

    for raw in page.locator('script[type="application/ld+json"]').all_inner_texts():
        try:
            visit(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def as_location_list(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def country_is_india(value: object) -> bool:
    if isinstance(value, dict):
        value = value.get("name") or value.get("identifier")
    return clean_text(value).casefold() in {"india", "in", "ind"}


INDIAN_CITY_STATES = {
    "ahmedabad": "Gujarat",
    "bangalore": "Karnataka",
    "bengaluru": "Karnataka",
    "bhopal": "Madhya Pradesh",
    "bhubaneswar": "Odisha",
    "chandigarh": "Chandigarh",
    "chennai": "Tamil Nadu",
    "coimbatore": "Tamil Nadu",
    "dehradun": "Uttarakhand",
    "delhi": "Delhi",
    "faridabad": "Haryana",
    "ghaziabad": "Uttar Pradesh",
    "gurgaon": "Haryana",
    "gurugram": "Haryana",
    "hyderabad": "Telangana",
    "indore": "Madhya Pradesh",
    "jaipur": "Rajasthan",
    "kochi": "Kerala",
    "kolkata": "West Bengal",
    "lucknow": "Uttar Pradesh",
    "mohali": "Punjab",
    "mumbai": "Maharashtra",
    "mysore": "Karnataka",
    "mysuru": "Karnataka",
    "nagpur": "Maharashtra",
    "new delhi": "Delhi",
    "noida": "Uttar Pradesh",
    "patna": "Bihar",
    "pune": "Maharashtra",
    "raipur": "Chhattisgarh",
    "ranchi": "Jharkhand",
    "surat": "Gujarat",
    "thiruvananthapuram": "Kerala",
    "vadodara": "Gujarat",
    "visakhapatnam": "Andhra Pradesh",
}


def infer_indian_state(city: str) -> str:
    states = []
    for city_name in re.split(r"[,;]", city):
        state = INDIAN_CITY_STATES.get(city_name.strip().casefold())
        if state and state not in states:
            states.append(state)
    return ", ".join(states)


def extract_india_places(posting: dict) -> list[tuple[str, str]]:
    places: list[tuple[str, str]] = []
    for place in as_location_list(posting.get("jobLocation")):
        address = place.get("address")
        if not isinstance(address, dict) or not country_is_india(address.get("addressCountry")):
            continue
        city = clean_text(address.get("addressLocality"))
        state = clean_text(address.get("addressRegion")) or infer_indian_state(city)
        pair = (city, state)
        if pair not in places:
            places.append(pair)
    return places


def title_matches(title: str) -> bool:
    return any(pattern.search(title) for pattern in ROLE_PATTERNS)


def listing_card_data(card) -> dict:
    title = clean_text(card.locator(".bx--card__heading").inner_text())
    copy_locator = card.locator(".ibm--card__copy__inner")
    card_copy = clean_text(copy_locator.inner_text()) if copy_locator.count() else ""
    url = urljoin(JOB_HOST, card.get_attribute("href") or "")
    return {
        "job_title": title,
        "card_location": card_copy,
        "job_url": url,
    }


def extract_posting(page, card_data: dict, today: date) -> tuple[dict | None, str]:
    page.goto(card_data["job_url"], wait_until="domcontentloaded", timeout=90000)
    postings = jsonld_job_postings(page)
    if not postings:
        return None, "missing_jobposting_jsonld"

    posting = postings[0]
    posted = parse_iso_date(posting.get("datePosted"))
    if posted is None:
        return None, "missing_posted_date"
    if not today - timedelta(days=LOOKBACK_DAYS) <= posted <= today:
        return None, "outside_date_window"

    india_places = extract_india_places(posting)
    if not india_places:
        return None, "missing_or_non_india_country"

    cities = list(dict.fromkeys(city for city, _ in india_places if city))
    states = list(dict.fromkeys(state for _, state in india_places if state))
    locations = []
    for city, state in india_places:
        components = [part for part in (city, state, "India") if part]
        if components:
            locations.append(", ".join(components))

    return {
        "company": "IBM",
        "job_title": clean_text(posting.get("title")) or card_data["job_title"],
        "job_description": clean_text(posting.get("description")),
        "location": "; ".join(dict.fromkeys(locations)) or card_data["card_location"],
        "city": ", ".join(cities),
        "state": ", ".join(states),
        "country": "India",
        "posted_date": posted.isoformat(),
        "job_url": card_data["job_url"],
    }, "qualified"


def init_db() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    columns = ", ".join(f'"{name}" TEXT NOT NULL DEFAULT \'\'' for name in COLUMNS)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS ibm_jobs "
                f"(url_norm TEXT PRIMARY KEY, {columns})"
            )
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(ibm_jobs)")
            }
            for name in COLUMNS:
                if name not in existing_columns:
                    conn.execute(
                        f'ALTER TABLE ibm_jobs ADD COLUMN "{name}" '
                        "TEXT NOT NULL DEFAULT ''"
                    )


def existing_urls() -> set[str]:
    urls: set[str] = set()
    with sqlite3.connect(DB_PATH) as conn:
        for (url,) in conn.execute("SELECT job_url FROM ibm_jobs"):
            if url:
                urls.add(normalize_url(url))

        # Also recognize records from the earlier version's table, without
        # changing its schema or replacing any existing data.
        legacy = conn.execute("PRAGMA table_info(jobs)").fetchall()
        legacy_columns = {row[1].casefold(): row[1] for row in legacy}
        legacy_url_column = legacy_columns.get("job_url")
        if legacy_url_column:
            query = f'SELECT "{legacy_url_column}" FROM jobs'
            for (url,) in conn.execute(query):
                if url:
                    urls.add(normalize_url(url))
    return urls


def insert_new(rows: list[dict], known_urls: set[str]) -> int:
    inserted = 0
    placeholders = ", ".join("?" for _ in range(len(COLUMNS) + 1))
    fields = ", ".join(['"url_norm"'] + [f'"{name}"' for name in COLUMNS])
    with sqlite3.connect(DB_PATH) as conn:
        for row in rows:
            norm = normalize_url(row["job_url"])
            if norm in known_urls:
                continue
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO ibm_jobs ({fields}) VALUES ({placeholders})",
                [norm] + [row[name] for name in COLUMNS],
            )
            if cursor.rowcount:
                known_urls.add(norm)
                inserted += 1
    return inserted


def export_csv() -> tuple[int, Path | None]:
    with sqlite3.connect(DB_PATH) as conn:
        selected_columns = ", ".join(f'"{name}"' for name in COLUMNS)
        df = pd.read_sql_query(
            f"SELECT {selected_columns} "
            "FROM ibm_jobs ORDER BY posted_date DESC, job_title",
            conn,
        )
    if df.empty:
        print(f"No stored IBM records; not creating an empty CSV at {CSV_PATH}.")
        return 0, None

    temporary_path = CSV_PATH.with_name(CSV_PATH.name + ".tmp")
    df.to_csv(temporary_path, index=False, encoding="utf-8-sig")
    try:
        try:
            os.replace(temporary_path, CSV_PATH)
            return len(df), CSV_PATH
        except PermissionError:
            alternate_path = CSV_PATH.with_name(
                f"{CSV_PATH.stem}_{datetime.now(IST):%Y%m%d_%H%M%S}.csv"
            )
            os.replace(temporary_path, alternate_path)
            print(f"{CSV_PATH.name} is locked; wrote {alternate_path.name} instead.")
            return len(df), alternate_path
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def wait_for_search(page, action) -> None:
    with page.expect_response(
        lambda response: "search/api/v2" in response.url and response.request.method == "POST",
        timeout=60000,
    ) as response_info:
        action()
    response = response_info.value
    if not response.ok:
        raise RuntimeError(f"IBM search API returned HTTP {response.status}")
    page.locator(SEARCH_CARD).first.wait_for(state="visible", timeout=60000)


def configure_search(page) -> None:
    india_filter = page.locator('a[data-key="India"]')
    if india_filter.count() == 0:
        raise RuntimeError("IBM Careers did not render the India location filter.")
    if not india_filter.is_visible():
        location_accordion = page.get_by_role("button", name="Location", exact=True)
        if location_accordion.count() == 0:
            raise RuntimeError("Could not find IBM's Location filter accordion.")
        location_accordion.click()
        india_filter.wait_for(state="visible", timeout=15000)
    checkbox = india_filter.locator('input[aria-label="India"]')
    if not checkbox.is_checked():
        wait_for_search(page, india_filter.click)

    page_sizes = page.locator("select")
    if page_sizes.count() < 2:
        raise RuntimeError("Could not find IBM's page-size and sorting controls.")
    if page_sizes.nth(0).input_value() != PAGE_SIZE:
        wait_for_search(page, lambda: page_sizes.nth(0).select_option(PAGE_SIZE))

    sort_select = page.locator("select").nth(1)
    if sort_select.locator('option[value="dcdate_desc"]').count():
        try:
            if sort_select.input_value() != "dcdate_desc":
                wait_for_search(page, lambda: sort_select.select_option("dcdate_desc"))
        except PlaywrightTimeoutError as error:
            print(f"  Could not confirm newest-first sorting; continuing: {error}")


def submit_role_search(page, role: str) -> None:
    query = page.locator('input[name="q"]')
    submit = page.locator('button[data-qa="submit"]')
    if query.count() == 0 or submit.count() == 0:
        raise RuntimeError("IBM Careers search box or submit button was not found.")
    wait_for_search(page, lambda: (query.fill(role), submit.click()))


def click_page(page, page_number: int) -> bool:
    page_link = page.locator(
        f'.ibm--pagination__pagelinks [aria-label="Page {page_number}"]'
    )
    if page_link.count() == 0:
        return False
    wait_for_search(page, page_link.first.click)
    return True


def print_debug(page, role: str, reason: str) -> None:
    try:
        print(f"\n[DEBUG] {reason} (search role: {role})")
        print(f"  Page URL: {page.url}")
        print(f"  Job card selector {SEARCH_CARD!r}: {page.locator(SEARCH_CARD).count()}")
        print(f"  Job title selector '.bx--card__heading': "
              f"{page.locator('.bx--card__heading').count()}")
        print(f"  Job-detail links: {page.locator('a[href*=\"JobDetail\"]').count()}")
        print(f"  Pagination selector '.ibm--pagination': "
              f"{page.locator('.ibm--pagination').count()}")
        print(f"  Page text: {page.locator('body').inner_text()[:1200]}")
    except Exception as error:
        print(f"  Could not collect page diagnostics: {error}")


def main() -> int:
    today = datetime.now(IST).date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    print(f"IBM Careers URL: {CAREERS_URL}")
    print(f"India-only postings published {cutoff.isoformat()} through {today.isoformat()}")
    print(f"Roles: {', '.join(ROLE_TITLES)} | maximum pages per role: {MAX_PAGES_PER_ROLE}")

    init_db()
    known_urls = existing_urls()
    print(f"Previously stored/known job URLs: {len(known_urls)}")

    stats: Counter = Counter()
    extracted_rows: dict[str, dict] = {}
    diagnostic_role = ROLE_TITLES[0]
    page = detail_page = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=HEADLESS)
            context = browser.new_context(locale="en-IN")
            page = context.new_page()
            page.goto(CAREERS_URL, wait_until="domcontentloaded", timeout=90000)
            try:
                page.locator(SEARCH_CARD).first.wait_for(state="visible", timeout=90000)
            except PlaywrightTimeoutError as error:
                print_debug(page, diagnostic_role, f"Initial results did not load: {error}")
                print("No scrape was saved because IBM returned no rendered job cards.")
                context.close()
                browser.close()
                return 1

            configure_search(page)
            detail_page = context.new_page()

            for role in ROLE_TITLES:
                diagnostic_role = role
                print(f"\n[IBM] Searching role: {role}")
                try:
                    submit_role_search(page, role)
                    pages_visited = 0
                    for page_number in range(1, MAX_PAGES_PER_ROLE + 1):
                        if page_number > 1 and not click_page(page, page_number):
                            break
                        pages_visited += 1
                        cards = page.locator(SEARCH_CARD)
                        card_count = cards.count()
                        stats["cards_seen"] += card_count
                        print(f"  Page {page_number}: {card_count} rendered cards")

                        page_cards = []
                        for index in range(card_count):
                            try:
                                item = listing_card_data(cards.nth(index))
                            except Exception as error:
                                stats["card_errors"] += 1
                                print(f"  Could not read card {index + 1}: {error}")
                                continue
                            if item["job_title"] and item["job_url"]:
                                page_cards.append(item)

                        for item in page_cards:
                            if not title_matches(item["job_title"]):
                                continue
                            stats["role_title_matches"] += 1
                            norm = normalize_url(item["job_url"])
                            if norm in known_urls or norm in extracted_rows:
                                stats["duplicates_skipped"] += 1
                                continue
                            stats["detail_pages_opened"] += 1
                            try:
                                row, reason = extract_posting(detail_page, item, today)
                            except Exception as error:
                                stats["detail_errors"] += 1
                                print(f"  Detail page failed for {item['job_title']!r}: {error}")
                                continue
                            if row is None:
                                stats["detail_not_qualified"] += 1
                                stats[reason] += 1
                                continue
                            extracted_rows[norm] = row
                            stats["extracted_qualified"] += 1
                            print(f"  Extracted: {row['job_title']} | {row['location']} | "
                                  f"{row['posted_date']}")

                    print(f"  Pages visited for {role}: {pages_visited}")
                except Exception as error:
                    stats["role_search_errors"] += 1
                    print(f"  Search failed for {role}; continuing with other roles: {error}")

            context.close()
            browser.close()
    except Exception as error:
        print(f"\nIBM scraper could not complete browser setup: {error}")
        return 1

    inserted = insert_new(list(extracted_rows.values()), known_urls)
    total_exported, csv_path = export_csv()

    print("\n" + "=" * 58)
    print(f"Job cards found on IBM Careers : {stats['cards_seen']}")
    print(f"Titles matching target roles  : {stats['role_title_matches']}")
    print(f"Detail pages opened           : {stats['detail_pages_opened']}")
    print(f"Recent India jobs extracted   : {stats['extracted_qualified']}")
    print(f"Filtered out / not qualified  : {stats['detail_not_qualified']}")
    print(f"  Missing structured posting  : {stats['missing_jobposting_jsonld']}")
    print(f"  Missing posted date         : {stats['missing_posted_date']}")
    print(f"  Outside 30-day window       : {stats['outside_date_window']}")
    print(f"  Missing/non-India country   : {stats['missing_or_non_india_country']}")
    print(f"Duplicates skipped            : {stats['duplicates_skipped']}")
    print(f"Card/detail errors            : {stats['card_errors'] + stats['detail_errors']}")
    print(f"Role search errors            : {stats['role_search_errors']}")
    print(f"New jobs inserted in SQLite   : {inserted}")
    print(f"Rows in IBM CSV               : {total_exported}")
    print(f"SQLite database               : {DB_PATH}")
    if csv_path:
        print(f"CSV file                      : {csv_path}")
    if not stats["extracted_qualified"]:
        reason = (
            "No new jobs qualified; matching jobs may already be stored or "
            "all candidates were filtered"
            if total_exported
            else "No recent, India-only job postings were extracted"
        )
        print_debug(page, diagnostic_role, reason)
        if not total_exported:
            print("No empty CSV was written. Review the URL, rendered-card counts, "
                  "page selectors, and detail-page/date results above.")
    elif inserted == 0:
        print("All extracted jobs were already present in the database; no rows were overwritten.")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())

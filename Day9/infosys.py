"""
Infosys India job data extractor for:
  https://career.infosys.com/joblist?companyhiringtype=IL&countrycode=IN

Flow (same shape as the Wipro script):
  1. collect_search_results()  - search each role on the Infosys careers site
  2. extract_job()             - open a job page and read the missing details
  3. append to CSV + SQLite    - only NEW jobs are added, nothing is overwritten

Infosys' careers site (career.infosys.com) is a JavaScript app, so the script
reads the JSON the page itself loads (the same data the site shows), falls back
to reading job pages like the Wipro script, and writes diagnostics to
output/infosys_diagnostics/ if nothing is found.
"""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from collections import Counter
import html
import json
import os
import re
import sqlite3
import sys

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# ------------------------------------------------------------------ CONFIG --
# Change these values to select roles and the posting date window.
ROLES = [
    "Software Engineer",
]
LAST_N_DAYS = 7
MAX_SEARCH_PAGES = 3        # "next" / "load more" clicks per role
SAVE_ALL_ROLES = True        # True = save EVERY recent India job, ignoring ROLES
HEADLESS = False             # False = you SEE the browser (use this to debug / avoid bot blocking)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ALL_RESPONSES = []           # every network response of the current attempt (for troubleshooting)
MISSING_DATE = 0             # job pages where no posting date could be found
DETAIL_TEXT_SAMPLE = ""      # text of the first job page that had no date (for troubleshooting)

os.makedirs("output", exist_ok=True)

CSV_PATH = "output/infosys_jobs_data.csv"
DB_PATH = "output/infosys_jobs_data.db"
DIAG_DIR = "output/infosys_diagnostics"

# Your URL first, then two fallbacks used only if it returns nothing.
LIST_URLS = [
    "https://career.infosys.com/joblist?companyhiringtype=IL&countrycode=IN",
    "https://career.infosys.com/joblist?companyhiringtype=IL&countrycode=IN%2F1000",
    "https://career.infosys.com/joblist",
]
DETAIL_URL = "https://career.infosys.com/jobdesc?jobReferenceCode={ref}"
BASE_URL = "https://career.infosys.com"

COLUMNS = [
    "Company", "Job_Title", "Job_ID", "Country", "City", "State",
    "Posting_Date", "Experience_Required", "Job_Type",
    "Job_Description", "Job_URL",
]

CITY_TO_STATE = {
    "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysuru": "Karnataka",
    "mysore": "Karnataka", "mangaluru": "Karnataka", "mangalore": "Karnataka",
    "hubli": "Karnataka", "hubballi": "Karnataka",
    "hyderabad": "Telangana", "pune": "Maharashtra", "mumbai": "Maharashtra",
    "navi mumbai": "Maharashtra", "nagpur": "Maharashtra",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "nagercoil": "Tamil Nadu",
    "chandigarh": "Chandigarh", "mohali": "Punjab", "bhubaneswar": "Odisha",
    "bhubaneshwar": "Odisha", "thiruvananthapuram": "Kerala",
    "trivandrum": "Kerala", "kochi": "Kerala", "kolkata": "West Bengal",
    "gurgaon": "Haryana", "gurugram": "Haryana", "noida": "Uttar Pradesh",
    "lucknow": "Uttar Pradesh", "delhi": "Delhi", "new delhi": "Delhi",
    "jaipur": "Rajasthan", "visakhapatnam": "Andhra Pradesh",
    "vizag": "Andhra Pradesh", "vijayawada": "Andhra Pradesh",
    "ahmedabad": "Gujarat", "indore": "Madhya Pradesh", "bhopal": "Madhya Pradesh",
}


# ---------------------------------------------------- AUTOMATIC ROLE MATCH --
# Same idea as the merged scraper: type plain role names in ROLES and the
# title-matching regex is built automatically.
_ENGINEER_FAMILY = r"(?:engineer(?:s|ing)?|developer(?:s)?)"
_ENGINEER_WORDS = {"engineer", "engineers", "engineering", "developer", "developers"}
_STRICT_DOMAINS = {"software"}
_ABBREVIATIONS = {
    "software engineer": r"\bsde\b",
    "software developer": r"\bsde\b",
}


def build_role_pattern(role):
    words = role.strip().lower().split()
    if not words:
        raise ValueError("ROLES contains an empty role name.")

    last, domain = words[-1], words[:-1]
    title_re = _ENGINEER_FAMILY if last in _ENGINEER_WORDS else re.escape(last) + "s?"

    if not domain:
        pattern = rf"\b{title_re}\b"
    else:
        domain_re = r"[\s\-]+".join(re.escape(word) for word in domain)
        if len(domain) == 1 and domain[0] in _STRICT_DOMAINS:
            pattern = rf"\b{domain_re}[\s\-]+(?:development[\s\-]+)?{title_re}\b"
        else:
            pattern = (
                rf"\b{domain_re}\b.{{0,40}}\b{title_re}\b"
                rf"|\b{title_re}\b.{{0,40}}\b{domain_re}\b"
            )

    extra = _ABBREVIATIONS.get(" ".join(words))
    if extra:
        pattern += "|" + extra
    return re.compile(pattern, re.I)


ROLE_PATTERNS = {role: build_role_pattern(role) for role in ROLES}


def matches_target_role(title):
    return any(pattern.search(title) for pattern in ROLE_PATTERNS.values())


# ---------------------------------------------------------- GENERIC HELPERS --
TITLE_KEYS = ["jobTitle", "title", "jobName", "designation", "postingTitle", "name"]
REF_KEYS = ["jobReferenceCode", "referenceCode", "jobReqId", "requisitionId", "jobId", "id"]
LOCATION_KEYS = ["location", "locations", "jobLocation", "city", "cities", "place"]
CITY_KEYS = ["city", "cityName", "jobCity"]
STATE_KEYS = ["state", "stateName", "province", "stateProvince"]
COUNTRY_KEYS = ["country", "countryName", "jobCountry"]
DATE_KEYS = [
    "createdOn", "postedDate", "postingDate", "datePosted", "postedOn", "publishedDate",
    "createdDate", "creationDate", "startDate", "updatedDate", "jobPostedDate",
]
DESC_KEYS = ["postingDescription", "jobDescription", "description", "roleDescription", "jobDesc", "responsibilities"]
EXPERIENCE_KEYS = [
    "experience", "experienceRequired", "workExperience", "experienceLevel",
    "yearsOfExperience", "minExperience", "exp",
]
JOB_TYPE_KEYS = ["jobType", "employmentType", "employeeType", "workerType", "contractType", "jobNature"]


def pick(record, keys):
    lowered = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, "", [], {}):
            return value
    return None


def flatten(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(part for part in (flatten(v) for v in value) if part)
    if isinstance(value, dict):
        return ", ".join(
            str(v).strip() for v in value.values() if isinstance(v, str) and v.strip()
        )
    return str(value).strip()


def clean_text(value):
    text = html.unescape(flatten(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_posting_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = float(value)
        if number > 1e11:  # epoch milliseconds
            number /= 1000
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y",
        "%b %d, %Y", "%B %d, %Y", "%m/%d/%y", "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(text[:20].strip(), fmt).date()
        except ValueError:
            continue
    return None


DATE_HINTS = ("date", "post", "creat", "publish", "updat", "open", "start")


def _walk_scalars(node, key=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_scalars(v, str(k))
    elif isinstance(node, list):
        for v in node[:5]:
            yield from _walk_scalars(v, key)
    else:
        yield key, node


def auto_date(record):
    """Find a posting date in ANY field whose name hints at a date."""
    for key, value in _walk_scalars(record):
        lowered = key.lower()
        if any(bad in lowered for bad in ("expir", "close", "end", "valid", "deadline")):
            continue  # an expiry date is NOT a posting date
        if not any(hint in lowered for hint in DATE_HINTS):
            continue
        parsed = parse_posting_date(value)
        if parsed and 2015 <= parsed.year <= date.today().year + 1:
            return parsed
    return None


def split_location(city, state, location, country):
    """Return (city, state, country) from whatever the page/API provided."""
    city, state = clean_text(city), clean_text(state)
    location, country = clean_text(location), clean_text(country)

    if not city and location:
        parts = [p.strip() for p in re.split(r"[,/|]", location) if p.strip()]
        parts = [p for p in parts if p.lower() != "india"]
        if parts:
            city = parts[0]
        if len(parts) > 1 and not state:
            state = parts[1]

    if not state:
        state = CITY_TO_STATE.get(city.lower(), "")

    is_india = (
        country.lower() in ("in", "ind", "india")
        or "india" in country.lower()
        or "india" in location.lower()
        or city.lower() in CITY_TO_STATE
    )
    if country and country.lower() not in ("in", "ind") and "india" not in country.lower():
        is_india = False
    return city, state, "India" if is_india else country


# ------------------------------------------------- TEXT (DETAIL PAGE) PARSE --
DATE_TEXT_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}[-\s][A-Za-z]{3,9}[-\s,]+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}"
)


def parse_detail_text(text):
    """Read labelled fields from a job page's text (Wipro-style regexes)."""
    out = {}

    m = re.search(
        r"(?:Posted(?:\s+On|\s+Date)?|Posting\s+(?:Start\s+)?Date|Date\s+Posted)\s*[:\-]?\s*(.{0,30})",
        text, re.I,
    )
    if m:
        found = DATE_TEXT_RE.search(m.group(1))
        out["date"] = parse_posting_date(found.group(0)) if found else None

    m = re.search(
        r"Locations?\s*[:\-]?\s*(.*?)(?=\s+(?:Job|Posted|Experience|Skills|Role|Education|Apply|Employment)\b|$)",
        text, re.I,
    )
    if m:
        out["location"] = m.group(1).strip()

    m = re.search(
        r"Experience(?:\s+Required|\s+Level)?\s*[:\-]?\s*(\d+\s*(?:\+|[-–]|to)?\s*\d*\s*\+?\s*(?:years?|yrs?)?)",
        text, re.I,
    )
    if m:
        out["experience"] = re.sub(r"\s+", " ", m.group(1)).strip()

    m = re.search(
        r"(?:Job|Employment|Work(?:er)?)\s*Type\s*[:\-]?\s*"
        r"(Full[\s-]?time|Part[\s-]?time|Contract(?:or)?|Permanent|Intern(?:ship)?|Temporary)",
        text, re.I,
    )
    if m:
        out["job_type"] = m.group(1).strip()

    m = re.search(
        r"\bJob Description\b\s*:?\s*(.*?)(?=\s+(?:Apply Now|Similar Jobs|Recruitment fraud)\b|$)",
        text, re.I,
    )
    if m:
        out["description"] = m.group(1).strip()

    return out


# ------------------------------------------------------- JSON RECORD PARSING --
def find_job_records(node, found):
    """Collect lists of dicts that look like job records inside any JSON."""
    if isinstance(node, list):
        dicts = [item for item in node if isinstance(item, dict)]
        if dicts and any(
            pick(item, TITLE_KEYS) and pick(item, REF_KEYS) for item in dicts[:5]
        ):
            found.extend(dicts)
            return
        for item in node:
            find_job_records(item, found)
    elif isinstance(node, dict):
        for value in node.values():
            find_job_records(value, found)


def job_url_from_ref(ref):
    return DETAIL_URL.format(ref=quote_plus(ref))


def record_to_prefill(record):
    """Turn one API record into a partial job dict (may lack some fields)."""
    title = clean_text(pick(record, TITLE_KEYS))
    ref = flatten(pick(record, REF_KEYS))
    if not title or not ref:
        return None

    city, state, country = split_location(
        pick(record, CITY_KEYS),
        pick(record, STATE_KEYS),
        pick(record, LOCATION_KEYS),
        pick(record, COUNTRY_KEYS),
    )

    experience = clean_text(pick(record, EXPERIENCE_KEYS))
    if not experience:
        low = pick(record, ["minExperienceLevel", "minExperience"])
        high = pick(record, ["maxExperienceLevel", "maxExperience"])
        if low is not None or high is not None:
            experience = f"{low if low is not None else 0}-{high if high is not None else ''} years".replace("- years", "+ years")

    description = clean_text(pick(record, DESC_KEYS))
    if not description:
        parts = []
        for label, key in (
            ("Role & Responsibilities", "rolesResponsibilities"),
            ("Additional Responsibility", "additionalResponsibility"),
            ("Technical Requirement", "technicalRequirement"),
            ("Preferred Skills", "preferredSkills"),
            ("Educational Requirement", "educationalRequirement"),
        ):
            text = clean_text(record.get(key))
            if text:
                parts.append(f"{label}: {text}")
        description = " | ".join(parts)

    role_text = " ".join(
        filter(None, [title, clean_text(record.get("roleDesignation"))])
    )
    return {
        "Company": "Infosys",
        "Job_Title": title,
        "Job_ID": ref,
        "Country": country,
        "City": city,
        "State": state,
        "Posting_Date": parse_posting_date(pick(record, DATE_KEYS)) or auto_date(record),
        "Experience_Required": experience,
        "Job_Type": clean_text(pick(record, JOB_TYPE_KEYS)),
        "Job_Description": description,
        "Job_URL": job_url_from_ref(ref),
        "_Role_Text": role_text,
    }


# ------------------------------------------------------------ SEARCH (PAGE) --
def load_more(page):
    """Click a 'next' / 'load more' control, or scroll. True if it acted."""
    page.mouse.wheel(0, 20000)
    controls = page.locator(
        "button:has-text('Load more'), button:has-text('Show more'), "
        "button:has-text('Next'), a:has-text('Next'), "
        "[aria-label*='next' i], [aria-label*='load more' i]"
    )
    try:
        for index in range(controls.count()):
            control = controls.nth(index)
            if control.is_visible() and control.is_enabled():
                control.click(timeout=3000)
                return True
    except Exception:
        pass
    return False


def dom_job_links(page):
    links = set()
    for anchor in page.locator("a").all():
        try:
            href = anchor.get_attribute("href")
        except Exception:
            continue
        if href and ("jobdesc" in href or "jobReferenceCode" in href):
            links.add(urljoin(BASE_URL, href))
    return links


def run_search_attempt(browser, list_url, role, use_search_box):
    """One attempt at a role. Returns (records, links, captured, page)."""
    context = browser.new_context(
        user_agent=USER_AGENT, locale="en-IN", viewport={"width": 1366, "height": 900}
    )
    page = context.new_page()
    captured = []
    ALL_RESPONSES.clear()

    def on_response(response):
        try:
            kind = response.request.resource_type
            ALL_RESPONSES.append((response.status, kind, response.url))
            if kind not in ("xhr", "fetch"):
                return
            # Try to read JSON from every XHR/fetch, whatever its content-type.
            captured.append((response.url, response.status, response.json()))
        except Exception:
            pass

    page.on("response", on_response)

    loaded = False
    for attempt in range(1, 4):
        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
            loaded = True
            break
        except Exception as error:
            print(f"Search attempt {attempt}/3 failed: {error}")
            if attempt < 3:
                page.wait_for_timeout(2000 * attempt)
    if not loaded:
        return [], set(), captured, page

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightTimeoutError:
        page.wait_for_timeout(5000)
    page.wait_for_timeout(5000)  # let the single-page app finish rendering

    try:
        shown = re.sub(r"\s+", " ", page.locator("body").inner_text())[:250]
        print(f"Page title: {page.title()!r}")
        print(f"Page text : {shown!r}")
        print(f"Network   : {len(ALL_RESPONSES)} responses, {len(captured)} readable as JSON")
    except Exception as error:
        print("Could not read the page text:", error)

    if use_search_box:
        box = page.locator(
            "input[type='search'], input[placeholder*='search' i], "
            "input[aria-label*='search' i], input[type='text']"
        )
        try:
            box.first.wait_for(state="visible", timeout=10000)
            box.first.fill(role)
            box.first.press("Enter")
            page.wait_for_timeout(4000)
        except Exception as error:
            print(f"Could not use the search box ({error}); reading the default list.")

    records, links = [], set()
    seen_responses = 0
    for page_number in range(MAX_SEARCH_PAGES):
        print(f"Reading results: {role} | Page {page_number + 1}")
        for _, _, payload in captured[seen_responses:]:
            find_job_records(payload, records)
        seen_responses = len(captured)

        before_links = len(links)
        links |= dom_job_links(page)
        print(f"Records so far: {len(records)} | Links so far: {len(links)}")

        if not load_more(page):
            print("No more pages to open.")
            break
        page.wait_for_timeout(2500)
        if len(captured) == seen_responses and len(dom_job_links(page) | links) == before_links:
            print("No new results after clicking; stopping pagination.")
            break

    for _, _, payload in captured[seen_responses:]:
        find_job_records(payload, records)
    return records, links, captured, page


def write_diagnostics(page, captured, role):
    """Save what the site actually returned so the logic can be corrected."""
    os.makedirs(DIAG_DIR, exist_ok=True)
    safe = re.sub(r"\W+", "_", role)

    endpoints = []
    for url, status, payload in captured:
        keys = list(payload.keys())[:15] if isinstance(payload, dict) else type(payload).__name__
        endpoints.append({
            "url": url, "status": status, "top_level": keys,
            "size": len(json.dumps(payload, default=str)),
            "sample": json.dumps(payload, default=str)[:1500],
        })
    with open(f"{DIAG_DIR}/{safe}_endpoints.json", "w", encoding="utf-8") as f:
        json.dump(endpoints, f, indent=2)

    with open(f"{DIAG_DIR}/{safe}_all_requests.txt", "w", encoding="utf-8") as f:
        for status, kind, url in ALL_RESPONSES:
            f.write(f"{status}\t{kind}\t{url}\n")
    print("  Non-static requests the page made:")
    shown = 0
    for status, kind, url in ALL_RESPONSES:
        if re.search(r"\.(js|css|png|jpe?g|gif|svg|woff2?|ico|ttf)(\?|$)", url, re.I):
            continue
        print(f"   - [{status}] {kind}: {url[:120]}")
        shown += 1
        if shown >= 15:
            break

    try:
        page.screenshot(path=f"{DIAG_DIR}/{safe}_page.png", full_page=True)
        with open(f"{DIAG_DIR}/{safe}_page.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as error:
        print("Could not save page snapshot:", error)

    print(f"\nTROUBLESHOOTING for '{role}':")
    print(f"  JSON responses captured : {len(captured)}")
    for item in endpoints[:10]:
        print(f"   - [{item['status']}] {item['url'][:110]}")
    print(f"  Saved details in: {DIAG_DIR}/ (endpoints, screenshot, HTML)")
    print("  If the screenshot shows jobs but none were parsed, the field names in")
    print("  the endpoints file differ from TITLE_KEYS / REF_KEYS / DATE_KEYS above.")


def collect_search_results(browser, role):
    """Search one role. Tries the India URL, then the plain URL, each with and
    without the search box, before giving up (and saving diagnostics)."""
    attempts = [(url, box) for url in LIST_URLS for box in (True, False)]
    last_page, last_captured = None, []

    for number, (list_url, use_box) in enumerate(attempts, start=1):
        print(f"\nSearching: {role} | attempt {number}/{len(attempts)} "
              f"({'search box' if use_box else 'default list'}) {list_url}")
        records, links, captured, page = run_search_attempt(
            browser, list_url, role, use_box
        )
        if records or links:
            page.close()
            return records, links, True
        if last_page is not None:
            last_page.close()
        last_page, last_captured = page, captured
        print("Nothing found in this attempt; trying the next approach...")

    if last_page is not None:
        write_diagnostics(last_page, last_captured, role)
        last_page.close()
    return [], set(), False


# -------------------------------------------------------------- JOB DETAILS --
def extract_job(page, url, cutoff_date, prefill=None):
    """Complete one job (opening its page only if something is missing) and
    apply the date / India / role filters."""
    global MISSING_DATE, DETAIL_TEXT_SAMPLE
    job = dict(prefill or {})
    try:
        needs_page = (
            not job.get("Posting_Date") or not job.get("Job_Description")
            or not job.get("Job_Title") or not job.get("City")
        )
        if needs_page:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            text = re.sub(r"\s+", " ", page.locator("body").inner_text())
            parsed = parse_detail_text(text)
            if not DETAIL_TEXT_SAMPLE:
                DETAIL_TEXT_SAMPLE = text[:4000]

            if not job.get("Job_Title"):
                try:
                    title = page.locator("h1").first.inner_text().strip()
                    job["Job_Title"] = re.sub(r"^Job\s*Title\s*:\s*", "", title, flags=re.I)
                except Exception:
                    job["Job_Title"] = ""

            job.setdefault("Posting_Date", None)
            if not job["Posting_Date"]:
                job["Posting_Date"] = parsed.get("date")
            if not job.get("City"):
                city, state, country = split_location(
                    "", job.get("State", ""), parsed.get("location", ""), job.get("Country", "")
                )
                job["City"], job["State"], job["Country"] = city, state or job.get("State", ""), country
            if not job.get("Experience_Required"):
                job["Experience_Required"] = parsed.get("experience", "")
            if not job.get("Job_Type"):
                job["Job_Type"] = parsed.get("job_type", "")
            if not job.get("Job_Description"):
                job["Job_Description"] = parsed.get("description", "")

        if not job.get("Job_ID"):
            job["Job_ID"] = parse_qs(urlparse(url).query).get("jobReferenceCode", [""])[0]

        posted = job.get("Posting_Date")
        if posted is None:
            MISSING_DATE += 1
            print("Posting date missing or invalid:", url)
            return None
        if posted < cutoff_date or posted > date.today():
            print(f"Outside the date window (posted {posted.isoformat()}):", job.get("Job_Title"))
            return None
        # The list URL is already filtered to India, so an unknown country is
        # treated as India; only an explicit non-India country is rejected.
        if job.get("Country") not in ("India", ""):
            print("Non-India location:", job.get("City"), job.get("State"))
            return None
        role_text = job.get("_Role_Text") or job.get("Job_Title", "")
        if not job.get("Job_Title") or not (
            SAVE_ALL_ROLES
            or matches_target_role(job["Job_Title"])
            or matches_target_role(role_text)
        ):
            return None
        if not job.get("Job_Description"):
            print("Job description missing:", url)

        return {
            "Company": "Infosys",
            "Job_Title": job["Job_Title"],
            "Job_ID": job.get("Job_ID", ""),
            "Country": "India",
            "City": job.get("City", ""),
            "State": job.get("State", ""),
            "Posting_Date": posted.isoformat(),
            "Experience_Required": job.get("Experience_Required", ""),
            "Job_Type": job.get("Job_Type", ""),
            "Job_Description": job.get("Job_Description", ""),
            "Job_URL": url,
        }
    except Exception as error:
        print("Job error:", url, error)
        return None


# ------------------------------------------------------------------ STORAGE --
def init_db(database_path):
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                Company TEXT, Job_Title TEXT, Job_ID TEXT, Country TEXT,
                City TEXT, State TEXT, Posting_Date TEXT,
                Experience_Required TEXT, Job_Type TEXT,
                Job_Description TEXT, Job_URL TEXT UNIQUE
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_job_url ON jobs (Job_URL)"
        )


def load_known_urls(csv_path, database_path):
    known = set()
    with sqlite3.connect(database_path) as connection:
        known.update(row[0] for row in connection.execute("SELECT Job_URL FROM jobs"))
    if os.path.exists(csv_path):
        try:
            previous = pd.read_csv(csv_path, encoding="utf-8-sig")
            if "Job_URL" in previous.columns:
                known.update(previous["Job_URL"].dropna().astype(str))
        except Exception as error:
            print("Could not read existing CSV:", error)
    return known


def append_jobs_to_sqlite(df, database_path):
    """INSERT OR IGNORE; returns the Job_URLs that were really new."""
    inserted = []
    column_names = ", ".join(f'"{column}"' for column in COLUMNS)
    placeholders = ", ".join("?" for _ in COLUMNS)
    sql = f"INSERT OR IGNORE INTO jobs ({column_names}) VALUES ({placeholders})"
    with sqlite3.connect(database_path) as connection:
        for row in df[COLUMNS].itertuples(index=False, name=None):
            if connection.execute(sql, row).rowcount == 1:
                inserted.append(row[COLUMNS.index("Job_URL")])
    return inserted


def append_jobs_to_csv(df, csv_path):
    path = csv_path
    try:
        header = not os.path.exists(path) or os.path.getsize(path) == 0
        df.to_csv(path, mode="a", header=header, index=False, encoding="utf-8-sig")
    except PermissionError:
        path = csv_path.replace(".csv", "_updated.csv")
        header = not os.path.exists(path) or os.path.getsize(path) == 0
        df.to_csv(path, mode="a", header=header, index=False, encoding="utf-8-sig")
        print("Primary CSV is locked; saved the new rows to:", path)
    return path


# --------------------------------------------------------------------- MAIN --
def main():
    cutoff_date = date.today() - timedelta(days=LAST_N_DAYS)
    print(f"Posting cutoff: {cutoff_date.isoformat()} (last {LAST_N_DAYS} day(s))")

    init_db(DB_PATH)
    known_urls = load_known_urls(CSV_PATH, DB_PATH)
    print(f"Already stored: {len(known_urls)} jobs")

    jobs = {}
    successful_searches = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )

        all_records, all_links = [], set()
        for role in ROLES:
            records, links, succeeded = collect_search_results(browser, role)
            successful_searches += int(succeeded)
            all_records.extend(records)
            all_links |= links

        if successful_searches == 0:
            browser.close()
            print(
                "\nNo job data could be read from the Infosys careers site. "
                f"See {DIAG_DIR}/ for the captured responses and a screenshot. "
                "Existing output files were not changed."
            )
            sys.exit(1)

        # Turn API records into partial jobs; links without records get opened.
        if all_records:
            os.makedirs(DIAG_DIR, exist_ok=True)
            with open(f"{DIAG_DIR}/sample_records.json", "w", encoding="utf-8") as f:
                json.dump(all_records[:5], f, indent=2, default=str)
            first = all_records[0]
            print("\nFields in a job record:", sorted(first.keys()))
            hinted = {k: v for k, v in first.items() if any(h in k.lower() for h in DATE_HINTS)}
            print("Date-like fields       :", hinted or "none found")
            with_date = sum(1 for r in all_records if r.get("createdOn"))
            print(f"Records with a createdOn date: {with_date} of {len(all_records)}")

        pending = {}
        skipped = {"known": 0, "old": 0, "title": 0, "country": 0}
        title_counts, designation_counts, in_window = Counter(), Counter(), 0
        for record in all_records:
            prefill = record_to_prefill(record)
            if not prefill:
                continue
            url = prefill["Job_URL"]
            posted = prefill["Posting_Date"]

            if posted and cutoff_date <= posted <= date.today() and prefill["Country"] in ("India", ""):
                in_window += 1
                title_counts[prefill["Job_Title"]] += 1
                designation_counts[clean_text(record.get("roleDesignation")) or "-"] += 1

            if url in known_urls:
                skipped["known"] += 1
            elif posted and not (cutoff_date <= posted <= date.today()):
                skipped["old"] += 1
            elif not (
                SAVE_ALL_ROLES
                or matches_target_role(prefill["Job_Title"])
                or matches_target_role(prefill.get("_Role_Text", ""))
            ):
                skipped["title"] += 1      # not one of your ROLES: never open it
            elif prefill["Country"] not in ("India", ""):
                skipped["country"] += 1
            else:
                pending[url] = prefill
        for link in all_links:
            if link not in known_urls:
                pending.setdefault(link, {})
        print(f"Records skipped before opening pages: {skipped}")
        print(f"Jobs posted in the last {LAST_N_DAYS} days (India): {in_window}")
        if in_window:
            print("Most common titles in that window (use these words in ROLES):")
            for title, count in title_counts.most_common(15):
                print(f"   {count:4d}  {title}")
            print("Most common role designations in that window:")
            for name, count in designation_counts.most_common(10):
                print(f"   {count:4d}  {name}")

        print(f"\nUnique job URLs to inspect: {len(pending)}")

        job_page = browser.new_page()
        for url in sorted(pending):
            print("\nOpening:", url)
            extracted = extract_job(job_page, url, cutoff_date, pending[url])
            if extracted:
                jobs[url] = extracted
                print("Successfully collected:", extracted["Job_Title"], extracted["City"])
            if MISSING_DATE >= 8 and not jobs:
                os.makedirs(DIAG_DIR, exist_ok=True)
                with open(f"{DIAG_DIR}/job_page_text.txt", "w", encoding="utf-8") as f:
                    f.write(DETAIL_TEXT_SAMPLE)
                print(
                    "\nStopping early: 8 job pages in a row had no readable posting date.\n"
                    f"Send me {DIAG_DIR}/sample_records.json and job_page_text.txt "
                    "so the date field can be mapped."
                )
                break
        job_page.close()
        browser.close()

    new_df = pd.DataFrame(list(jobs.values()), columns=COLUMNS)
    new_df = new_df.drop_duplicates(subset=["Job_URL"])
    if not new_df.empty:
        new_df = new_df.sort_values(by=["Posting_Date", "Job_Title"], ascending=[False, True])

    new_urls = append_jobs_to_sqlite(new_df, DB_PATH) if not new_df.empty else []
    added_df = new_df[new_df["Job_URL"].isin(new_urls)]
    csv_target = CSV_PATH
    if not added_df.empty:
        csv_target = append_jobs_to_csv(added_df, CSV_PATH)

    with sqlite3.connect(DB_PATH) as connection:
        total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    print("\nTotal Jobs in DB:", total)
    print("New Jobs Added:", len(new_urls))
    print("CSV saved at:", csv_target)
    print("SQLite database saved at:", DB_PATH)

    if new_df.empty:
        print(
            "\nThe site was read, but no job matched your roles, the India filter "
            f"and the last {LAST_N_DAYS} days. Try a wider LAST_N_DAYS, check ROLES, "
            f"or look at {DIAG_DIR}/ for what the site returned."
        )


if __name__ == "__main__":
    main()
"""Merge the existing Wipro + Accenture dataset with Infosys job data."""

import argparse
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
MAIN_DEFAULT = Path("..") / "Day9" / "output" / "india_jobs.csv"
INFOSYS_DEFAULT = Path("..") / "Day9" / "output" / "infosys_jobs_data.csv"
BASE_COLUMNS = [
    "Company",
    "Job_Title",
    "Country",
    "Location",
    "Posting_Date",
    "Job_Description",
    "Job_URL",
]
OUTPUT_COLUMNS = [
    "Job_Title",
    "Company",
    "Country",
    "Location",
    "Posting_Date",
    "Job_Description",
    "Job_URL",
]
COMPANIES = ("Wipro", "Accenture", "Infosys")
TECHNICAL_CASES = {
    "AI/ML": "AI/ML",
    "API": "API",
    "ACN": "ACN",
    "AADC": "AADC",
    "AI": "AI",
    "AWS": "AWS",
    "BTP": "BTP",
    "CI/CD": "CI/CD",
    "CMT": "CMT",
    "CRM": "CRM",
    "DevOps": "DevOps",
    "ERP": "ERP",
    "ETL": "ETL",
    "GCP": "GCP",
    "GN": "GN",
    "HR": "HR",
    "IBM": "IBM",
    "I&P": "I&P",
    "IoT": "IoT",
    "IT": "IT",
    "Java": "Java",
    "JavaScript": "JavaScript",
    "ML": "ML",
    "Node.js": "Node.js",
    "QA": "QA",
    "RPA": "RPA",
    "SAP": "SAP",
    "SQL": "SQL",
    "SaaS": "SaaS",
    "SC&O": "SC&O",
    "S&O": "S&O",
    "TypeScript": "TypeScript",
    "UI": "UI",
    "UX": "UX",
    "BPM": "BPM",
}


def resolve_input(path_value):
    """Resolve relative inputs from the script folder or current directory."""
    path = Path(path_value).expanduser()
    candidates = [path] if path.is_absolute() else [SCRIPT_DIR / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(candidate.resolve()) for candidate in candidates)
    raise FileNotFoundError(f"Input file not found. Searched: {searched}")


def title_case_accenture_text(value):
    text = " ".join(str(value).split())
    text = text.title()
    for term, preferred_case in sorted(
        TECHNICAL_CASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        text = re.sub(
            rf"(?<!\w){re.escape(term)}(?!\w)",
            preferred_case,
            text,
            flags=re.IGNORECASE,
        )
    return text


def read_jobs(path_value, company_hint=None):
    path = resolve_input(path_value)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")

    if "Company" not in frame.columns:
        if company_hint is None:
            raise ValueError(f"{path} has no Company column.")
        frame["Company"] = company_hint
    else:
        frame["Company"] = frame["Company"].astype(str)
        if company_hint:
            missing_company = frame["Company"].str.strip().eq("")
            frame.loc[missing_company, "Company"] = company_hint

    if "Location" not in frame.columns:
        frame["Location"] = ""
    city = frame["City"] if "City" in frame.columns else pd.Series("", index=frame.index)
    state = frame["State"] if "State" in frame.columns else pd.Series("", index=frame.index)
    derived_location = (
        city.astype(str).str.strip() + ", " + state.astype(str).str.strip()
    ).str.strip(", ")
    missing_location = frame["Location"].astype(str).str.strip().eq("")
    frame.loc[missing_location, "Location"] = derived_location[missing_location]

    for column in BASE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    if frame["Company"].astype(str).str.strip().eq("").any():
        raise ValueError(f"{path} contains job records without a company name.")
    print(f"Read {len(frame):,} rows from {path}")
    return frame[BASE_COLUMNS].copy()


def merge_jobs(main_path, infosys_path):
    main_df = read_jobs(main_path)
    infosys_df = read_jobs(infosys_path, company_hint="Infosys")
    merged = pd.concat([main_df, infosys_df], ignore_index=True, sort=False).fillna("")

    posting_dates = merged["Posting_Date"].astype(str).str.strip()
    parsed_dates = pd.to_datetime(
        posting_dates, format="%Y-%m-%d", errors="coerce"
    )
    needs_fallback = parsed_dates.isna() & posting_dates.ne("")
    parsed_dates.loc[needs_fallback] = pd.to_datetime(
        posting_dates.loc[needs_fallback], dayfirst=True, errors="coerce"
    )
    valid_dates = parsed_dates.notna()
    merged.loc[valid_dates, "Posting_Date"] = parsed_dates[valid_dates].dt.strftime(
        "%Y-%m-%d"
    )

    today = date.today()
    cutoff = today - timedelta(days=29)
    posting_days = parsed_dates.dt.date
    within_window = (
        parsed_dates.notna()
        & posting_days.ge(cutoff)
        & posting_days.le(today)
    )
    merged = merged.loc[within_window].copy()
    print(
        "Date window (last 30 calendar days): "
        f"{cutoff.isoformat()} through {today.isoformat()}"
    )

    accenture = merged["Company"].astype(str).str.strip().str.casefold().eq("accenture")
    contains_hash = merged[BASE_COLUMNS].astype(str).apply(
        lambda column: column.str.contains("#", regex=False)
    ).any(axis=1)
    remove_accenture = accenture & contains_hash
    print(
        f"Removed {int(remove_accenture.sum()):,} Accenture postings "
        "containing '#'."
    )
    merged = merged.loc[~remove_accenture].copy()
    accenture = merged["Company"].astype(str).str.strip().str.casefold().eq("accenture")

    for column in ("Job_Title", "Company", "Country", "Location"):
        merged.loc[accenture, column] = merged.loc[accenture, column].map(
            title_case_accenture_text
        )
    merged.loc[accenture, "Job_Description"] = merged.loc[
        accenture, "Job_Description"
    ].map(lambda value: " ".join(str(value).split()))

    url_key = merged["Job_URL"].astype(str).str.strip()
    has_url = url_key.ne("")
    merged["_url_key"] = url_key
    with_url = merged.loc[has_url].drop_duplicates(subset=["_url_key"], keep="first")
    without_url = merged.loc[~has_url].drop(columns="_url_key")
    with_url = with_url.drop(columns="_url_key")
    merged = pd.concat([with_url, without_url], ignore_index=True)

    merged["_sort_date"] = pd.to_datetime(merged["Posting_Date"], errors="coerce")
    merged = merged.sort_values(
        by=["_sort_date", "Company", "Job_Title"],
        ascending=[False, True, True],
        na_position="last",
    ).drop(columns="_sort_date")
    return merged[OUTPUT_COLUMNS].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(
        description="Merge Wipro, Accenture, and Infosys job postings."
    )
    parser.add_argument("--main", default=str(MAIN_DEFAULT))
    parser.add_argument("--infosys", default=str(INFOSYS_DEFAULT))
    parser.add_argument(
        "--out",
        default="output/all_companies_jobs.csv",
    )
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    output_path = Path(args.out).expanduser()
    if not output_path.is_absolute():
        output_path = SCRIPT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    database_path = Path(args.db).expanduser() if args.db else output_path.with_suffix(".db")
    if not database_path.is_absolute():
        database_path = SCRIPT_DIR / database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)

    merged = merge_jobs(args.main, args.infosys)
    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    with sqlite3.connect(database_path) as connection:
        merged.to_sql("jobs", connection, if_exists="replace", index=False)

    counts = merged["Company"].value_counts()
    print("\nFinal columns:")
    print(", ".join(merged.columns))
    print("\nJobs per company:")
    for company in COMPANIES:
        print(f"  {company:<10} {int(counts.get(company, 0)):>6,}")
    for company, count in counts.items():
        if company not in COMPANIES:
            print(f"  {company:<10} {int(count):>6,}")
    print(f"\nTotal: {len(merged):,} jobs")
    print(f"CSV: {output_path.resolve()}")
    print(f"SQLite: {database_path.resolve()} (table: jobs)")


if __name__ == "__main__":
    main()

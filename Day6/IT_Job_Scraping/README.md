# Wipro India Job Scraper

Scrapes Wipro Careers listings for configured job roles, filters postings by date, and exports India job details to CSV and SQLite.

## Setup

From this directory, install the Python dependencies and Playwright's Chromium browser:

```powershell
py -m pip install pandas playwright
py -m playwright install chromium
```

## Configure and run

Edit the settings near the top of `main.py`:

```python
ROLES = ["Business Analyst", "Data Analyst"]
LAST_N_DAYS = 30
MAX_SEARCH_PAGES = 5
```

Run the scraper:

```powershell
py main.py
```

The scraper searches each role, collects job pages, filters for India locations and postings within the configured date window, and removes duplicate job URLs from the current run.

## Output files

- `output/wipro_india_jobs.csv` is refreshed with the latest run. If that file is locked, results are written to `output/wipro_india_jobs_updated.csv`.
- `output/wipro_india_jobs.db` contains a SQLite table named `jobs`. New rows are appended; an existing `Job_URL` is ignored, so repeated runs do not duplicate jobs or replace stored rows.

The exported columns are `Company`, `Job_Title`, `Country`, `City`, `State`, `Posting_Date`, `Job_Description`, and `Job_URL`. Dates use `YYYY-MM-DD` format.

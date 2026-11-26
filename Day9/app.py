import sqlite3
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


DB_PATH = Path(__file__).resolve().parent / "output" / "india_jobs.db"

st.set_page_config(
    page_title="India Job Market",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #18382f;
        --muted: #66776f;
        --paper: #eaf0eb;
        --green: #28775a;
        --accent: #d66b4c;
        --line: #d5dfd7;
    }
    .stApp { background: var(--paper); color: var(--ink); }
    section[data-testid="stSidebar"] {
        background: #e1e9e2;
        border-right: 1px solid var(--line);
    }
    .block-container { max-width: 1440px; padding-top: 2rem; }
    .market-header {
        background: #18382f;
        border-left: 6px solid var(--accent);
        border-radius: 5px;
        padding: 1.45rem 1.6rem 1.5rem;
        margin-bottom: 1.4rem;
    }
    .market-kicker {
        color: #a9d8bd;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.4rem;
    }
    .market-title {
        color: #fff;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 2.35rem;
        font-weight: 600;
        line-height: 1.15;
        margin: 0;
    }
    .market-meta { color: #d1dfd5; font-size: 0.9rem; margin-top: 0.55rem; }
    [data-testid="stMetric"] {
        background: #fff;
        border: 1px solid var(--line);
        border-top: 3px solid var(--accent);
        border-radius: 5px;
        padding: 0.9rem 1rem;
    }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { color: var(--ink); }
    h2, h3 { color: var(--ink); }
    div[data-testid="stDataFrame"] { border: 1px solid var(--line); }
    @media (max-width: 700px) {
        .block-container { padding: 1.2rem 1rem 2rem; }
        .market-title { font-size: 1.9rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=60)
def load_jobs(database_path, modified_at):
    with sqlite3.connect(database_path) as connection:
        return pd.read_sql_query(
            """
            SELECT Company, Job_Title, Country, Location, Posting_Date, Job_URL
            FROM jobs
            """,
            connection,
        )


st.sidebar.markdown("### Filters")

if not DB_PATH.exists():
    st.error(f"Could not find the jobs database: {DB_PATH}")
    st.stop()

try:
    jobs = load_jobs(str(DB_PATH), DB_PATH.stat().st_mtime)
except sqlite3.Error as error:
    st.error(f"Could not read the jobs database: {error}")
    st.stop()

if jobs.empty:
    st.info("No job records are stored in the database yet.")
    st.stop()

jobs["Posting_Date"] = pd.to_datetime(jobs["Posting_Date"], errors="coerce")
for column in ("Company", "Job_Title", "Location", "Country", "Job_URL"):
    jobs[column] = jobs[column].fillna("").astype(str).str.strip()

companies = sorted(value for value in jobs["Company"].unique() if value)
locations = sorted(value for value in jobs["Location"].unique() if value)
valid_dates = jobs["Posting_Date"].dropna()

selected_companies = st.sidebar.multiselect(
    "Company", companies, default=companies
)
selected_locations = st.sidebar.multiselect("Location", locations)
title_query = st.sidebar.text_input("Job title", placeholder="e.g. Cloud Engineer")

date_bounds = None
if not valid_dates.empty:
    first_date = valid_dates.min().date()
    last_date = valid_dates.max().date()
    date_mode = st.sidebar.selectbox(
        "Posting window",
        ["Last 7 days", "Last 30 days", "Last 90 days", "All dates", "Custom range"],
        index=1,
    )
    if date_mode == "All dates":
        date_bounds = (first_date, last_date)
    elif date_mode == "Custom range":
        default_start = max(first_date, last_date - timedelta(days=29))
        selected_dates = st.sidebar.date_input(
            "Choose dates",
            value=(default_start, last_date),
            min_value=first_date,
            max_value=last_date,
        )
        if len(selected_dates) == 2:
            date_bounds = selected_dates
    else:
        window_days = int(date_mode.split()[1])
        date_bounds = (
            max(first_date, last_date - timedelta(days=window_days - 1)),
            last_date,
        )

with st.sidebar.expander("Appearance"):
    accent_color = st.color_picker("Accent color", "#d66b4c")

st.markdown(
    f"<style>:root {{ --accent: {accent_color}; }}</style>",
    unsafe_allow_html=True,
)

filtered = jobs.copy()
filtered = filtered[filtered["Company"].isin(selected_companies)]
if selected_locations:
    filtered = filtered[filtered["Location"].isin(selected_locations)]
if title_query.strip():
    filtered = filtered[
        filtered["Job_Title"].str.contains(title_query.strip(), case=False, regex=False)
    ]
if date_bounds:
    start_date, end_date = date_bounds
    filtered = filtered[
        filtered["Posting_Date"].dt.date.between(start_date, end_date)
    ]

latest_posting = valid_dates.max().strftime("%b %d, %Y") if not valid_dates.empty else "—"
st.markdown(
    f"""
    <div class="market-header">
        <div class="market-kicker">India · Technology hiring</div>
        <h1 class="market-title">Job market, at a glance.</h1>
        <div class="market-meta">Accenture + Wipro &nbsp;·&nbsp; Latest posting {latest_posting}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

metric_columns = st.columns(4)
metric_columns[0].metric("Matching roles", f"{len(filtered):,}")
metric_columns[1].metric("Companies", f"{filtered['Company'].nunique():,}")
metric_columns[2].metric("Locations", f"{filtered['Location'].nunique():,}")
filtered_dates = filtered["Posting_Date"].dropna()
metric_columns[3].metric(
    "Newest match",
    filtered_dates.max().strftime("%b %d") if not filtered_dates.empty else "—",
)

st.divider()
chart_columns = st.columns([1.25, 1])
with chart_columns[0]:
    st.subheader("Hiring activity")
    daily = (
        filtered.dropna(subset=["Posting_Date"])
        .groupby(filtered["Posting_Date"].dt.date)
        .size()
        .rename("Roles")
        .to_frame()
    )
    if daily.empty:
        st.caption("No dated roles match these filters.")
    else:
        st.line_chart(daily, color="#28775a", height=270)

with chart_columns[1]:
    st.subheader("Company comparison")
    company_totals = (
        filtered[filtered["Company"] != ""]["Company"]
        .value_counts()
        .rename("Roles")
        .to_frame()
    )
    if company_totals.empty:
        st.caption("No companies match these filters.")
    else:
        st.bar_chart(company_totals, color=accent_color, height=270)

location_columns = st.columns(2)
with location_columns[0]:
    st.subheader("Top locations")
    top_locations = (
        filtered[filtered["Location"] != ""]["Location"]
        .value_counts()
        .head(8)
        .rename("Roles")
        .to_frame()
    )
    if top_locations.empty:
        st.caption("No locations match these filters.")
    else:
        st.bar_chart(top_locations, color="#28775a", height=270)

with location_columns[1]:
    st.subheader("Most-listed roles")
    top_titles = (
        filtered[filtered["Job_Title"] != ""]["Job_Title"]
        .value_counts()
        .head(8)
        .rename("Openings")
        .to_frame()
    )
    if top_titles.empty:
        st.caption("No job titles match these filters.")
    else:
        st.bar_chart(top_titles, color=accent_color, height=270)

st.divider()
table_heading, row_limit_column, download_column = st.columns([3, 1, 1])
with table_heading:
    st.subheader("Recent roles")
    st.caption(f"Showing the newest matches first · {len(filtered):,} total matches")

with row_limit_column:
    row_limit = st.selectbox("Recent rows", [25, 50, 100, 250], index=2)

table = (
    filtered.sort_values("Posting_Date", ascending=False, na_position="last")
    .head(row_limit)
    .copy()
)
table["Posting_Date"] = table["Posting_Date"].dt.strftime("%Y-%m-%d").fillna("")
table = table.rename(
    columns={
        "Company": "Company",
        "Job_Title": "Job title",
        "Location": "Location",
        "Posting_Date": "Posted",
        "Job_URL": "Posting",
    }
)[["Company", "Job title", "Location", "Posted", "Posting"]]

with download_column:
    st.download_button(
        "Download CSV",
        data=table.to_csv(index=False).encode("utf-8-sig"),
        file_name="india_jobs_recent.csv",
        mime="text/csv",
        width="stretch",
    )

st.dataframe(
    table,
    column_config={
        "Job title": st.column_config.TextColumn(width="large"),
        "Posting": st.column_config.LinkColumn("Posting", display_text="Open role"),
    },
    hide_index=True,
    width="stretch",
)
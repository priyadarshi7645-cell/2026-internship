"""📊 Job Market Analytics — Streamlit dashboard for the output of aiw.py.

Put this file next to aiw.py, then:   streamlit run app.py
(Use the sidebar "▶ Run aiw.py merge" button to build/refresh output/all_companies_jobs.db.)
Optional: set JOBS_DB=/path/to/all_companies_jobs.db (or .csv) to read a different file.
"""
from __future__ import annotations

import html
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "aiw.py"
OUT_CSV = HERE / "output" / "all_companies_jobs.csv"
DEFAULT_MAIN = "../Day9/output/india_jobs.csv"
DEFAULT_INFOSYS = "../Day9/output/infosys_jobs_data.csv"
PALETTE = ["#FF4B4B", "#0068C9", "#29B09D", "#FFAB00", "#6C5CE7", "#94A3B8"]
ALL_COUNTRIES = "All Countries"

# ------------------------------------------------------------ skills & cleanup ----
SKILLS = {  # name -> regex matched (case-insensitive) on Job_Title + Job_Description
    "Python": r"\bpython\b", "SQL": r"\bsql\b", "Java": r"\bjava\b",
    "GenAI": r"\b(?:gen ?ai|generative ai)\b", "LLMs": r"\bllms?\b", "RAG": r"\brag\b",
    "Agentic AI": r"\bagentic\b", "Machine Learning": r"\bmachine learning\b",
    "Deep Learning": r"\bdeep learning\b", "NLP": r"\bnlp\b", "MLOps": r"\bmlops\b",
    "PySpark": r"\bpyspark\b", "Databricks": r"\bdatabricks\b", "Snowflake": r"\bsnowflake\b",
    "Azure": r"\bazure\b", "AWS": r"\baws\b", "GCP": r"\bgcp\b", "Kubernetes": r"\bkubernetes\b",
    "Docker": r"\bdocker\b", "TensorFlow": r"\btensorflow\b", "PyTorch": r"\bpytorch\b",
    "ETL": r"\betl\b",
}
_STATES = {"telangana", "karnataka", "maharashtra", "tamil nadu", "gujarat", "rajasthan", "west bengal",
           "odisha", "madhya pradesh", "uttar pradesh", "haryana", "delhi", "kerala", "andhra pradesh"}
_ALIASES = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru", "gurgaon": "Gurugram"}


def clean_location(raw) -> str:
    """'HYDERABAD, Telangana' -> 'Hyderabad'; 'Hyderabad, Pune' -> 'Hyderabad / Pune'."""
    cities: list[str] = []
    for part in str(raw or "").split(","):
        p = part.strip()
        if not p or p.lower() in _STATES:
            continue
        p = _ALIASES.get(p.lower(), p.title())
        if p not in cities:
            cities.append(p)
    return " / ".join(cities) if cities else "Unknown"


def classify_role_family(title) -> str:
    t = str(title or "").lower()
    if "ai / ml" in t or "ai/ml" in t or "machine learning" in t or "mlops" in t:
        return "AI / ML Engineer"
    if any(k in t for k in ("gen ai", "genai", "ai native", "responsible ai", "physical ai", "ai engineer", "- ai")):
        return "AI / GenAI Engineer"
    if "analyst" in t:
        return "Analyst"
    if "data" in t and ("engineer" in t or "platform" in t or "migration" in t):
        return "Data Engineer"
    if "software" in t or "developer" in t or "cloud" in t:
        return "Software Engineer"
    return "Other"


def highlight(text: str, skills: list[str]) -> str:
    safe = html.escape(text or "")
    for s in skills:
        safe = re.sub(f"({SKILLS[s]})", r'<mark style="background:#FDE68A;padding:0 3px;border-radius:4px">\1</mark>',
                      safe, flags=re.I)
    return safe


def skill_snippet(text: str, skill: str | None, width: int = 110) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(SKILLS[skill], text, flags=re.I) if skill else None
    if not m:
        return text[: width * 2] + ("…" if len(text) > width * 2 else "")
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


# ---------------------------------------------------------------- data loading ----
def find_source() -> tuple[Path | None, list[Path]]:
    names = ["output/all_companies_jobs.db", "all_companies_jobs.db",
             "output/all_companies_jobs.csv", "all_companies_jobs.csv"]
    env = os.environ.get("JOBS_DB")
    cands = [Path(env).expanduser()] if env else []
    for d in (HERE, Path.cwd()):
        cands += [d / n for n in names]
    for c in cands:
        if c.is_file():
            return c.resolve(), cands
    return None, cands


@st.cache_data(show_spinner="Reading jobs…")
def load_jobs(path: str, mtime: float) -> pd.DataFrame:  # mtime busts the cache after each aiw.py run
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    else:
        with sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True) as con:
            df = pd.read_sql('SELECT * FROM "jobs"', con)
    df["Posting_Date"] = pd.to_datetime(df["Posting_Date"], errors="coerce")
    df["Location_Clean"] = df["Location"].map(clean_location)
    df["Role_Family"] = df["Job_Title"].map(classify_role_family)
    hay = df["Job_Title"].fillna("") + " " + df["Job_Description"].fillna("")
    for name, pat in SKILLS.items():
        df[f"sk_{name}"] = hay.str.contains(pat, case=False, regex=True)
    return df


def table_schema(path: Path) -> str:
    if path.suffix.lower() == ".csv":
        cols = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
        return "-- CSV columns\n" + "\n".join(f"  {c}" for c in cols)
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as con:
        row = con.execute("SELECT sql FROM sqlite_master WHERE name = 'jobs'").fetchone()
    return row[0] if row else "-- table not found"


def run_aiw() -> None:
    """Callback: run aiw.py like the command line, keep its console output, clear caches."""
    s = st.session_state
    cmd = [sys.executable, str(SCRIPT), "--main", s.get("m_main", DEFAULT_MAIN),
           "--infosys", s.get("m_inf", DEFAULT_INFOSYS), "--out", str(OUT_CSV)]
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=600)
        s["merge_log"] = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
        s["merge_ok"] = r.returncode == 0
    except Exception as exc:  # noqa: BLE001
        s["merge_log"], s["merge_ok"] = f"Could not run aiw.py: {exc}", False
    st.cache_data.clear()


def run_controls() -> None:
    """Sidebar controls for aiw.py (shown with or without data)."""
    if not SCRIPT.exists():
        st.caption("`aiw.py` not found next to app.py — showing existing output only.")
        return
    st.button("▶ Run aiw.py merge", on_click=run_aiw, use_container_width=True,
              type="primary", help="Rebuilds output/all_companies_jobs.db/.csv, then reloads")
    with st.expander("aiw.py inputs"):
        st.text_input("--main (Wipro + Accenture CSV)", DEFAULT_MAIN, key="m_main")
        st.text_input("--infosys (Infosys CSV)", DEFAULT_INFOSYS, key="m_inf")
    if st.session_state.get("merge_log"):
        ok = st.session_state.get("merge_ok")
        (st.success if ok else st.error)("aiw.py finished" if ok else "aiw.py failed")
        with st.expander("aiw.py console output", expanded=not ok):
            st.code(st.session_state["merge_log"])


# ----------------------------------------------------------------- page + style ----
st.set_page_config(page_title="Job Market Analytics · Streamlit", page_icon="📊", layout="wide")
st.markdown("""
<style>
.stApp::before{content:"";position:fixed;top:0;left:0;right:0;height:3px;z-index:999999;
  background:linear-gradient(90deg,#FF4B4B 0%,#FF8C42 35%,#FFAB00 68%,#0068C9 100%);}
[data-testid="stMetric"]{background:#fff;border:1px solid #E6EAF1;border-radius:12px;padding:14px 16px;}
[data-testid="stMetricValue"]{font-weight:700;}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:12px;}
section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]{background:#fff;}
.chart-title{font-size:1rem;font-weight:600;margin:0;}
.chart-sub{font-size:.78rem;color:#555867;margin:0 0 .4rem 0;}
.chip{display:inline-block;font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:6px;
  background:#FFF1F1;color:#FF4B4B;border:1px solid #FFD9D9;margin:0 4px 4px 0;}
.chip-blue{background:#EEF5FF;color:#0068C9;border-color:#D6E6FA;border-radius:999px;}
.mono{font-family:'JetBrains Mono',ui-monospace,monospace;}
</style>""", unsafe_allow_html=True)


def chart_header(title: str, sub: str) -> None:
    st.markdown(f'<p class="chart-title">{title}</p><p class="chart-sub">{sub}</p>', unsafe_allow_html=True)


def style_fig(fig: go.Figure, height: int = 300) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
                      font=dict(family="Inter, system-ui, sans-serif", size=12, color="#0E1117"))
    fig.update_xaxes(gridcolor="#E6EAF1", zeroline=False)
    fig.update_yaxes(gridcolor="#E6EAF1", zeroline=False)
    return fig


NOBAR = {"displayModeBar": False}

# ------------------------------------------------------------------- load data ----
DB_PATH, _searched = find_source()
if DB_PATH is None:
    with st.sidebar:
        run_controls()
    st.title("📊 Job Market Analytics")
    st.info("No merged jobs file yet. Click **▶ Run aiw.py merge** in the sidebar to build "
            "`output/all_companies_jobs.db`.")
    st.markdown("Looked in:\n" + "\n".join(f"- `{p}`" for p in _searched))
    st.stop()

raw = load_jobs(str(DB_PATH), DB_PATH.stat().st_mtime)
if raw.empty:
    with st.sidebar:
        run_controls()
    st.title("📊 Job Market Analytics")
    st.warning("The merged file has 0 jobs (aiw.py keeps only postings from the last 2 days).")
    st.stop()

all_companies = sorted(raw["Company"].dropna().unique())
countries = [ALL_COUNTRIES] + sorted(raw["Country"].dropna().unique())
loc_order = raw["Location_Clean"].value_counts().index.tolist()

# ---------------------------------------------------------------- session state ----
ss = st.session_state
ss.setdefault("f_dedup", True)
ss.setdefault("f_kw", "")
ss.setdefault("f_country", ALL_COUNTRIES)
ss.setdefault("f_comp", all_companies)
ss.setdefault("f_locs", [])
ss.setdefault("skill_pill", None)
ss.setdefault("table_q", "")
ss.setdefault("jd_open", None)
ss["f_comp"] = [c for c in ss["f_comp"] if c in all_companies]
ss["f_locs"] = [x for x in ss["f_locs"] if x in loc_order]
if ss["f_country"] not in countries:
    ss["f_country"] = ALL_COUNTRIES


def reset_filters() -> None:
    ss.update(f_dedup=True, f_kw="", f_country=ALL_COUNTRIES, f_comp=all_companies,
              f_locs=[], skill_pill=None, table_q="")


def toggle_all_companies() -> None:
    ss["f_comp"] = [] if len(ss["f_comp"]) == len(all_companies) else all_companies


def on_city_click() -> None:
    for p in (ss.get("chart_city") or {}).get("selection", {}).get("points", []):
        city = p.get("y")
        if city in loc_order:
            cur = list(ss["f_locs"])
            cur.remove(city) if city in cur else cur.append(city)
            ss["f_locs"] = cur


def on_skill_click() -> None:
    pts = (ss.get("chart_skill") or {}).get("selection", {}).get("points", [])
    if pts and pts[0].get("y") in SKILLS:
        ss["skill_pill"] = pts[0]["y"]


# --------------------------------------------------------------------- sidebar ----
with st.sidebar:
    with st.container(border=True):
        st.caption("DATA SOURCE · 🟢 Active")
        st.code(f"🗄️ {DB_PATH.name}" + ("" if DB_PATH.suffix == ".csv" else " → jobs"), language=None)
        st.toggle("Deduplicate by `Job_URL`", key="f_dedup")
        c1, c2 = st.columns(2)
        c1.button("↻ Refresh DB", on_click=st.cache_data.clear, use_container_width=True)
        c2.button("Reset Filters", on_click=reset_filters, use_container_width=True)
        run_controls()

    st.text_input("Keyword / Skill Search", key="f_kw", placeholder="e.g. GenAI, Python, RAG, L4...")
    st.selectbox("Country (`Country`)", countries, key="f_country")
    h1, h2 = st.columns([3, 1])
    h1.markdown("**Companies** (`Company`)")
    h2.button("Toggle", on_click=toggle_all_companies, key="btn_toggle_comp", help="Toggle all companies")
    st.multiselect("Companies", all_companies, key="f_comp", label_visibility="collapsed")
    st.markdown("**Locations / Hubs** (`Location`)")
    st.pills("Locations", loc_order, selection_mode="multi", key="f_locs", label_visibility="collapsed")
    st.caption("No city selected = all cities")
    with st.expander("View `jobs` Table Schema"):
        st.code(table_schema(DB_PATH), language="sql")

# ------------------------------------------------------------------- filtering ----
base = raw.drop_duplicates("Job_URL") if ss["f_dedup"] else raw


def apply_filters(df: pd.DataFrame, with_locations: bool = True) -> pd.DataFrame:
    if ss["f_country"] != ALL_COUNTRIES:
        df = df[df["Country"] == ss["f_country"]]
    df = df[df["Company"].isin(ss["f_comp"])]
    if with_locations and ss["f_locs"]:
        df = df[df["Location_Clean"].isin(ss["f_locs"])]
    kw = ss["f_kw"].strip().lower()
    if kw:
        hay = (df["Job_Title"] + " " + df["Company"] + " " + df["Location"] + " " + df["Job_Description"]).str.lower()
        df = df[hay.str.contains(kw, regex=False)]
    return df


filtered = apply_filters(base)
filtered_any_loc = apply_filters(base, with_locations=False)  # keeps the city chart clickable

# --------------------------------------------------------------------- header ----
t1, t2 = st.columns([5, 1])
with t1:
    st.title("📊 Job Market Analytics")
    st.caption(f"Live market intelligence from `{DB_PATH.name}` — built by `aiw.py` "
               "(Wipro + Accenture + Infosys, last 2 days)")
with t2:
    if (ss["f_kw"].strip() or ss["f_country"] != ALL_COUNTRIES or ss["f_locs"]
            or len(ss["f_comp"]) != len(all_companies)):
        st.markdown("<div style='text-align:right;padding-top:2rem'>🟡 <b>Filters Applied</b></div>",
                    unsafe_allow_html=True)

if filtered.empty:
    st.warning("No jobs match the current filters. Try **Reset Filters** in the sidebar.")
    st.stop()

# ------------------------------------------------------------------------ KPIs ----
n, n_comp = len(filtered), filtered["Company"].nunique()
hubs = filtered["Location_Clean"].value_counts()
latest = filtered["Posting_Date"].max()
latest_n = int((filtered["Posting_Date"] == latest).sum())
dups_hidden = len(raw) - len(base)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Unique Jobs" if ss["f_dedup"] else "Total Jobs", f"{n:,}",
          f"{n / max(len(base), 1):.0%} of {'unique' if ss['f_dedup'] else 'raw'} ({len(base):,})",
          delta_color="off",
          help=f"Deduplicated on Job_URL ({dups_hidden} dupes hidden)" if ss["f_dedup"] else "Raw rows")
k2.metric("Active Hiring Companies", n_comp, f"{n / n_comp:.1f} jobs/co", delta_color="off")
k3.metric("Top Hiring Hub", hubs.index[0], f"{hubs.iloc[0] / n:.0%} ({hubs.iloc[0]})", delta_color="off")
k4.metric("Latest Posting Date", latest.strftime("%Y-%m-%d") if pd.notna(latest) else "—",
          f"{latest_n:,} posted", delta_color="off")

st.write("")
tab_overview, tab_skills = st.tabs(["📊 Market Overview", "🧠 Skills & JD Intelligence"])


# ---------------------------------------------------------- JD popup (st.dialog) ----
@st.dialog("Job Description", width="large")
def show_jd(job: pd.Series) -> None:
    date_txt = job["Posting_Date"].strftime("%Y-%m-%d") if pd.notna(job["Posting_Date"]) else ""
    st.markdown(f'<span class="chip">{html.escape(str(job["Company"]).upper())}</span>'
                f'<span class="mono" style="font-size:.75rem;color:#555867">Posting_Date: {date_txt}</span>',
                unsafe_allow_html=True)
    st.subheader(job["Job_Title"])
    st.caption(f"📍 {job['Location']}, {job['Country']}")
    stack = [s for s in SKILLS if job[f"sk_{s}"]]
    st.markdown("**Detected Tech Stack**")
    st.markdown("".join(f'<span class="chip chip-blue">{s}</span>' for s in stack) or "_No tracked skills matched_",
                unsafe_allow_html=True)
    st.markdown("**Full Job_Description**")
    st.markdown(f'<div style="white-space:pre-line;max-height:360px;overflow:auto;background:#F8F9FB;'
                f'border:1px solid #E6EAF1;border-radius:12px;padding:14px;font-size:.88rem;line-height:1.55">'
                f'{highlight(job["Job_Description"], stack)}</div>', unsafe_allow_html=True)
    if job["Job_URL"]:
        st.link_button("Open Career URL ↗", job["Job_URL"], type="primary")


# ============================================================= TAB 1: OVERVIEW ====
with tab_overview:
    r1a, r1b = st.columns(2)

    with r1a, st.container(border=True):
        chart_header("Job Postings Over Time", "Daily posting velocity across indexed companies")
        d = filtered.dropna(subset=["Posting_Date"])
        daily = d.groupby(d["Posting_Date"].dt.date).size().reset_index(name="Jobs")
        fig = go.Figure(go.Scatter(
            x=daily["Posting_Date"].astype(str), y=daily["Jobs"], mode="lines+markers",
            line=dict(color="#FF4B4B", width=3), marker=dict(size=9), fill="tozeroy",
            fillcolor="rgba(255,75,75,0.10)", hovertemplate="%{x}<br>%{y} jobs<extra></extra>"))
        fig.update_xaxes(type="category")
        st.plotly_chart(style_fig(fig), use_container_width=True, config=NOBAR)

    with r1b, st.container(border=True):
        chart_header("Top Hiring Locations", "Job distribution by Location · click a bar to toggle that city")
        city = filtered_any_loc["Location_Clean"].value_counts().head(10).iloc[::-1]
        colors = ["#FF4B4B" if c in ss["f_locs"] else "#0068C9" for c in city.index]
        fig = go.Figure(go.Bar(x=city.values, y=city.index, orientation="h", marker_color=colors,
                               hovertemplate="%{y}: %{x} jobs<extra></extra>"))
        fig.update_traces(selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))
        st.plotly_chart(style_fig(fig), use_container_width=True, key="chart_city",
                        on_select=on_city_click, selection_mode="points", config=NOBAR)

    r2a, r2b = st.columns(2)

    with r2a, st.container(border=True):
        chart_header("Jobs by Company", "Open role counts per organization")
        comp = filtered["Company"].value_counts().iloc[::-1]
        fig = go.Figure(go.Bar(x=comp.values, y=comp.index, orientation="h", marker_color="#29B09D",
                               hovertemplate="%{y}: %{x} jobs<extra></extra>"))
        st.plotly_chart(style_fig(fig), use_container_width=True, config=NOBAR)

    with r2b, st.container(border=True):
        chart_header("Role Family Distribution", "Job_Title grouped into role families")
        fam = filtered["Role_Family"].value_counts()
        fig = go.Figure(go.Pie(labels=fam.index, values=fam.values, hole=0.6, sort=False, textinfo="percent",
                               marker=dict(colors=PALETTE, line=dict(color="#fff", width=2))))
        st.plotly_chart(style_fig(fig).update_layout(showlegend=True), use_container_width=True, config=NOBAR)

    # ---- Job Listings Explorer ----
    with st.container(border=True):
        explorer = filtered
        q = ss["table_q"].strip().lower()
        if q:
            m = (explorer["Job_Title"] + " " + explorer["Company"] + " " + explorer["Location"]
                 + " " + explorer["Posting_Date"].dt.strftime("%Y-%m-%d").fillna("")).str.lower()
            explorer = explorer[m.str.contains(q, regex=False)]
        e1, e2 = st.columns([3, 1])
        e1.markdown(f"**Job Listings Explorer** &nbsp; `{len(explorer):,} rows`")
        e1.caption("Click column headers to sort · select a row to open its full Job_Description")
        e2.text_input("Filter table rows", key="table_q", placeholder="Filter table rows...",
                      label_visibility="collapsed")
        explorer = explorer.sort_values("Posting_Date", ascending=False).reset_index(drop=True)
        view = explorer[["Job_Title", "Company", "Country", "Location_Clean", "Posting_Date", "Job_URL"]].rename(
            columns={"Location_Clean": "Location"})
        view["Posting_Date"] = view["Posting_Date"].dt.strftime("%Y-%m-%d")
        sel = st.dataframe(view, use_container_width=True, hide_index=True, height=420,
                           on_select="rerun", selection_mode="single-row", key="explorer_tbl",
                           column_config={"Job_URL": st.column_config.LinkColumn("Job_URL", display_text="Apply / URL ↗")})

    rows = sel.selection.rows if sel and sel.selection else []
    if rows and rows[0] < len(explorer):
        job = explorer.iloc[rows[0]]
        if ss["jd_open"] != job["Job_URL"]:  # open the popup once per selection, not on every rerun
            ss["jd_open"] = job["Job_URL"]
            show_jd(job)
    else:
        ss["jd_open"] = None

# ========================================================= TAB 2: SKILLS & JDs ====
with tab_skills:
    skill_counts = pd.Series({s: int(filtered[f"sk_{s}"].sum()) for s in SKILLS})
    skill_counts = skill_counts[skill_counts > 0].sort_values(ascending=False)
    if ss["skill_pill"] not in skill_counts.index:
        ss["skill_pill"] = None

    s1, s2 = st.columns(2)

    with s1, st.container(border=True):
        chart_header("Top In-Demand Skills Extracted from JDs",
                     "Keyword frequency across Job_Description · click a bar to filter")
        top = skill_counts.head(15).iloc[::-1]
        colors = ["#FF4B4B" if s == ss["skill_pill"] else "#0068C9" for s in top.index]
        fig = go.Figure(go.Bar(x=top.values, y=top.index, orientation="h", marker_color=colors,
                               hovertemplate="%{y}: %{x} jobs<extra></extra>"))
        fig.update_traces(selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1)))
        st.plotly_chart(style_fig(fig, height=420), use_container_width=True, key="chart_skill",
                        on_select=on_skill_click, selection_mode="points", config=NOBAR)

    with s2, st.container(border=True):
        chart_header("Skill-Matched Job Descriptions", "Pick a skill (or click a bar) to highlight matching keywords")
        st.pills("Skill", list(skill_counts.index), key="skill_pill", label_visibility="collapsed",
                 format_func=lambda s: f"{s} ({skill_counts[s]})")
        skill = ss["skill_pill"]
        with st.container(height=330, border=False):
            matched = filtered[filtered[f"sk_{skill}"]] if skill else filtered
            st.caption(f"{len(matched):,} jobs" + (f" mention **{skill}**" if skill else "")
                       + " — showing the first 25")
            for _, r in matched.head(25).iterrows():
                snip = html.escape(skill_snippet(r["Job_Description"], skill))
                if skill:
                    snip = re.sub(f"({SKILLS[skill]})", r'<mark style="background:#FDE68A">\1</mark>', snip,
                                  flags=re.I)
                with st.container(border=True):
                    st.markdown(f"**{r['Job_Title']}** · {r['Company']} · {r['Location_Clean']}")
                    st.markdown(f'<span style="font-size:.8rem;color:#555867">{snip}</span>',
                                unsafe_allow_html=True)
                    if r["Job_URL"]:
                        st.link_button("Open ↗", r["Job_URL"])

    # ---- Company × skill matrix ----
    with st.container(border=True):
        chart_header("Company Tech Stack Co-Occurrence Matrix",
                     "Cell text = job count · colour = share of that company's jobs")
        top_sk = list(skill_counts.head(10).index)
        comps = filtered["Company"].value_counts().index.tolist()
        counts = pd.DataFrame({s: [int(filtered.loc[filtered["Company"] == c, f"sk_{s}"].sum()) for c in comps]
                               for s in top_sk}, index=comps)
        sizes = filtered["Company"].value_counts().reindex(comps)
        share = counts.div(sizes, axis=0)
        fig = go.Figure(go.Heatmap(
            z=share.values, x=top_sk, y=[f"{c} ({sizes[c]})" for c in comps], text=counts.values,
            texttemplate="%{text}", colorscale=[[0, "#FFF5F5"], [1, "#FF4B4B"]], zmin=0, zmax=1,
            showscale=False, xgap=3, ygap=3,
            hovertemplate="%{y}<br>%{x}: %{text} jobs (%{z:.0%})<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(style_fig(fig, height=max(180, 60 * len(comps) + 70)),
                        use_container_width=True, config=NOBAR)
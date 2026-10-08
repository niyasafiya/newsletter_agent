"""
Technomak Executive Newsletter & Admin Console (v3 - persistent)
------------------------------------------------------------------
Same app as before, but backed by SQLite instead of an in-memory dict, so
published updates, Excel imports, and URL imports all survive a restart.

Everything else is unchanged from the frontend's point of view: the exact
same JSON API shapes are returned, so the React frontend (in ../frontend)
does not need any changes.

Run:
    pip install flask openpyxl requests langgraph langgraph-checkpoint-sqlite --break-system-packages
    export ADMIN_PASSWORD="choose-a-real-password"
    python technomak_app.py
Then open http://127.0.0.1:5000 (or run the frontend dev server separately
and let it proxy to this backend - see the frontend's README).

The database file (technomak.db by default, override with DB_PATH) is
created automatically on first run and seeded with the same starting
content the earlier in-memory version had. After that, the seed is never
re-applied - all further content comes from what's actually published,
uploaded, or imported.

SECURITY NOTE: see the previous version's note - the admin password is
never hardcoded or stored in plain text, and the session key is randomized
per run unless SECRET_KEY is set.
"""

import csv
import io
import os
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime

import requests
from flask import (
    Flask, jsonify, redirect, render_template_string,
    request, session, url_for, send_from_directory)
from openpyxl import Workbook, load_workbook
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Preserve the SECTION_META ordering in API responses (Flask sorts JSON keys
# alphabetically by default, which put Project Portfolio in the middle).
app.json.sort_keys = False
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB upload cap

# ---------------------------------------------------------------------------
# CORS - lets a separately-hosted frontend (e.g. the React app's own dev
# server) call this API with session cookies. Deliberately NOT a wildcard
# "*" origin: browsers refuse to send/receive cookies on wildcard-CORS
# requests, and a wildcard would let any website call the admin API using
# a logged-in admin's browser session. Only the origin(s) listed in
# FRONTEND_ORIGIN are allowed. (When the frontend's Vite dev server proxies
# /api and /admin to this backend, the browser sees same-origin requests
# and this CORS layer isn't even exercised - it's a fallback for setups
# that call the backend directly from a different origin.)
# ---------------------------------------------------------------------------
FRONTEND_ORIGINS = [
    o.strip() for o in
    os.environ.get("FRONTEND_ORIGIN", "http://localhost:8443,http://127.0.0.1:8443").split(",")
    if o.strip()
]


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in FRONTEND_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/v1/<path:_any>", methods=["OPTIONS"])
@app.route("/admin/import/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return ("", 204)


ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
_env_password = os.environ.get("ADMIN_PASSWORD")
if _env_password:
    ADMIN_PASSWORD_HASH = generate_password_hash(_env_password)
else:
    _generated_password = secrets.token_urlsafe(9)
    ADMIN_PASSWORD_HASH = generate_password_hash(_generated_password)
    print("=" * 64)
    print(" No ADMIN_PASSWORD environment variable set.")
    print(f" One-time generated password for this run: {_generated_password}")
    print(" Set ADMIN_PASSWORD before deploying anywhere real.")
    print("=" * 64)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "technomak.db"))

# Section metadata is fixed (not user-editable) - only the entries inside
# each section are dynamic and stored in the database.
SECTION_META = {
    "projects": "Project Portfolio",
    "competitors": "Competitor Intelligence",
    "marketing": "Marketing & Sales",
    "ea": "EA / Systems Integration",
    "team": "Team & Leadership",
    "ops": "Ops & Feedback",
    "releases": "What's New",
    "news": "News & Blogs",
}

SECTION_LOOKUP = {}
for _key, _label in SECTION_META.items():
    SECTION_LOOKUP[_key.lower()] = _key
    SECTION_LOOKUP[_label.lower()] = _key

# Seed content - identical to the original in-memory version. Only applied
# once, the first time the database is created.
SEED_ENTRIES = [
    # ── Project Portfolio ── real project inventory (36 tracked initiatives)
    ("projects", "36 initiatives tracked this cycle",
     "25 existing tools, 11 new initiatives. 15 are in active development, "
     "4 newly deployed (ESignTool, ApprovalFlowSync, RFP Tracker, Camera Gatepass).",
     "Active", "Ops Office"),
    ("projects", "ESignTool",
     "Secure digital signature workflows, deployed with high daily usage. "
     "Owned by Sanad / Noufi.",
     "Deployed", "Sanad"),
    ("projects", "ApprovalFlowSync",
     "Multi-party approval orchestration engine, deployed with medium usage. "
     "Owned by Sanad / Noufi.",
     "Deployed", "Sanad"),
    ("projects", "RFP Tracker",
     "Pipeline management for all RFPs, deployed with high usage across the "
     "bid desk. Owned by Sanad / Noufi.",
     "Deployed", "Sanad"),
    ("projects", "Camera Gatepass",
     "Facility access and security monitoring, deployed with high usage "
     "across all sites. Owned by Anirudh / Niya.",
     "Deployed", "Anirudh"),
    ("projects", "AIBidManager",
     "Precision bid comparison and selection against pre-defined templates; "
     "in testing with high projected usage.",
     "Testing", "Sanad"),
    ("projects", "QuoteFast",
     "One-click budgetary RFP quotes; in testing with high projected usage.",
     "Testing", "Sanad"),
    ("projects", "SteelGuard AI",
     "Predictive steel quality assurance tool; in active development, "
     "flagged high priority.",
     "Development", "Sanad"),
    ("projects", "ExecutiveEye",
     "High-level business intelligence and productivity-tracking dashboard; "
     "actively in use.",
     "Active", "Sanad"),

    # ── Competitor Intelligence ── real sourced data (Financials, Job
    # Boards, Gov Tenders, Reviews, Analyst Intel, Digital Footprint,
    # Win/Loss tracker modules)
    ("competitors", "Petrofac Emirates JV in play",
     "Petrofac's UK holding entered administration Oct 2025; its UAE JV, "
     "managing ~$2.87B in ADNOC contracts, is being sold to Mason "
     "Capital/Pearlstone - opening exposure for reallocation across the region.",
     "Risk", "Research Team"),
    ("competitors", "Regional market still expanding",
     "UAE construction market projected to grow from $45.8B (2025) to $69B "
     "by 2034; ADNOC's 2026-2028 capital programme carries roughly $55B in "
     "upcoming work (source: IMARC Group, Oil & Gas Middle East).",
     "Opportunity", "Research Team"),
    ("competitors", "Drake & Scull completes restructuring",
     "AED 4.18B debt written off; DFM trading resumed May 2024, share price "
     "up ~40%. Revenue doubled to AED 223.8M in FY2025 (+116% YoY). Source: "
     "Khaleej Times, AGBI, The National.",
     "Industry", "Research Team"),
    ("competitors", "NPCC leads confirmed contract awards",
     "NPCC holds $4.2B in confirmed awards across 3 contracts (2022-2025), "
     "vs. Technomak's $1.06B across 2 contracts. Worth tracking as a gap in "
     "award volume, not necessarily win rate.",
     "Risk", "Research Team"),
    ("competitors", "Technomak confirmed win: Cap Lopez FLNG",
     "~$1B EPC, commissioning, and integration contract for Dixstone/"
     "Perenco in Gabon. Barge fabricated in Dubai, 700,000 TPA LNG, first "
     "gas targeted 2026. Source: Global Flow Control, LNG Prime.",
     "Opportunity", "Research Team"),
    ("competitors", "Hiring signal: Petrofac freeze vs. our ramp-up",
     "Petrofac Emirates has frozen hiring post-administration, with "
     "postings removed Oct-Nov 2025 - skilled UAE-based EPC talent now "
     "available in market. Meanwhile all 6 of our open roles (Kerala) "
     "point toward the Cap Lopez FLNG ramp-up.",
     "Opportunity", "Research Team"),
    ("competitors", "Employer review volume gap",
     "Technomak has 14 employer reviews on Glassdoor/Indeed vs. Petrofac's "
     "1200+ and NPCC's 420+. Sample size is too small for a reliable "
     "rating - a brand-visibility gap worth addressing.",
     "Pending", "Research Team"),
    ("competitors", "Headcount comparison",
     "Technomak: ~1,500 employees (founded 2004). NPCC: ~7,000+ (1973). "
     "Petrofac: ~5,800 pre-administration (1981). Source: ZoomInfo, "
     "Datanyze, LinkedIn public profiles.",
     "Industry", "Research Team"),

    # ── Marketing & Sales ── real backlog items tagged marketing-related
    ("marketing", "Pipeline update pending",
     "Add this cycle's lead counts and conversion figures from the "
     "marketing dashboard, or import them below.",
     "Pending", "Ops Office"),
    ("marketing", "Marketing / Competitor analysis tool",
     "Market positioning and intelligence tool; in active development, "
     "owned by Anirudh / Niya.",
     "Development", "Anirudh"),
    ("marketing", "Digital marketing / Ads / Leads",
     "Lead-generation and online promotion tooling; in active development, "
     "flagged high priority.",
     "Development", "Anirudh"),

    # ── EA / Systems Integration ── real project data
    ("ea", "ERP integration in testing",
     "Systems Integration ERP (EA) initiative is in testing with medium "
     "projected usage, led by Anirudh and Niya.",
     "Testing", "Anirudh"),
    ("ea", "OT/IT/Cyber Presales Help",
     "Industrial cybersecurity sales-support tooling; in active "
     "development, owned by Anirudh / Niya.",
     "Development", "Anirudh"),

    # ── Team & Leadership ── real content from the original CEO message page
    ("team", "Message from the CEO",
     "Our team is the engine of our innovation. By blending human "
     "expertise with AI-driven operational efficiency, we are scaling new "
     "heights in Industry 4.0.",
     "Leadership", "CEO Office"),
    ("team", "Current composition",
     "12 full-time engineering & strategy leads, 8 specialised interns in "
     "data & AI research.",
     "Headcount", "CEO Office"),

    # ── Ops & Feedback ── no real data source yet, kept as a placeholder
    ("ops", "Survey results pending",
     "Add this cycle's operational survey highlights here, or import them below.",
     "Pending", "Ops Office"),

    # ── What's New ── no real data source yet, kept as a placeholder
    ("releases", "Release notes pending",
     "Add what shipped this cycle across active projects.",
     "Pending", "Ops Office"),

    # ── News & Blogs ── real content from the original page
    ("news", "AI-driven predictive maintenance in manufacturing",
     "Latest industry news relevant to Technomak's manufacturing operations.",
     "Industry", "Comms Team"),
    ("news", "Upcoming: digital twins in modular construction",
     "Draft blog post exploring digital twin adoption in modular "
     "construction workflows.",
     "Draft", "Comms Team"),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(get_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                tag TEXT NOT NULL,
                date TEXT NOT NULL,
                source TEXT NOT NULL,
                publisher TEXT NOT NULL DEFAULT 'Admin'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                origin TEXT NOT NULL,
                added INTEGER NOT NULL,
                skipped INTEGER NOT NULL
            )
        """)
        conn.commit()

        # Migration for databases created before the publisher column existed.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
        if "publisher" not in existing_cols:
            conn.execute("ALTER TABLE entries ADD COLUMN publisher TEXT NOT NULL DEFAULT 'Admin'")
            conn.commit()

        row_count = conn.execute("SELECT COUNT(*) AS c FROM entries").fetchone()["c"]
        if row_count == 0:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            conn.executemany(
                "INSERT INTO entries (section, title, body, tag, date, source, publisher) "
                "VALUES (?, ?, ?, ?, ?, 'seed', ?)",
                [(s, t, b, tag, today, pub) for (s, t, b, tag, pub) in SEED_ENTRIES],
            )
            conn.commit()
            print(f"Database created at {DB_PATH} and seeded with "
                  f"{len(SEED_ENTRIES)} starting entries.")


def resolve_section(raw):
    if not raw:
        return None
    return SECTION_LOOKUP.get(str(raw).strip().lower())


def add_entry(section_key, title, body, source, tag="New", publisher="Admin",
              image=None):
    title = (title or "").strip() or "(untitled)"
    body = (body or "").strip()
    publisher = (publisher or "").strip() or "Admin"
    if not body or section_key not in SECTION_META:
        return False
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO entries (section, title, body, tag, date, source, "
            "publisher, image) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (section_key, title, body, tag, today, source, publisher,
             (image or "").strip() or None),
        )
        conn.commit()
    return True


def get_entry_raw(entry_id):
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT id, section, title, body, tag, date, source, publisher, image "
            "FROM entries WHERE id = ?", (entry_id,),
        ).fetchone()
    return dict(row) if row else None


def update_entry(entry_id, title=None, body=None, tag=None, publisher=None, image=None):
    """Partial update - only fields explicitly passed (not None) are changed.
    Pass image="" to explicitly clear an existing thumbnail."""
    existing = get_entry_raw(entry_id)
    if not existing:
        return False
    new_title = (title if title is not None else existing["title"]).strip() or "(untitled)"
    new_body = (body if body is not None else existing["body"]).strip()
    new_tag = (tag if tag is not None else existing["tag"]).strip() or existing["tag"]
    new_publisher = (publisher if publisher is not None else existing["publisher"]).strip() or "Admin"
    new_image = existing["image"] if image is None else ((image or "").strip() or None)
    if not new_body:
        return False
    with closing(get_db()) as conn:
        conn.execute(
            "UPDATE entries SET title = ?, body = ?, tag = ?, publisher = ?, image = ? "
            "WHERE id = ?",
            (new_title, new_body, new_tag, new_publisher, new_image, entry_id),
        )
        conn.commit()
    return True


def delete_entry(entry_id):
    with closing(get_db()) as conn:
        cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.commit()
    return cur.rowcount > 0


def get_sections():
    """Everything the public digest page needs: {key: {label, entries}}."""
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, section, title, body, tag, date, source, publisher, image FROM entries ORDER BY id DESC"
        ).fetchall()
    result = {key: {"label": label, "entries": []} for key, label in SECTION_META.items()}
    for row in rows:
        if row["section"] in result:
            result[row["section"]]["entries"].append({
                "id": row["id"], "title": row["title"], "body": row["body"],
                "tag": row["tag"], "date": row["date"], "source": row["source"],
                "publisher": row["publisher"], "image": row["image"],
            })
    return result


def get_entry_by_id(entry_id):
    """A single entry plus its section info, for the detail page."""
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT id, section, title, body, tag, date, source, publisher, "
            "image FROM entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"], "section": row["section"],
        "section_label": SECTION_META.get(row["section"], row["section"]),
        "title": row["title"], "body": row["body"], "tag": row["tag"],
        "date": row["date"], "source": row["source"], "publisher": row["publisher"],
        "image": row["image"],
    }


def get_section_entries(section_key):
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, title, body, tag, date, source, publisher, image "
            "FROM entries WHERE section = ? ORDER BY id DESC",
            (section_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def log_import(kind, origin, added, skipped):
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO import_log (ts, kind, origin, added, skipped) VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), kind, origin, added, skipped),
        )
        conn.commit()


def get_import_log():
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT ts AS when_, kind, origin, added, skipped FROM import_log ORDER BY id DESC"
        ).fetchall()
    return [
        {"when": row["when_"], "kind": row["kind"], "origin": row["origin"],
         "added": row["added"], "skipped": row["skipped"]}
        for row in rows
    ]


def ingest_rows(rows, source_label, default_publisher="Import"):
    """rows: iterable of dicts with keys section/title/body/publisher (case-insensitive).
    'publisher' is optional per row - falls back to default_publisher if absent."""
    added, skipped = 0, 0
    for row in rows:
        norm = {str(k).strip().lower(): v for k, v in row.items()}
        section_key = resolve_section(norm.get("section"))
        title = norm.get("title")
        body = norm.get("body")
        publisher = norm.get("publisher") or default_publisher
        if section_key and (title or body) and add_entry(section_key, title, body, source_label, publisher=publisher):
            added += 1
        else:
            skipped += 1
    return added, skipped


def ingest_json(payload, source_label):
    added, skipped = 0, 0
    if isinstance(payload, list):
        added, skipped = ingest_rows(payload, source_label)
    elif isinstance(payload, dict):
        for raw_key, items in payload.items():
            section_key = resolve_section(raw_key)
            if not section_key or not isinstance(items, list):
                skipped += len(items) if isinstance(items, list) else 1
                continue
            for item in items:
                title = item.get("title") if isinstance(item, dict) else None
                body = item.get("body") if isinstance(item, dict) else None
                publisher = (item.get("publisher") if isinstance(item, dict) else None) or "Import"
                if add_entry(section_key, title, body, source_label, publisher=publisher):
                    added += 1
                else:
                    skipped += 1
    return added, skipped


init_db()

# ---------------------------------------------------------------------------
# Design tokens + legacy server-rendered pages (kept as a fallback if you
# open the Flask app directly without running the React frontend).
# ---------------------------------------------------------------------------

BASE_STYLE = """
:root{
  --bg:#f7f9fb; --panel:#ffffff; --panel-2:#f1f5f8; --line:#e2e8ee;
  --ink:#1c1f24; --ink-soft:#4a5058; --ink-dim:#8c939c;
  --brass:#1787ac; --brass-dim:#145f76;
  --teal:#0f8f6e; --teal-bg:rgba(15,143,110,0.10);
  --amber:#b26a12; --amber-bg:rgba(178,106,18,0.10);
  --red:#c0453a; --red-bg:rgba(192,69,58,0.08);
  --radius:10px;
}
*{box-sizing:border-box;}
html{scroll-behavior:smooth;}
body{margin:0;background:var(--bg);
  color:var(--ink); font-family:'Inter', system-ui, sans-serif;}
h1,h2,h3,.mono,.tag,nav a,.brand,button,label{font-family:'Space Grotesk', sans-serif;}
a{color:var(--brass); text-decoration:none;}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px 100px;}
nav.topbar{position:sticky;top:0;z-index:50;background:rgba(255,255,255,0.92);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--line);}
.topbar-inner{max-width:1080px;margin:0 auto;padding:16px 24px;
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;}
.brand{font-weight:700;font-size:18px;letter-spacing:0.01em;}
.brand em{font-style:normal;color:var(--brass);}
.navlinks{display:flex;gap:20px;flex-wrap:wrap;}
.navlinks a{color:var(--ink-soft);font-size:13px;font-weight:600;}
.navlinks a:hover{color:var(--ink);}
.login-btn{background:var(--brass);color:#fff;padding:8px 16px;border-radius:6px;
  font-size:13px;font-weight:700;}
.login-btn:hover{background:var(--brass-dim);}
.hero{padding:56px 0 40px;}
.hero h1{font-size:34px;margin:0 0 10px;letter-spacing:-0.01em;}
.hero p{color:var(--ink-soft);max-width:640px;line-height:1.6;margin:0;}
.stat-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;margin-top:32px;}
.stat-strip div{background:var(--panel);padding:18px 16px;}
.stat-num{font-size:28px;font-weight:700;color:var(--brass);}
.stat-lbl{font-size:12px;color:var(--ink-dim);margin-top:4px;}
section.module{margin-top:48px; scroll-margin-top:80px;}
.mod-head{display:flex;justify-content:space-between;align-items:baseline;
  border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:18px;}
.mod-title{font-size:19px;font-weight:700;margin:0;}
.mod-count{font-size:12px;color:var(--ink-dim);}
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:18px 20px;transition:border-color 0.15s, transform 0.15s;
  box-shadow:0 1px 2px rgba(20,30,40,0.04);}
.card:hover{border-color:var(--brass);}
.card h4{margin:0 0 8px;font-size:15px;font-weight:600;}
.card p{margin:0;font-size:13.5px;color:var(--ink-soft);line-height:1.55;}
.card-meta{display:flex;justify-content:space-between;align-items:center;margin-top:14px;}
.tag{display:inline-block;font-size:10.5px;font-weight:700;padding:3px 9px;border-radius:20px;
  text-transform:uppercase;letter-spacing:0.04em;}
.tag.Active,.tag.Opportunity,.tag.Leadership{background:var(--teal-bg);color:var(--teal);}
.tag.Testing,.tag.Headcount,.tag.Draft,.tag.Industry,.tag.New{background:var(--amber-bg);color:var(--amber);}
.tag.Risk{background:var(--red-bg);color:var(--red);}
.tag.Pending{background:rgba(140,147,156,0.12);color:var(--ink-soft);}
.date{font-size:11px;color:var(--ink-dim);}
.src-badge{font-size:10px;color:var(--ink-dim);border:1px solid var(--line);
  border-radius:4px;padding:1px 6px;margin-left:6px;}
footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--line);
  font-size:12px;color:var(--ink-dim);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;}
.admin-shell{max-width:760px;margin:0 auto;padding:60px 24px 100px;}
.admin-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:32px;
  box-shadow:0 2px 10px rgba(20,30,40,0.05);}
.admin-card h2{margin-top:0;}
.top-links{display:flex;justify-content:space-between;font-size:13px;margin-bottom:24px;color:var(--ink-soft);}
.tabs{display:flex;gap:6px;border-bottom:1px solid var(--line);margin-bottom:22px;flex-wrap:wrap;}
.tab-btn{background:none;border:none;color:var(--ink-soft);padding:10px 16px;font-size:13px;
  font-weight:600;cursor:pointer;border-radius:6px 6px 0 0;}
.tab-btn.active{background:var(--panel-2);color:var(--brass);}
.tab-pane{display:none;}
.tab-pane.active{display:block;}
.form-group{margin-bottom:16px;}
label{display:block;font-size:12px;font-weight:600;color:var(--ink-soft);margin-bottom:6px;
  text-transform:uppercase;letter-spacing:0.03em;}
select,textarea,input[type=text],input[type=password],input[type=url]{
  width:100%;padding:11px 12px;background:#fff;border:1px solid var(--line);
  border-radius:6px;color:var(--ink);font-size:14px;font-family:inherit;}
textarea{min-height:90px;resize:vertical;}
input[type=file]{width:100%;color:var(--ink-soft);font-size:13px;}
button{background:var(--brass);color:#fff;border:none;padding:11px 20px;
  font-size:13px;font-weight:700;border-radius:6px;cursor:pointer;}
button:hover{background:var(--brass-dim);}
.hint{font-size:12px;color:var(--ink-dim);margin-top:6px;line-height:1.5;}
.error{background:var(--red-bg);color:var(--red);padding:10px 14px;border-radius:6px;font-size:13px;margin-bottom:16px;}
.output{margin-top:16px;background:var(--panel-2);padding:12px 14px;border-left:3px solid var(--brass);
  border-radius:6px;font-family:monospace;font-size:12px;white-space:pre-wrap;display:none;max-height:220px;overflow:auto;color:var(--ink);}
table.log{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:10px;}
table.log th,table.log td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);color:var(--ink-soft);}
table.log th{color:var(--ink-dim);font-weight:600;text-transform:uppercase;font-size:10.5px;}
"""

FONT_LINKS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
"""

PUBLIC_TEMPLATE = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Technomak Digest</title>""" + FONT_LINKS + """<style>""" + BASE_STYLE + """</style></head>
<body>
<nav class="topbar"><div class="topbar-inner">
  <div class="brand">technomak<em>.</em>digest</div>
  <div class="navlinks">
    {% for key, sec in sections.items() %}<a href="#{{ key }}">{{ sec.label }}</a>{% endfor %}
  </div>
  <a href="{{ url_for('login') }}" class="login-btn">Admin</a>
</div></nav>
<div class="wrap">
  <div class="hero">
    <h1>Executive digest</h1>
    <p>A live working summary of projects, market intelligence, and people - updated by the team, pulled from spreadsheets, or imported from a live feed.</p>
    <div class="stat-strip">
      <div><div class="stat-num">{{ total_entries }}</div><div class="stat-lbl">Total updates on record</div></div>
      <div><div class="stat-num">{{ sections|length }}</div><div class="stat-lbl">Tracked sections</div></div>
      <div><div class="stat-num">{{ imported_count }}</div><div class="stat-lbl">Imported via upload/URL</div></div>
      <div><div class="stat-num">{{ today }}</div><div class="stat-lbl">Last generated</div></div>
    </div>
  </div>
  {% for key, sec in sections.items() %}
  <section class="module" id="{{ key }}">
    <div class="mod-head">
      <h2 class="mod-title">{{ sec.label }}</h2>
      <span class="mod-count">{{ sec.entries|length }} update{{ 's' if sec.entries|length != 1 else '' }}</span>
    </div>
    <div class="card-grid">
      {% for entry in sec.entries[:6] %}
      <div class="card">
        <h4>{{ entry.title }}</h4>
        <p>{{ entry.body }}</p>
        <div class="card-meta">
          <span class="tag {{ entry.tag }}">{{ entry.tag }}</span>
          <span class="date">{{ entry.date }}<span class="src-badge">{{ entry.source }}</span></span>
        </div>
      </div>
      {% endfor %}
    </div>
  </section>
  {% endfor %}
  <footer>
    <span>Technomak internal digest &middot; confidential, not for external distribution</span>
    <span><a href="{{ url_for('login') }}">Admin console</a></span>
  </footer>
</div>
</body></html>
"""

LOGIN_TEMPLATE = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Admin Login</title>""" + FONT_LINKS + """<style>""" + BASE_STYLE + """</style></head>
<body><div class="admin-shell"><div class="admin-card">
  <h2>Admin Login</h2>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST">
    <div class="form-group"><label>Username</label>
      <input type="text" name="username" autocomplete="off" required></div>
    <div class="form-group"><label>Password</label>
      <input type="password" name="password" required></div>
    <button type="submit">Sign in</button>
  </form>
  <p style="margin-top:18px;font-size:13px;color:var(--ink-soft)">
    <a href="{{ url_for('public_landing') }}">&larr; Back to digest</a></p>
</div></div></body></html>
"""

ADMIN_TEMPLATE = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Admin Console</title>""" + FONT_LINKS + """<style>""" + BASE_STYLE + """</style></head>
<body><div class="admin-shell"><div class="admin-card">
  <div class="top-links">
    <a href="{{ url_for('public_landing') }}">&larr; View digest</a>
    <a href="{{ url_for('logout') }}">Sign out</a>
  </div>
  <h2>Admin console</h2>
  <div class="tabs">
    <button class="tab-btn active" data-tab="publishTab">Publish update</button>
    <button class="tab-btn" data-tab="excelTab">Upload files</button>
    <button class="tab-btn" data-tab="urlTab">Import from URL</button>
    <button class="tab-btn" data-tab="aiTab">AI tools</button>
    <button class="tab-btn" data-tab="aiAgentTab">AI Agent</button>
    <button class="tab-btn" data-tab="manageTab">Manage entries</button>
    <button class="tab-btn" data-tab="historyTab">History &amp; Reset</button>
    <button class="tab-btn" data-tab="logTab">Import log</button>
  </div>
  <div id="publishTab" class="tab-pane active">
    <form id="publishForm">
      <div class="form-group"><label>Section</label>
        <select id="section">
          {% for key, sec in sections.items() %}<option value="{{ key }}">{{ sec.label }}</option>{% endfor %}
        </select></div>
      <div class="form-group"><label>Title</label><input type="text" id="title" required></div>
      <div class="form-group"><label>Body</label><textarea id="body" required></textarea></div>
      <div class="form-group"><label>Thumbnail (optional)</label>
        <input type="file" id="publishImage" accept="image/*">
        <p class="hint">JPG, PNG, WEBP or GIF, up to 8MB.</p></div>
      <button type="submit">Publish</button>
    </form>
    <div id="publishOutput" class="output"></div>
  </div>
  <div id="excelTab" class="tab-pane">
    <form id="excelForm" enctype="multipart/form-data">
      <div class="form-group"><label>File</label>
        <input type="file" id="excelFile" name="file"
          accept=".xlsx,.csv,.json,.pdf,.docx,.txt,.md,.markdown,.html,.htm,.log,.rtf" required></div>
      <div class="form-group"><label>Section (used for documents without their own section column, and as the default when drafting from unstructured files)</label>
        <select id="excelSection">
          <option value="">Auto-detect</option>
          {% for key, sec in sections.items() %}<option value="{{ key }}">{{ sec.label }}</option>{% endfor %}
        </select></div>
      <p class="hint">Excel, CSV and JSON with <b>section, title, body</b> columns import straight in.
        PDF, Word, text, Markdown and HTML are read and drafted for review first.
        <a href="{{ url_for('download_template') }}">Download a spreadsheet template &rarr;</a></p>
      <button type="submit">Upload &amp; import</button>
    </form>
    <div id="excelOutput" class="output"></div>
    <div id="excelReview"></div>
  </div>
  <div id="urlTab" class="tab-pane">
    <form id="urlForm">
      <div class="form-group"><label>Source URL</label>
        <input type="url" id="sourceUrl" placeholder="https://..." required></div>
      <p class="hint">Works with a published Google Sheet CSV link or a JSON API endpoint.</p>
      <button type="submit">Fetch &amp; import</button>
    </form>
    <div id="urlOutput" class="output"></div>
  </div>
  <div id="aiTab" class="tab-pane">
    <h3 style="margin:0 0 6px;font-size:15px;">Executive summary</h3>
    <p class="hint">Reads every update in the digest and writes a short synthesis for the top of the public page.</p>
    <div style="display:flex;gap:10px;margin-bottom:14px;">
      <button id="genSummaryBtn" type="button">Generate draft</button>
      <button id="genPublishSummaryBtn" type="button">Generate &amp; publish</button>
    </div>
    <div id="summaryOutput" class="output"></div>

    <hr style="margin:24px 0;border:none;border-top:1px solid #dfe3e8;">

    <h3 style="margin:0 0 6px;font-size:15px;">AI newsletter creator</h3>
    <p class="hint">Choose a section, paste rough notes, and it drafts (or rewrites, with an AI key configured) entries ready to review and publish.</p>
    <div class="form-group"><label>Section</label>
      <select id="aiSection">
        {% for key, sec in sections.items() %}<option value="{{ key }}">{{ sec.label }}</option>{% endfor %}
      </select></div>
    <div class="form-group"><label>Output</label>
      <select id="aiStyle">
        <option value="multiple">Separate entries</option>
        <option value="single">One entry</option>
      </select></div>
    <div class="form-group"><label>Your notes</label>
      <textarea id="aiText" rows="6" placeholder="Paste rough notes - fragments, shorthand, bullet points..."></textarea></div>
    <button id="aiDraftBtn" type="button">Draft entries</button>
    <div id="aiDraftOutput" class="output"></div>
    <div id="aiDraftReview"></div>
  </div>

  <div id="aiAgentTab" class="tab-pane">
    <h3 style="margin:0 0 6px;font-size:15px;">AI research agent</h3>
    <p class="hint">Picks or sharpens a topic, searches the web, checks what this section already says,
      drafts one entry, and fact-checks it against the sources before you review it.
      Needs an LLM key and TAVILY_API_KEY.</p>
    <div class="form-group"><label>Topic</label>
      <input type="text" id="agentTopic" placeholder="leave blank to let the agent pick"></div>
    <div class="form-group"><label>Section</label>
      <select id="agentSection">
        {% for key, sec in sections.items() %}<option value="{{ key }}">{{ sec.label }}</option>{% endfor %}
      </select></div>
    <button id="agentRunBtn" type="button">Run agent</button>
    <div id="agentOutput" class="output"></div>
    <div id="agentSources"></div>
    <div id="agentReview"></div>
    <div id="agentFeedbackBox" style="display:none;margin-top:14px;">
      <div class="form-group"><label>Request changes</label>
        <textarea id="agentFeedback" rows="3" placeholder="e.g. Focus on the UAE angle, drop the second sentence..."></textarea></div>
      <button id="agentFeedbackBtn" type="button">Request changes</button>
    </div>
  </div>

  <div id="manageTab" class="tab-pane">
    <h3 style="margin:0 0 6px;font-size:15px;">Manage entries</h3>
    <p class="hint">Edit or delete anything already published - title, body, tag,
      publisher, and thumbnail. Changes save immediately.</p>
    <div class="form-group"><label>Filter by section</label>
      <select id="manageFilterSection"><option value="">All sections</option></select></div>
    <div id="manageListArea" class="hint">Loading entries…</div>
  </div>

  <div id="historyTab" class="tab-pane">
    <h3 style="margin:0 0 6px;font-size:15px;">Archive everything &amp; start fresh</h3>
    <p class="hint">Moves every entry, in every section, into a saved snapshot you can browse
      later - then clears the board completely so you can start publishing new content
      from a clean slate. This cannot be undone from here, so double-check first.</p>
    <div class="form-group"><label>Label this edition</label>
      <input type="text" id="archiveLabel" placeholder="e.g. September 2026 Edition"></div>
    <button id="archiveAllBtn" type="button">Archive everything &amp; clear the board</button>
    <div id="archiveAllOutput" class="output"></div>

    <hr style="margin:24px 0;border:none;border-top:1px solid #dfe3e8;">

    <h3 style="margin:0 0 6px;font-size:15px;">Past editions</h3>
    <div id="archiveHistoryArea" class="hint">Loading past editions…</div>
  </div>

  <div id="logTab" class="tab-pane">
    <table class="log">
      <tr><th>When</th><th>Type</th><th>Source</th><th>Added</th><th>Skipped</th></tr>
      {% for row in log %}
      <tr><td>{{ row.when }}</td><td>{{ row.kind }}</td><td>{{ row.origin }}</td><td>{{ row.added }}</td><td>{{ row.skipped }}</td></tr>
      {% else %}
      <tr><td colspan="5">No imports yet.</td></tr>
      {% endfor %}
    </table>
  </div>
</div></div>
<script>
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});
function showOutput(el, obj) { el.style.display = 'block'; el.textContent = JSON.stringify(obj, null, 2); }
async function uploadImageFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/admin/upload-image', { method: 'POST', body: fd });
  const result = await res.json();
  if (!res.ok) throw new Error(result.error || 'Image upload failed');
  return result.image;
}

document.getElementById('publishForm').addEventListener('submit', async function(e){
  e.preventDefault();
  const section = document.getElementById('section').value;
  const payload = { title: document.getElementById('title').value, body: document.getElementById('body').value };
  const imageFile = document.getElementById('publishImage').files[0];
  if (imageFile) {
    try {
      payload.image = await uploadImageFile(imageFile);
    } catch (err) {
      showOutput(document.getElementById('publishOutput'), { error: err.message });
      return;
    }
  }
  const res = await fetch('/api/v1/' + section, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  const result = await res.json();
  showOutput(document.getElementById('publishOutput'), result);
  if (res.ok) { document.getElementById('title').value=''; document.getElementById('body').value=''; document.getElementById('publishImage').value=''; }
});
document.getElementById('excelForm').addEventListener('submit', async function(e){
  e.preventDefault();
  const fd = new FormData();
  fd.append('file', document.getElementById('excelFile').files[0]);
  const section = document.getElementById('excelSection').value;
  if (section) fd.append('section', section);
  const out = document.getElementById('excelOutput');
  const review = document.getElementById('excelReview');
  review.innerHTML = '';
  out.style.display = 'block';
  out.textContent = 'Reading...';
  const res = await fetch('/admin/import/file', { method: 'POST', body: fd });
  const result = await res.json();
  if (!res.ok) { out.textContent = 'Error: ' + (result.error || 'unknown'); return; }

  if (result.kind === 'imported') {
    out.textContent = 'Imported ' + result.added + ' row(s), skipped ' + result.skipped + '.';
    return;
  }
  // kind === 'drafted': unstructured file, needs review before publishing.
  out.textContent = (result.ai_enabled ? 'AI mode - ' : 'Rule-based mode (set GROQ_API_KEY for AI drafting) - ') +
    'read ' + result.chars_extracted + ' characters, drafted ' + result.proposed.length +
    ' entr' + (result.proposed.length===1?'y':'ies') + ' from "' + result.filename + '". Review below.';

  const items = result.proposed.map(p => Object.assign({include:true}, p));
  function renderFileReview() {
    review.innerHTML = '<h4 style="margin:16px 0 8px;font-size:13px;">Review &amp; publish</h4>' +
      items.map((p, i) => `
        <div style="border:1px solid #dfe3e8;padding:10px;margin-bottom:8px;">
          <label style="display:flex;gap:8px;align-items:flex-start;">
            <input type="checkbox" data-i="${i}" class="fincl" ${p.include ? 'checked' : ''} style="margin-top:4px;">
            <span style="flex:1;">
              <div style="font-size:11px;color:#1787ac;text-transform:uppercase;font-weight:700;margin-bottom:4px;">${p.tag} &middot; ${p.section}</div>
              <input data-i="${i}" class="fedit-title" value="${p.title.replace(/"/g,'&quot;')}" style="width:100%;font-weight:700;border:none;border-bottom:1px solid #dfe3e8;margin-bottom:6px;padding:2px 0;">
              <textarea data-i="${i}" class="fedit-body" rows="2" style="width:100%;border:none;border-bottom:1px solid #dfe3e8;font-size:12px;">${p.body}</textarea>
            </span>
          </label>
        </div>`).join('') +
      '<button id="publishFileDraftsBtn" type="button">Publish selected</button>';

    review.querySelectorAll('.fincl').forEach(el => el.addEventListener('change', e => { items[+e.target.dataset.i].include = e.target.checked; }));
    review.querySelectorAll('.fedit-title').forEach(el => el.addEventListener('input', e => { items[+e.target.dataset.i].title = e.target.value; }));
    review.querySelectorAll('.fedit-body').forEach(el => el.addEventListener('input', e => { items[+e.target.dataset.i].body = e.target.value; }));
    document.getElementById('publishFileDraftsBtn').addEventListener('click', async () => {
      const chosen = items.filter(p => p.include).map(({include, ...rest}) => rest);
      if (chosen.length === 0) { alert('Select at least one entry.'); return; }
      const pubRes = await fetch('/admin/ai/publish-batch', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ entries: chosen })
      });
      const pubResult = await pubRes.json();
      if (pubRes.ok) {
        review.innerHTML = '<p class="hint">Published ' + pubResult.added + ' entr' + (pubResult.added===1?'y':'ies') + '.</p>';
      } else {
        alert('Error: ' + (pubResult.error || 'unknown'));
      }
    });
  }
  renderFileReview();
});
document.getElementById('urlForm').addEventListener('submit', async function(e){
  e.preventDefault();
  const url = document.getElementById('sourceUrl').value;
  const res = await fetch('/admin/import/url', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url}) });
  showOutput(document.getElementById('urlOutput'), await res.json());
});

// --- AI tools ---
async function generateSummary(publish) {
  const out = document.getElementById('summaryOutput');
  out.style.display = 'block';
  out.textContent = 'Working...';
  const res = await fetch('/admin/ai/summary', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({publish})
  });
  const result = await res.json();
  if (res.ok) {
    const s = result.summary;
    out.textContent = (publish ? 'Published. ' : 'Draft only. ') +
      (result.ai_enabled ? '(AI mode) ' : '(rule-based mode - set GROQ_API_KEY for AI-written summaries) ') +
      '\\n\\n' + s.content;
  } else {
    out.textContent = 'Error: ' + (result.error || 'unknown');
  }
}
document.getElementById('genSummaryBtn').addEventListener('click', () => generateSummary(false));
document.getElementById('genPublishSummaryBtn').addEventListener('click', () => generateSummary(true));

document.getElementById('aiDraftBtn').addEventListener('click', async function(){
  const section = document.getElementById('aiSection').value;
  const style = document.getElementById('aiStyle').value;
  const text = document.getElementById('aiText').value;
  const out = document.getElementById('aiDraftOutput');
  const review = document.getElementById('aiDraftReview');
  review.innerHTML = '';
  if (text.trim().length < 10) { out.style.display='block'; out.textContent = 'Paste at least a few sentences first.'; return; }
  out.style.display = 'block';
  out.textContent = 'Drafting...';
  const res = await fetch('/admin/ai/create', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ text, section, style })
  });
  const result = await res.json();
  if (!res.ok) { out.textContent = 'Error: ' + (result.error || 'unknown'); return; }
  out.textContent = (result.ai_enabled ? 'AI mode - ' : 'Rule-based mode (set GROQ_API_KEY for AI rewriting) - ') +
    result.proposed.length + ' entr' + (result.proposed.length===1?'y':'ies') + ' drafted. Review below, then publish.';

  const items = result.proposed.map((p, i) => Object.assign({include:true}, p));
  function renderReview() {
    review.innerHTML = '<h4 style="margin:16px 0 8px;font-size:13px;">Review &amp; publish</h4>' +
      items.map((p, i) => `
        <div style="border:1px solid #dfe3e8;padding:10px;margin-bottom:8px;">
          <label style="display:flex;gap:8px;align-items:flex-start;">
            <input type="checkbox" data-i="${i}" class="incl" ${p.include ? 'checked' : ''} style="margin-top:4px;">
            <span style="flex:1;">
              <div style="font-size:11px;color:#1787ac;text-transform:uppercase;font-weight:700;margin-bottom:4px;">${p.tag}</div>
              <input data-i="${i}" class="edit-title" value="${p.title.replace(/"/g,'&quot;')}" style="width:100%;font-weight:700;border:none;border-bottom:1px solid #dfe3e8;margin-bottom:6px;padding:2px 0;">
              <textarea data-i="${i}" class="edit-body" rows="2" style="width:100%;border:none;border-bottom:1px solid #dfe3e8;font-size:12px;">${p.body}</textarea>
            </span>
          </label>
        </div>`).join('') +
      '<button id="publishDraftsBtn" type="button">Publish selected</button>';

    review.querySelectorAll('.incl').forEach(el => el.addEventListener('change', e => {
      items[+e.target.dataset.i].include = e.target.checked;
    }));
    review.querySelectorAll('.edit-title').forEach(el => el.addEventListener('input', e => {
      items[+e.target.dataset.i].title = e.target.value;
    }));
    review.querySelectorAll('.edit-body').forEach(el => el.addEventListener('input', e => {
      items[+e.target.dataset.i].body = e.target.value;
    }));
    document.getElementById('publishDraftsBtn').addEventListener('click', async () => {
      const chosen = items.filter(p => p.include).map(({include, ...rest}) => rest);
      if (chosen.length === 0) { alert('Select at least one entry.'); return; }
      const pubRes = await fetch('/admin/ai/publish-batch', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ entries: chosen })
      });
      const pubResult = await pubRes.json();
      if (pubRes.ok) {
        review.innerHTML = '<p class="hint">Published ' + pubResult.added + ' entr' + (pubResult.added===1?'y':'ies') + '.</p>';
        document.getElementById('aiText').value = '';
      } else {
        alert('Error: ' + (pubResult.error || 'unknown'));
      }
    });
  }
  renderReview();
});

// ---- AI Agent tab -------------------------------------------------------
// Sources and drafts come from the open web, so everything is escaped.

const AGENT_ESC = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
function agentEsc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, ch => AGENT_ESC[ch]); }
let agentRunId = null;
let agentItems = [];

function agentBusy(on, msg) {
  document.getElementById('agentRunBtn').disabled = on;
  document.getElementById('agentFeedbackBtn').disabled = on;
  const out = document.getElementById('agentOutput');
  out.style.display = 'block';
  if (msg) out.textContent = msg;
}

function renderAgentResult(result) {
  agentRunId = result.run_id;
  const out = document.getElementById('agentOutput');
  const lines = ['Draft ready for review - topic: ' + (result.topic || '(given)') +
    ' - ' + result.revision_count + ' self-check revision' + (result.revision_count === 1 ? '' : 's') + '.'];
  if (result.search_queries && result.search_queries.length) lines.push('Searched: ' + result.search_queries.join(' | '));
  (result.warnings || []).forEach(w => lines.push('Warning: ' + w));
  out.textContent = lines.join('\\n');
  renderAgentSources(result.sources);
  agentItems = result.proposed.map(p => Object.assign({include:true}, p));
  renderAgentReview();
  document.getElementById('agentFeedbackBox').style.display = 'block';
}

function renderAgentSources(sources) {
  const box = document.getElementById('agentSources');
  if (!sources || !sources.length) { box.innerHTML = ''; return; }
  box.innerHTML = '<h4 style="margin:16px 0 8px;font-size:13px;">Sources found (' + sources.length + ')</h4>' +
    '<ol style="margin:0;padding-left:20px;font-size:12.5px;line-height:1.6;">' +
    sources.map(s => {
      const safeUrl = /^https?:\\/\\//i.test(s.url) ? agentEsc(s.url) : '#';
      return `<li><a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${agentEsc(s.title)}</a></li>`;
    }).join('') + '</ol>';
}

function renderAgentReview() {
  const review = document.getElementById('agentReview');
  review.innerHTML = '<h4 style="margin:16px 0 8px;font-size:13px;">Review &amp; publish</h4>' +
    agentItems.map((p, i) => `
      <div style="border:1px solid #dfe3e8;padding:10px;margin-bottom:8px;">
        <label style="display:flex;gap:8px;align-items:flex-start;">
          <input type="checkbox" data-i="${i}" class="ag-incl" ${p.include ? 'checked' : ''} style="margin-top:4px;">
          <span style="flex:1;">
            <div style="font-size:11px;color:#1787ac;text-transform:uppercase;font-weight:700;margin-bottom:4px;">${agentEsc(p.tag)}</div>
            <input data-i="${i}" class="ag-edit-title" value="${agentEsc(p.title)}" style="width:100%;font-weight:700;border:none;border-bottom:1px solid #dfe3e8;margin-bottom:6px;padding:2px 0;">
            <textarea data-i="${i}" class="ag-edit-body" rows="4" style="width:100%;border:none;border-bottom:1px solid #dfe3e8;font-size:12px;">${agentEsc(p.body)}</textarea>
          </span>
        </label>
      </div>`).join('') +
    '<button id="agentPublishBtn" type="button">Publish selected</button>';

  review.querySelectorAll('.ag-incl').forEach(el => el.addEventListener('change', e => {
    agentItems[+e.target.dataset.i].include = e.target.checked;
  }));
  review.querySelectorAll('.ag-edit-title').forEach(el => el.addEventListener('input', e => {
    agentItems[+e.target.dataset.i].title = e.target.value;
  }));
  review.querySelectorAll('.ag-edit-body').forEach(el => el.addEventListener('input', e => {
    agentItems[+e.target.dataset.i].body = e.target.value;
  }));
  document.getElementById('agentPublishBtn').addEventListener('click', async () => {
    const chosen = agentItems.filter(p => p.include).map(({include, ...rest}) => rest);
    if (chosen.length === 0) { alert('Select at least one entry.'); return; }
    const pubRes = await fetch('/admin/ai/publish-batch', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ entries: chosen, run_id: agentRunId })
    });
    const pubResult = await pubRes.json();
    if (pubRes.ok) {
      review.innerHTML = '<p class="hint">Published ' + pubResult.added + ' entr' + (pubResult.added===1?'y':'ies') + '.</p>';
      document.getElementById('agentFeedbackBox').style.display = 'none';
      document.getElementById('agentFeedback').value = '';
      agentRunId = null;
      loadManageEntries();
    } else {
      alert('Error: ' + (pubResult.error || 'unknown'));
    }
  });
}

async function agentPost(url, payload) {
  try {
    const res = await fetch(url, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const result = await res.json();
    return { ok: res.ok, result };
  } catch (err) {
    return { ok: false, result: { error: 'Request failed: ' + err.message } };
  }
}

function showAgentError(result) {
  const out = document.getElementById('agentOutput');
  const warns = (result.warnings || []).map(w => '\\nWarning: ' + w).join('');
  out.textContent = 'Error: ' + (result.error || 'unknown') + warns;
  renderAgentSources(result.sources);
}

document.getElementById('agentRunBtn').addEventListener('click', async function(){
  document.getElementById('agentReview').innerHTML = '';
  document.getElementById('agentSources').innerHTML = '';
  document.getElementById('agentFeedbackBox').style.display = 'none';
  agentBusy(true, 'Running: 1 decide topic, 2 research, 3 gather internal context, 4 draft, 5 self-check, 6 structure output... this can take 1-3 minutes on a free Groq plan.');
  const { ok, result } = await agentPost('/admin/ai/agent-create', {
    section: document.getElementById('agentSection').value,
    topic: document.getElementById('agentTopic').value
  });
  agentBusy(false);
  if (ok) renderAgentResult(result); else showAgentError(result);
});

document.getElementById('agentFeedbackBtn').addEventListener('click', async function(){
  const feedback = document.getElementById('agentFeedback').value.trim();
  if (!feedback) { alert('Write what should change first.'); return; }
  if (!agentRunId) { alert('Run the agent first.'); return; }
  const current = agentItems[0] || {};
  agentBusy(true, 'Revising: 4 draft, 5 self-check, 6 structure output...');
  const { ok, result } = await agentPost('/admin/ai/agent-feedback', {
    run_id: agentRunId, human_feedback: feedback, title: current.title, body: current.body
  });
  agentBusy(false);
  if (ok) { document.getElementById('agentFeedback').value = ''; renderAgentResult(result); }
  else { document.getElementById('agentOutput').textContent = 'Error: ' + (result.error || 'unknown'); }
});

// ---- Manage entries tab -------------------------------------------------

const TAG_OPTIONS = ["New","Active","Testing","Pending","Risk","Opportunity",
  "Leadership","Headcount","Draft","Industry","Development"];
let manageEntries = [];

async function loadManageEntries() {
  const res = await fetch('/api/v1/sections');
  const data = await res.json();
  const sectionSelect = document.getElementById('manageFilterSection');
  if (sectionSelect.options.length <= 1) {
    Object.entries(data).forEach(([key, sec]) => {
      const opt = document.createElement('option');
      opt.value = key; opt.textContent = sec.label;
      sectionSelect.appendChild(opt);
    });
  }
  manageEntries = [];
  Object.entries(data).forEach(([key, sec]) => {
    sec.entries.forEach(e => manageEntries.push({ ...e, section: key, sectionLabel: sec.label }));
  });
  renderManageList();
}

function renderManageList() {
  const area = document.getElementById('manageListArea');
  const filter = document.getElementById('manageFilterSection').value;
  const rows = filter ? manageEntries.filter(e => e.section === filter) : manageEntries;
  if (!rows.length) { area.innerHTML = '<p class="hint">No entries here yet.</p>'; return; }

  area.innerHTML = rows.map(e => `
    <div class="manage-row" data-id="${e.id}" style="border:1px solid #dfe3e8;padding:14px;margin-bottom:10px;">
      <div class="hint" style="margin-bottom:8px;">${e.sectionLabel} &middot; ${e.source} &middot; ${e.date}</div>
      <div class="form-group"><label>Title</label>
        <input type="text" class="m-title" value="${e.title.replace(/"/g,'&quot;')}"></div>
      <div class="form-group"><label>Body</label>
        <textarea class="m-body" rows="3">${e.body.replace(/</g,'&lt;')}</textarea></div>
      <div style="display:flex;gap:10px;">
        <div class="form-group" style="flex:1;"><label>Tag</label>
          <select class="m-tag">${TAG_OPTIONS.map(t => `<option value="${t}" ${t===e.tag?'selected':''}>${t}</option>`).join('')}</select></div>
        <div class="form-group" style="flex:1;"><label>Publisher</label>
          <input type="text" class="m-publisher" value="${(e.publisher||'').replace(/"/g,'&quot;')}"></div>
      </div>
      <div class="form-group"><label>Thumbnail</label>
        ${e.image ? `<div style="margin-bottom:6px;"><img src="/media/${e.image}" style="max-width:160px;border-radius:4px;display:block;margin-bottom:4px;">
          <label style="display:inline-flex;align-items:center;gap:6px;font-weight:400;text-transform:none;font-size:12.5px;">
            <input type="checkbox" class="m-remove-img"> Remove this thumbnail</label></div>` : ''}
        <input type="file" class="m-image" accept="image/*">
        <p class="hint">${e.image ? 'Choose a new file to replace it.' : 'No thumbnail yet - choose a file to add one.'}</p></div>
      <div style="display:flex;gap:8px;">
        <button type="button" class="m-save">Save changes</button>
        <button type="button" class="m-delete" style="background:#C43A2C;">Delete entry</button>
      </div>
      <div class="m-output output"></div>
    </div>
  `).join('');

  area.querySelectorAll('.manage-row').forEach(row => {
    const id = row.dataset.id;

    row.querySelector('.m-save').addEventListener('click', async () => {
      const out = row.querySelector('.m-output');
      const payload = {
        title: row.querySelector('.m-title').value,
        body: row.querySelector('.m-body').value,
        tag: row.querySelector('.m-tag').value,
        publisher: row.querySelector('.m-publisher').value,
      };
      const removeImg = row.querySelector('.m-remove-img');
      const imageFile = row.querySelector('.m-image').files[0];
      if (imageFile) {
        try { payload.image = await uploadImageFile(imageFile); }
        catch (err) { showOutput(out, { error: err.message }); return; }
      } else if (removeImg && removeImg.checked) {
        payload.image = "";
      }
      const res = await fetch('/api/v1/entry/' + id, {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
      });
      const result = await res.json();
      showOutput(out, result);
      if (res.ok) loadManageEntries();
    });

    row.querySelector('.m-delete').addEventListener('click', async () => {
      if (!confirm('Delete this entry permanently? This is not archived - it is gone.')) return;
      const res = await fetch('/api/v1/entry/' + id, { method: 'DELETE' });
      const result = await res.json();
      if (res.ok) { row.remove(); } else { showOutput(row.querySelector('.m-output'), result); }
    });
  });
}

document.getElementById('manageFilterSection').addEventListener('change', renderManageList);
loadManageEntries();

// ---- History & Reset tab ------------------------------------------------

async function loadArchiveHistory() {
  const area = document.getElementById('archiveHistoryArea');
  const res = await fetch('/api/v1/archive');
  const list = await res.json();
  if (!list.length) { area.innerHTML = '<p class="hint">No past editions archived yet.</p>'; return; }
  area.innerHTML = list.map(a => `
    <div style="border:1px solid #dfe3e8;padding:12px 14px;margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div><strong>${a.label}</strong>
          <span class="hint" style="margin-left:8px;">${a.count} item(s) &middot; archived ${a.archived_date}</span>
        </div>
        <button type="button" class="viewHistoryBtn" data-id="${a.id}">View</button>
      </div>
      <div id="historyDetail-${a.id}" style="display:none;margin-top:10px;"></div>
    </div>
  `).join('');
  area.querySelectorAll('.viewHistoryBtn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const detailEl = document.getElementById('historyDetail-' + id);
      if (detailEl.style.display === 'block') { detailEl.style.display = 'none'; return; }
      if (!detailEl.dataset.loaded) {
        const dRes = await fetch('/api/v1/archive/' + id);
        const detail = await dRes.json();
        const bySection = {};
        detail.entries.forEach(e => { (bySection[e.section_label] ||= []).push(e); });
        detailEl.innerHTML = Object.entries(bySection).map(([label, items]) => `
          <div style="margin-top:10px;">
            <div style="font-weight:700;font-size:12.5px;color:#1787ac;">${label}</div>
            ${items.map(e => `
              <div style="padding:8px 0;border-top:1px solid #f0f1f3;">
                <div style="font-weight:600;font-size:13px;">${e.title}</div>
                <div style="font-size:12.5px;color:#4a5058;margin-top:2px;">${e.body}</div>
                <div class="hint" style="margin-top:4px;">${e.tag} &middot; by ${e.publisher} &middot; ${e.date}</div>
              </div>
            `).join('')}
          </div>
        `).join('');
        detailEl.dataset.loaded = '1';
      }
      detailEl.style.display = 'block';
    });
  });
}
loadArchiveHistory();

document.getElementById('archiveAllBtn').addEventListener('click', async () => {
  const label = document.getElementById('archiveLabel').value.trim();
  if (!label) { alert('Give this edition a label first, e.g. "September 2026 Edition".'); return; }
  if (!confirm('Archive everything and clear the board? This moves ALL current entries, in every section, into history and empties the active list. This cannot be undone from here.')) return;
  const res = await fetch('/api/v1/archive-all', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ label })
  });
  const result = await res.json();
  showOutput(document.getElementById('archiveAllOutput'), result);
  if (res.ok) {
    document.getElementById('archiveLabel').value = '';
    loadArchiveHistory();
    loadManageEntries();
  }
});
</script>
</body></html>
"""

# ---------------------------------------------------------------------------
# Routes - public / legacy server-rendered pages
# ---------------------------------------------------------------------------

@app.route("/")
def public_landing():
    sections = get_sections()
    total_entries = sum(len(s["entries"]) for s in sections.values())
    imported_count = sum(
        1 for s in sections.values() for e in s["entries"] if e["source"] != "seed"
    )
    return render_template_string(
        PUBLIC_TEMPLATE, sections=sections, total_entries=total_entries,
        imported_count=imported_count, today=datetime.utcnow().strftime("%Y-%m-%d"),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid_user = secrets.compare_digest(username, ADMIN_USERNAME)
        valid_pass = check_password_hash(ADMIN_PASSWORD_HASH, password)
        if valid_user and valid_pass:
            session["logged_in"] = True
            return redirect(url_for("admin_console"))
        error = "Invalid administrator credentials."
    return render_template_string(LOGIN_TEMPLATE, error=error)


@app.route("/admin")
def admin_console():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template_string(ADMIN_TEMPLATE, sections=get_sections(), log=get_import_log())


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("public_landing"))


@app.route("/api/v1/session")
def api_session():
    return jsonify({"logged_in": bool(session.get("logged_in"))})


@app.route("/api/v1/login", methods=["POST"])
def api_login():
    payload = request.get_json(silent=True) or {}
    username = payload.get("username", "")
    password = payload.get("password", "")
    valid_user = secrets.compare_digest(username, ADMIN_USERNAME)
    valid_pass = check_password_hash(ADMIN_PASSWORD_HASH, password)
    if valid_user and valid_pass:
        session["logged_in"] = True
        return jsonify({"status": "success"}), 200
    return jsonify({"error": "Invalid administrator credentials."}), 401


@app.route("/api/v1/logout", methods=["POST"])
def api_logout():
    session.pop("logged_in", None)
    return jsonify({"status": "success"}), 200


@app.route("/api/v1/sections")
def api_sections():
    return jsonify(get_sections())


@app.route("/api/v1/entry/<int:entry_id>")
def api_entry(entry_id):
    entry = get_entry_by_id(entry_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404
    return jsonify(entry)


@app.route("/api/v1/entry/<int:entry_id>", methods=["PUT", "POST"])
def api_update_entry(entry_id):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    if not get_entry_raw(entry_id):
        return jsonify({"error": "Entry not found"}), 404
    ok = update_entry(
        entry_id,
        title=payload.get("title"),
        body=payload.get("body"),
        tag=payload.get("tag"),
        publisher=payload.get("publisher"),
        image=payload.get("image"),
    )
    if not ok:
        return jsonify({"error": "Body cannot be empty."}), 400
    updated = get_entry_by_id(entry_id)
    return jsonify({"status": "success", "entry": updated})


@app.route("/api/v1/entry/<int:entry_id>", methods=["DELETE"])
def api_delete_entry(entry_id):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    if not delete_entry(entry_id):
        return jsonify({"error": "Entry not found"}), 404
    return jsonify({"status": "success"})


@app.route("/api/v1/import-log")
def api_import_log():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    return jsonify(get_import_log())


@app.route("/admin/template.xlsx")
def download_template():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    wb = Workbook()
    ws = wb.active
    ws.title = "updates"
    ws.append(["section", "title", "body", "publisher"])
    ws.append(["projects", "Example update", "Replace this row with real content.", "Your Name"])
    ws.append(["competitors", "Example update", "Replace this row with real content.", "Your Name"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from flask import send_file
    return send_file(
        buf, as_attachment=True, download_name="technomak_newsletter_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---------------------------------------------------------------------------
# Routes - JSON API
# ---------------------------------------------------------------------------

@app.route("/api/v1/<section>", methods=["GET"])
def get_section(section):
    if section not in SECTION_META:
        return jsonify({"error": "Section not found"}), 404
    return jsonify({"status": "success", "section": section, "data": get_section_entries(section)}), 200


@app.route("/api/v1/<section>", methods=["POST"])
def post_section(section):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    if section not in SECTION_META:
        return jsonify({"error": "Section not found"}), 404
    payload = request.get_json(silent=True) or {}
    publisher = payload.get("publisher") or "Admin"
    tag = payload.get("tag") if payload.get("tag") in _ALLOWED_TAGS else "New"
    ok = add_entry(section, payload.get("title"), payload.get("body"), "manual",
                   tag=tag, publisher=publisher, image=payload.get("image"))
    if not ok:
        return jsonify({"error": "Both 'title' and 'body' are required."}), 400
    log_import("manual", section, 1, 0)
    return jsonify({"status": "success", "message": f"Published to {section}"}), 201

# ---------------------------------------------------------------------------
# Routes - admin imports (Excel upload, URL fetch)
# ---------------------------------------------------------------------------

def parse_grouped_rows(ws):
    """Fallback parser for real-world spreadsheets that don't use our
    section/title/body header - e.g. a competitor list with one company
    per group and several detail lines per company, where the company
    name is only written once (merged-cell style) and left blank on the
    rows below it.

    Assumes: column A is an optional index/number (ignored), column B is
    the entity/title (filled on the first row of a group, blank after),
    column C is one detail line per row. Consecutive detail lines under
    the same title are joined into a single entry body.
    """
    groups = []  # list of (title, [detail_lines])
    current_title = None
    current_lines: list = []

    all_rows = list(ws.iter_rows(values_only=True))
    for row in all_rows[1:]:  # skip the header row
        cells = list(row) + [None, None, None]
        title_cell = cells[1]
        detail_cell = cells[2]

        title_val = str(title_cell).replace("\u200b", "").strip() if title_cell else ""
        detail_val = str(detail_cell).replace("\u200b", "").strip() if detail_cell else ""

        if title_val:
            if current_title and current_lines:
                groups.append((current_title, current_lines))
            current_title = title_val
            current_lines = [detail_val] if detail_val else []
        elif detail_val and current_title:
            current_lines.append(detail_val)

    if current_title and current_lines:
        groups.append((current_title, current_lines))

    return [
        {"title": title, "body": " • " + "\n • ".join(lines)}
        for title, lines in groups
        if lines
    ]


def looks_like_standard_schema(header):
    return any(h in header for h in ("section", "title", "body"))


@app.route("/admin/import/excel", methods=["POST"])
def import_excel():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded."}), 400
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files are supported."}), 400

    # Optional: force every row in this file into one specific section.
    # Required for files that don't have their own 'section' column (like
    # the grouped-rows fallback format below).
    target_section = resolve_section(request.form.get("section"))

    try:
        wb = load_workbook(file, read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter)
        header = [str(h).strip().lower() if h else "" for h in header_row]

        if looks_like_standard_schema(header):
            rows = []
            for raw_row in rows_iter:
                row = dict(zip(header, raw_row))
                if any(v not in (None, "") for v in row.values()):
                    if target_section and not row.get("section"):
                        row["section"] = target_section
                    rows.append(row)
            added, skipped = ingest_rows(rows, f"excel:{filename}")
        else:
            if not target_section:
                return jsonify({
                    "error": "This file doesn't use the standard section/title/body "
                             "columns. Choose a target section and it will be parsed "
                             "as a grouped list (one entry per named group)."
                }), 400
            parsed_rows = parse_grouped_rows(ws)
            if not parsed_rows:
                return jsonify({"error": "Could not find any grouped rows to import "
                                          "from this file."}), 400
            for row in parsed_rows:
                row["section"] = target_section
            added, skipped = ingest_rows(parsed_rows, f"excel:{filename}")
    except Exception as exc:
        return jsonify({"error": f"Could not read that file: {exc}"}), 400

    log_import("excel", filename, added, skipped)
    return jsonify({"status": "success", "added": added, "skipped": skipped}), 200


@app.route("/admin/import/url", methods=["POST"])
def import_url():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"error": "Please provide a valid http(s) URL."}), 400

    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Technomak-Digest/1.0"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": f"Could not fetch that URL: {exc}"}), 400

    content_type = resp.headers.get("Content-Type", "")
    text = resp.text[:2_000_000]  # 2MB safety cap

    added = skipped = 0
    try:
        if "json" in content_type or url.lower().endswith(".json"):
            added, skipped = ingest_json(resp.json(), f"url:{url}")
        else:
            reader = csv.DictReader(io.StringIO(text))
            added, skipped = ingest_rows(reader, f"url:{url}")
    except Exception as exc:
        return jsonify({"error": f"Fetched the URL but could not parse it as CSV or JSON: {exc}"}), 400

    log_import("url", url, added, skipped)
    return jsonify({"status": "success", "added": added, "skipped": skipped}), 200


# ===========================================================================
# v4 FEATURES: search, key metrics, AI summary, AI newsletter creator,
# email delivery to subscribers.
# ===========================================================================

import json as _json
import re as _re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# --- extra tables ----------------------------------------------------------

def init_features_db():
    with closing(get_db()) as conn:
        # Migration: add the image column to existing databases.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(entries)")]
        if "image" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN image TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                added TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                generated TEXT NOT NULL,
                mode TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                archived_date TEXT NOT NULL,
                entries_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()


init_features_db()


def get_setting(key, default=""):
    with closing(get_db()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()


def archive_all_entries(label):
    """Snapshots every current entry (across all sections) into
    archive_snapshots, then clears the entries table entirely so the admin
    can start fresh. Returns the number of entries archived."""
    import json as _json
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, section, title, body, tag, date, source, publisher, image "
            "FROM entries ORDER BY section, id"
        ).fetchall()
    entries = [dict(r) for r in rows]
    if not entries:
        return 0
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO archive_snapshots (label, archived_date, entries_json) VALUES (?, ?, ?)",
            (label, datetime.utcnow().strftime("%Y-%m-%d"), _json.dumps(entries)),
        )
        conn.execute("DELETE FROM entries")
        conn.commit()
    return len(entries)


def get_archive_list():
    import json as _json
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, label, archived_date, entries_json FROM archive_snapshots ORDER BY id DESC"
        ).fetchall()
    return [
        {"id": r["id"], "label": r["label"], "archived_date": r["archived_date"],
         "count": len(_json.loads(r["entries_json"]))}
        for r in rows
    ]


def get_archive_detail(archive_id):
    import json as _json
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT label, archived_date, entries_json FROM archive_snapshots WHERE id = ?",
            (archive_id,),
        ).fetchone()
    if not row:
        return None
    entries = _json.loads(row["entries_json"])
    for e in entries:
        e["section_label"] = SECTION_META.get(e["section"], e["section"])
    return {"label": row["label"], "archived_date": row["archived_date"], "entries": entries}

# --- LLM helper (Groq / OpenAI-compatible, fully optional) -----------------
# Set ONE of these before starting the app to enable real AI generation:
#   export GROQ_API_KEY="gsk_..."       (uses Groq's free tier, gpt-oss-120b)
#   export OPENAI_API_KEY="sk-..."      (uses OpenAI)
# Or override everything explicitly:
#   export LLM_BASE_URL=".../v1/chat/completions"  LLM_API_KEY=...  LLM_MODEL=...
# With no key set, AI endpoints fall back to a rule-based mode so the app
# still works end to end in demos.
# The AI Agent tab (agent.py) also searches the web, and needs both an LLM key
# above AND:
#   export TAVILY_API_KEY="tvly-..."    (Tavily search API, tavily.com)
# It has no rule-based fallback - without the keys it returns a clear error.
# The public "Ask about the news" chat (reader_agent.py, /api/v1/ask) uses
# the same LLM key and TAVILY_API_KEY.

def _llm_config():
    base = os.environ.get("LLM_BASE_URL")
    key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL")
    if not key and os.environ.get("GROQ_API_KEY"):
        key = os.environ["GROQ_API_KEY"]
        base = base or "https://api.groq.com/openai/v1/chat/completions"
        # llama-3.3-70b-versatile was retired by Groq; override with LLM_MODEL.
        model = model or "openai/gpt-oss-120b"
    if not key and os.environ.get("OPENAI_API_KEY"):
        key = os.environ["OPENAI_API_KEY"]
        base = base or "https://api.openai.com/v1/chat/completions"
        model = model or "gpt-4o-mini"
    if not (base and key and model):
        return None
    return {"base": base, "key": key, "model": model}


def llm_available():
    return _llm_config() is not None


def call_llm(system_prompt, user_prompt, max_tokens=900):
    """Returns (text, None) on success or (None, error_message) on failure."""
    cfg = _llm_config()
    if not cfg:
        return None, "No LLM API key configured."
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    # gpt-oss models think before answering, and the thinking counts against
    # max_tokens - keep it short so the actual answer isn't cut off.
    if "gpt-oss" in cfg["model"]:
        body["reasoning_effort"] = "low"
    try:
        # Free tiers (Groq: 8,000 tokens/minute) answer 429 when a burst of
        # calls exceeds the limit - wait as long as they ask, then retry.
        for attempt in range(4):
            resp = requests.post(
                cfg["base"],
                headers={"Authorization": f"Bearer {cfg['key']}",
                         "Content-Type": "application/json"},
                json=body,
                timeout=45,
            )
            if resp.status_code != 429 or attempt == 3:
                break
            try:
                wait = float(resp.headers.get("retry-after", 10))
            except ValueError:
                wait = 10
            time.sleep(min(max(wait, 1), 30))
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if not text:
            return None, (f"LLM returned no text (stopped: {choice.get('finish_reason')}) "
                          "- it may have run out of tokens.")
        return text, None
    except Exception as exc:
        return None, f"LLM call failed: {exc}"


def recent_entries_digest_text(limit=40, section=None):
    """Plain-text dump of the most recent entries, for AI prompts.
    Pass section= to restrict it to one section key."""
    with closing(get_db()) as conn:
        if section:
            rows = conn.execute(
                "SELECT section, title, body, tag, date FROM entries "
                "WHERE section = ? ORDER BY id DESC LIMIT ?", (section, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT section, title, body, tag, date FROM entries "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    lines = []
    for r in rows:
        label = SECTION_META.get(r["section"], r["section"])
        lines.append(f"[{label} | {r['tag']} | {r['date']}] {r['title']}: {r['body']}")
    return "\n".join(lines)


def rule_based_summary():
    """Fallback executive summary with no AI: real counts + notable items."""
    with closing(get_db()) as conn:
        total = conn.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"]
        risks = conn.execute(
            "SELECT title FROM entries WHERE tag='Risk' ORDER BY id DESC LIMIT 3").fetchall()
        opps = conn.execute(
            "SELECT title FROM entries WHERE tag='Opportunity' ORDER BY id DESC LIMIT 3").fetchall()
        newest = conn.execute(
            "SELECT title, section FROM entries WHERE source != 'seed' "
            "ORDER BY id DESC LIMIT 3").fetchall()
    bullets = [f"• {total} updates on record across {len(SECTION_META)} sections."]
    if risks:
        bullets.append("• Risks flagged: " + "; ".join(r["title"] for r in risks) + ".")
    if opps:
        bullets.append("• Opportunities in play: " + "; ".join(o["title"] for o in opps) + ".")
    if newest:
        bullets.append("• Latest additions: " + "; ".join(
            f"{n['title']} ({SECTION_META.get(n['section'], n['section'])})" for n in newest) + ".")
    return "\n".join(bullets)


def latest_summary():
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT content, generated, mode FROM summaries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {"content": row["content"], "generated": row["generated"], "mode": row["mode"]}


# --- Images -----------------------------------------------------------------
# Uploaded pictures live next to the database in ./media and are served from
# /media/<name>. Entries store just the filename.

MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@app.route("/media/<path:name>")
def serve_media(name):
    return send_from_directory(MEDIA_DIR, name)


@app.route("/admin/upload-image", methods=["POST"])
def upload_image():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No image uploaded."}), 400
    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in IMAGE_EXT:
        return jsonify({"error": "Use a JPG, PNG, WEBP or GIF image."}), 400
    raw = file.read()
    if len(raw) > MAX_IMAGE_BYTES:
        return jsonify({"error": "That image is larger than 8 MB."}), 400
    name = f"{secrets.token_hex(8)}{ext}"
    with open(os.path.join(MEDIA_DIR, name), "wb") as fh:
        fh.write(raw)
    return jsonify({"status": "success", "image": name,
                    "url": f"/media/{name}"}), 201


# --- Search ----------------------------------------------------------------

@app.route("/api/v1/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"query": q, "results": []})
    like = f"%{q}%"
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, section, title, body, tag, date, source, publisher, image FROM entries "
            "WHERE title LIKE ? COLLATE NOCASE OR body LIKE ? COLLATE NOCASE "
            "   OR tag LIKE ? COLLATE NOCASE "
            "ORDER BY id DESC LIMIT 50",
            (like, like, like),
        ).fetchall()
    results = [{
        "id": r["id"], "section": r["section"],
        "section_label": SECTION_META.get(r["section"], r["section"]),
        "title": r["title"], "body": r["body"], "tag": r["tag"],
        "date": r["date"], "source": r["source"], "publisher": r["publisher"],
        "image": r["image"],
    } for r in rows]
    return jsonify({"query": q, "results": results})


# --- Public "Ask about the news" chat (reader_agent.py) --------------------
# Not the keyword search above: this researches the web live (Tavily) and
# answers in a conversation. Public - no login - so it is length-limited and
# rate-limited per IP. It reads nothing from and writes nothing to the
# entries table; conversations live in reader_agent.db.

import threading
import traceback
import uuid as _uuid

try:
    import reader_agent as _reader
    _reader.configure(call_llm)
    _READER_IMPORT_ERROR = None
except ImportError as _exc:
    _reader = None
    _READER_IMPORT_ERROR = (f"The news assistant is unavailable ({_exc}). Install it with: "
                            "pip install langgraph langgraph-checkpoint-sqlite")

_CONVERSATION_ID_RE = _re.compile(r"^[A-Za-z0-9_-]{8,64}$")
ASK_RATE_LIMIT = 8        # questions...
ASK_RATE_WINDOW = 60      # ...per this many seconds, per client IP
_ask_hits = {}
_ask_lock = threading.Lock()


def _ask_rate_limited(client):
    now = time.time()
    with _ask_lock:
        hits = [t for t in _ask_hits.get(client, []) if now - t < ASK_RATE_WINDOW]
        limited = len(hits) >= ASK_RATE_LIMIT
        if not limited:
            hits.append(now)
        _ask_hits[client] = hits
    return limited


@app.route("/api/v1/ask", methods=["POST"])
def api_ask():
    if _reader is None:
        print(_READER_IMPORT_ERROR)
        return jsonify({"error": "The news assistant isn't available right now."}), 503
    payload = request.get_json(silent=True) or {}
    query = " ".join(str(payload.get("query") or "").split())
    if not query:
        return jsonify({"error": "Type a question first."}), 400
    if len(query) > _reader.MAX_QUERY_CHARS:
        return jsonify({"error": f"Please keep questions under "
                                 f"{_reader.MAX_QUERY_CHARS} characters."}), 400
    conversation_id = str(payload.get("conversation_id") or "").strip() or str(_uuid.uuid4())
    if not _CONVERSATION_ID_RE.match(conversation_id):
        return jsonify({"error": "Invalid conversation id."}), 400
    if _ask_rate_limited(request.remote_addr or "unknown"):
        return jsonify({"error": "You're asking a bit fast - please wait a minute "
                                 "and try again."}), 429

    try:
        result = _reader.ask(conversation_id, query, payload.get("detail_level"))
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Sorry, something went wrong answering that. "
                                 "Please try again.",
                        "conversation_id": conversation_id}), 500
    if result.get("error"):
        # Full reason in the server log; readers get a plain message.
        print(f"[ask {conversation_id}] {result['error']}")
        return jsonify({"error": "Sorry, I couldn't look that up right now. "
                                 "Please try again in a minute.",
                        "conversation_id": conversation_id}), 502
    return jsonify({
        "conversation_id": conversation_id,
        "response": result.get("response_text", ""),
        "answer": result.get("answer", ""),
        "key_points": result.get("verified_points") or [],
        "sources": result.get("sources_used") or [],
        "topic": result.get("topic", ""),
        "detail_level": result.get("detail_level", "short"),
        "note": result.get("verification_note", ""),
    })


# --- Key metrics -----------------------------------------------------------
# The competitor figures below are curated from the sourced intelligence in
# the digest itself (NPCC/Technomak award tracker, headcount comparison,
# IMARC market projection) so charts always show real numbers even on a
# fresh database.

CURATED_METRICS = {
    "competitor_awards": {
        "title": "Confirmed contract awards 2022–2025 (USD billions)",
        "unit": "$B",
        "items": [
            {"name": "NPCC", "value": 4.2, "note": "3 contracts"},
            {"name": "Technomak", "value": 1.06, "note": "2 contracts"},
        ],
        "source": "Award tracker, Competitor Intelligence",
    },
    "headcount": {
        "title": "Headcount comparison (employees)",
        "unit": "",
        "items": [
            {"name": "NPCC", "value": 7000, "note": "founded 1973"},
            {"name": "Petrofac", "value": 5800, "note": "pre-administration"},
            {"name": "Technomak", "value": 1500, "note": "founded 2004"},
        ],
        "source": "ZoomInfo / Datanyze / LinkedIn",
    },
    "market": {
        "title": "UAE construction market projection (USD billions)",
        "unit": "$B",
        "items": [
            {"name": "2025", "value": 45.8, "note": ""},
            {"name": "2034", "value": 69.0, "note": "projected"},
        ],
        "source": "IMARC Group / Oil & Gas Middle East",
    },
}


@app.route("/api/v1/metrics")
def api_metrics():
    with closing(get_db()) as conn:
        tag_rows = conn.execute(
            "SELECT tag, COUNT(*) c FROM entries GROUP BY tag ORDER BY c DESC"
        ).fetchall()
        sec_rows = conn.execute(
            "SELECT section, COUNT(*) c FROM entries GROUP BY section"
        ).fetchall()
    return jsonify({
        "tag_distribution": [{"name": r["tag"], "value": r["c"]} for r in tag_rows],
        "section_counts": [
            {"name": SECTION_META.get(r["section"], r["section"]),
             "key": r["section"], "value": r["c"]}
            for r in sec_rows
        ],
        "curated": CURATED_METRICS,
    })


# --- AI executive summary --------------------------------------------------

@app.route("/api/v1/summary")
def api_summary():
    return jsonify({"summary": latest_summary()})


@app.route("/admin/ai/summary", methods=["POST"])
def admin_ai_summary():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    publish = bool(payload.get("publish"))

    mode = "ai"
    content = None
    if llm_available():
        content, err = call_llm(
            "You write crisp executive summaries for an internal company digest "
            "at Technomak, an industrial/EPC company. Respond with 3-5 bullet "
            "points only, each starting with '• '. Be specific: name projects, "
            "figures, and risks from the provided updates. No preamble.",
            "Summarize the most important developments from these digest "
            "entries:\n\n" + recent_entries_digest_text(),
        )
        if content is None:
            mode = "fallback"
            content = rule_based_summary()
    else:
        mode = "rule-based"
        content = rule_based_summary()

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    if publish:
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT INTO summaries (content, generated, mode) VALUES (?, ?, ?)",
                (content, generated, mode),
            )
            conn.commit()
    return jsonify({"status": "success", "published": publish,
                    "summary": {"content": content, "generated": generated, "mode": mode},
                    "ai_enabled": llm_available()})


# --- AI newsletter creator -------------------------------------------------

_ALLOWED_TAGS = {"Active", "Deployed", "Testing", "Development", "Risk",
                 "Opportunity", "Industry", "Pending", "Leadership",
                 "Headcount", "Draft", "New"}


_SHORTHAND = [
    (r"\btmak\b", "Technomak"),
    (r"\buat\b", "UAT"),
    (r"\bvm\b", "virtual machine"),
    (r"\bvms\b", "virtual machines"),
    (r"\bdocs\b", "documentation"),
    (r"\bdoc\b", "document"),
    (r"\bpm tool\b", "project management tool"),
    (r"\bmgmt\b", "management"),
    (r"\bw/\s*", "with "),
    (r"\bsigs\b", "signatures"),
    (r"\bppl\b", "people"),
    (r"\bqtr\b", "quarter"),
    (r"\basap\b", "as soon as possible"),
    (r"\bh&s\b", "health and safety"),
    (r"\bavathar\b", "Avatar"),
    (r"\bnews letter\b", "newsletter"),
    (r"(\d+)\s*wk\b", r"\1-week"),
    (r"(\d+)\s*hrs?\b", r"\1 hours"),
    (r"\bno\.\s*", "number "),
]

# Lines starting "<Name> to <verb>" are action items, not descriptions.
_ACTION_RE = _re.compile(r"^([A-Z][a-zA-Z]+(?:\s+and\s+[A-Z][a-zA-Z]+)?)\s+to\s+(.+)$")
_NEEDS_RE = _re.compile(r"^(.+?)\s+(?:need|needs|require|requires)\s+(?:to\s+)?(.+)$", _re.I)


def _expand_shorthand(s):
    for pattern, repl in _SHORTHAND:
        s = _re.sub(pattern, repl, s, flags=_re.IGNORECASE)
    return s


def _tidy_fragment(s):
    """Clean up a raw note fragment: spacing, stray punctuation, capitals."""
    s = _re.sub(r"\s+", " ", s).strip()
    s = s.replace("–", "-").replace("—", "-")
    s = _re.sub(r"\s+([,.;:])", r"\1", s)
    s = _re.sub(r"\s*-\s*(?=[a-z])", " - ", s)   # "docs -developers" -> "docs - developers"
    s = _re.sub(r"\s*/\s*", "/", s)
    s = _expand_shorthand(s)
    s = s.rstrip(",;:-").strip()
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def _as_sentence(s):
    """Turn one fragment into a readable sentence where the shape is clear."""
    s = s.strip()
    if not s:
        return ""
    m = _ACTION_RE.match(s)
    if m:
        who, what = m.group(1), m.group(2)
        if what[:1].isupper() and not what[:2].isupper():
            what = what[0].lower() + what[1:]
        s = f"{who} will {what}"
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s if s.endswith((".", "!", "?")) else s + "."


_NUMBER_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
                 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}

# Words in a heading that tell us what the list underneath actually is.
_LIST_FRAMES = [
    (("plan", "planned", "roadmap", "scope", "week", "sprint"),
     "{n} workstreams are in scope: {items}."),
    (("team", "members", "testers", "squad"),
     "The team consists of {items}."),
    (("tool", "tools", "product", "products", "platform"),
     "The tools covered are {items}."),
    (("risk", "risks", "issue", "issues", "blocker", "blockers"),
     "{n} issues are open: {items}."),
    (("todo", "action", "actions", "next"),
     "{n} actions are outstanding: {items}."),
]


def _frame_for(title):
    low = (title or "").lower()
    for keywords, template in _LIST_FRAMES:
        if any(k in low for k in keywords):
            return template
    return "{n} items are covered: {items}."


def _join_list(items):
    """a, b and c"""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _prose_from_group(title, lines):
    """Compose readable sentences from a heading plus its fragments.

    Template-based, not language understanding: it expands common shorthand,
    picks a sentence frame that matches the heading, and reshapes obvious
    action items ("Sanad to organise X" -> "Sanad will organise X"). It
    cannot infer meaning the way an AI key can.
    """
    title = _tidy_fragment(title or "")
    items = [_tidy_fragment(x) for x in lines if _tidy_fragment(x)]
    items = [i for i in items if i.lower() != title.lower()]
    if not items:
        return _as_sentence(title) if title else ""

    short = [i for i in items if len(i.split()) <= 6]
    long_items = [i for i in items if len(i.split()) > 6]
    sentences = []

    # If the title is itself a full statement (not a short heading), it holds
    # real content - keep it in the body so nothing is lost.
    if title and len(title.split()) > 6:
        sentences.append(_as_sentence(title))

    if len(short) >= 2:
        frame = _frame_for(title)
        sentences.append(frame.format(
            n=_NUMBER_WORDS.get(len(short), str(len(short))),
            items=_join_list(short),
        ))
    elif short:
        sentences.append(_as_sentence(short[0]))

    for item in long_items:
        sentences.append(_as_sentence(item))

    return " ".join(s for s in sentences if s)


def _heuristic_entries_from_text(text, max_entries=10):
    """No-AI fallback parser.

    Works on blank-line-separated blocks, because that's how people actually
    write notes. A multi-line block becomes an entry (first line = title,
    rest = bullets). Single-line blocks - numbered items, one-liners - are
    collected as bullets under the entry above them rather than each becoming
    its own entry, which is what produced 20+ fragments before. A short
    single-line block arriving after an entry already has several bullets is
    read as the next heading.
    """
    list_re = _re.compile(r"^\s*(?:[-*\u2022\u25cf\u00b7]|\(?\d+[\.\)])\s*")
    divider_re = _re.compile(r"^[\-=_*~]{3,}$")

    def clean(ln):
        return list_re.sub("", ln.strip()).strip()

    def is_short(s):
        return len(s.split()) <= 8 and len(s) <= 70 and not s.endswith((".", ";"))

    blocks = []
    for raw_block in _re.split(r"\n\s*\n", text):
        block_lines = [ln.strip() for ln in raw_block.splitlines()
                       if ln.strip() and not divider_re.match(ln.strip())]
        if block_lines:
            blocks.append(block_lines)
    if not blocks:
        return []

    groups = []

    def new_group(title):
        groups.append({"title": title, "lines": []})

    for block in blocks:
        if len(block) > 1:
            # Multi-line block: its own entry.
            head, rest = block[0], block[1:]
            if is_short(head) and not list_re.match(head):
                new_group(clean(head))
                groups[-1]["lines"].extend(clean(x) for x in rest)
            else:
                new_group(clean(head))
                groups[-1]["lines"].extend(clean(x) for x in block)
            continue

        line = block[0]
        cleaned = clean(line)
        if not cleaned:
            continue
        looks_like_item = bool(list_re.match(line))
        starts_new = (
            not groups
            or (not looks_like_item and is_short(cleaned) and len(groups[-1]["lines"]) >= 3)
        )
        if starts_new:
            new_group(cleaned)
        else:
            groups[-1]["lines"].append(cleaned)

    proposed = []
    for g in groups[:max_entries]:
        body_lines = [x for x in g["lines"] if x]
        title = _tidy_fragment(g["title"] or (body_lines[0] if body_lines else ""))[:120]
        if not title:
            continue
        body = _prose_from_group(g["title"], body_lines) or title
        proposed.append({"section": "news", "title": title, "body": body,
                         "tag": "New"})
    return proposed


@app.route("/admin/ai/create", methods=["POST"])
def admin_ai_create():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if len(text) < 10:
        return jsonify({"error": "Paste at least a few sentences of source "
                                 "material first."}), 400

    # The admin picks which section this material belongs to; the AI's job is
    # to turn rough notes into properly written entries for that section,
    # not to guess where things go.
    target_section = resolve_section(payload.get("section"))
    style = (payload.get("style") or "multiple").lower()  # "multiple" | "single"

    proposed, mode = None, "ai"
    if llm_available():
        section_label = SECTION_META.get(target_section, "the digest")
        if style == "single":
            shape = ("Produce exactly ONE entry that covers all of the "
                     "material together.")
        else:
            shape = ("Produce one entry per distinct topic - typically 2 to 5 "
                     "entries. Do not create an entry for every line.")
        raw, err = call_llm(
            "You are an editor for Technomak's internal executive digest, "
            f"writing the '{section_label}' section. You receive rough notes: "
            "fragments, abbreviations, half-sentences, bullet lists and "
            "shorthand. Rewrite them into clear, complete, professional "
            "sentences an executive can read without context.\n\n"
            "Rules:\n"
            "- Expand fragments into full grammatical sentences.\n"
            "- Fix spelling, spacing and capitalisation.\n"
            "- Keep every fact, name, number and owner from the notes. Never "
            "invent details that are not there.\n"
            "- Write in a neutral reporting voice, not marketing language.\n"
            f"- {shape}\n\n"
            "Respond ONLY with a JSON array, no markdown fences. Each "
            "element: {\"title\": short clear headline, \"body\": 1-3 full "
            "sentences, \"tag\": one of Active/Deployed/Testing/Development/"
            "Risk/Opportunity/Industry/Pending/Leadership/New}.",
            "Rough notes to rewrite:\n\n" + text[:10000],
            max_tokens=2000,
        )
        if raw is not None:
            try:
                cleaned = _re.sub(r"^```(json)?|```$", "", raw.strip(),
                                  flags=_re.MULTILINE).strip()
                items = _json.loads(cleaned)
                proposed = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    sec = target_section or resolve_section(it.get("section")) or "news"
                    tag = it.get("tag") if it.get("tag") in _ALLOWED_TAGS else "New"
                    title = str(it.get("title") or "").strip()[:160]
                    body = str(it.get("body") or "").strip()
                    if title and body:
                        proposed.append({"section": sec, "title": title,
                                         "body": body, "tag": tag})
            except Exception:
                proposed = None
    if proposed is None:
        mode = "rule-based" if not llm_available() else "fallback"
        proposed = _heuristic_entries_from_text(text)
        if target_section:
            for p in proposed:
                p["section"] = target_section
    if not proposed:
        return jsonify({"error": "Could not derive any entries from that "
                                 "text."}), 400

    # "Combine into one entry" applies whichever path produced the drafts, so
    # the choice behaves the same with or without an AI key.
    if style == "single" and len(proposed) > 1:
        headline = proposed[0]["title"].strip()
        paragraphs, seen = [], set()
        for p in proposed:
            body = p["body"].strip()
            heading = p["title"].strip()
            # Only prefix the heading when the body doesn't already carry it
            # and doesn't already read as a framed sentence - otherwise we get
            # "Week 1 plans: Six workstreams are in scope: ...".
            reads_as_sentence = bool(_re.match(
                r"^[A-Z][^:]{0,60}\s(is|are|will|has|have|consists|covers|needs)\b", body))
            if (body.lower().startswith(heading.lower())
                    or reads_as_sentence
                    or heading.lower() in body.lower()[:80]):
                part = body
            else:
                part = f"{heading}: {body}"
            part = _re.sub(r"\s+", " ", part).strip()
            if part and part.lower() not in seen:
                seen.add(part.lower())
                paragraphs.append(part if part.endswith(".") else part + ".")
        proposed = [{
            "section": target_section or proposed[0]["section"],
            "title": headline[:120],
            "body": " ".join(paragraphs),
            "tag": proposed[0]["tag"],
        }]

    return jsonify({"status": "success", "mode": mode,
                    "ai_enabled": llm_available(), "proposed": proposed})


@app.route("/admin/ai/publish-batch", methods=["POST"])
def admin_ai_publish_batch():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "No entries to publish."}), 400
    added = skipped = 0
    for it in entries:
        if not isinstance(it, dict):
            skipped += 1
            continue
        sec = resolve_section(it.get("section"))
        tag = it.get("tag") if it.get("tag") in _ALLOWED_TAGS else "New"
        if sec and add_entry(sec, it.get("title"), it.get("body"),
                             "ai-creator", tag=tag, publisher="AI Creator"):
            added += 1
        else:
            skipped += 1
    log_import("ai-creator", "AI newsletter creator", added, skipped)
    # Optional: the AI Agent tab passes the run it came from, so its
    # pending draft is marked approved once something is actually published.
    if added and payload.get("run_id"):
        set_pending_draft_status(str(payload["run_id"]), "approved")
    return jsonify({"status": "success", "added": added, "skipped": skipped})


# --- AI research agent (agent.py, LangGraph) --------------------------------
# The agent drafts one entry per run; nothing publishes from here. Each run's
# result is stored as a pending_drafts row. The admin either approves it
# (published through /admin/ai/publish-batch above) or sends feedback, which
# re-enters the graph at the Draft node and produces a new pending row.

try:
    import agent as _agent
    _agent.configure(call_llm, recent_entries_digest_text, SECTION_META, _ALLOWED_TAGS)
    _AGENT_IMPORT_ERROR = None
except ImportError as _exc:
    _agent = None
    _AGENT_IMPORT_ERROR = (f"The AI agent is unavailable ({_exc}). Install it with: "
                           "pip install langgraph --break-system-packages")


def init_agent_db():
    with closing(get_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_drafts (
                id TEXT PRIMARY KEY,
                section TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                tag TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                status TEXT NOT NULL,
                parent_id TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


init_agent_db()


def save_pending_draft(result, parent_id=None):
    """Stores a finished run; returns its run_id. state_json keeps what
    resume_with_feedback needs to re-enter at Draft."""
    run_id = secrets.token_hex(8)
    entry = result["entry"]
    resume_state = {k: result.get(k) for k in _agent.RESUME_KEYS}
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO pending_drafts (id, section, title, body, tag, "
            "sources_json, state_json, status, parent_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?)",
            (run_id, entry["section"], entry["title"], entry["body"], entry["tag"],
             _json.dumps(result.get("raw_sources") or []), _json.dumps(resume_state),
             parent_id, datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")),
        )
        conn.commit()
    return run_id


def get_pending_draft(run_id):
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM pending_drafts WHERE id = ?",
                           (run_id,)).fetchone()
    return dict(row) if row else None


def set_pending_draft_status(run_id, status):
    with closing(get_db()) as conn:
        conn.execute("UPDATE pending_drafts SET status = ? WHERE id = ?",
                     (status, run_id))
        conn.commit()


def _agent_response(result, parent_id=None):
    """Shared by agent-create and agent-feedback: turn a graph result into
    the JSON the admin UI renders, saving it as a pending draft.
    Returns (response, status_code)."""
    if result.get("status") != "pending_review":
        return jsonify({"error": result.get("error") or "The agent did not produce a draft.",
                        "sources": result.get("raw_sources") or [],
                        "warnings": result.get("warnings") or []}), 502
    run_id = save_pending_draft(result, parent_id=parent_id)
    return jsonify({
        "status": result["status"], "run_id": run_id,
        "proposed": [result["entry"]],
        "sources": result.get("raw_sources") or [],
        "revision_count": result.get("revision_count", 0),
        "topic": result.get("topic"),
        "search_queries": result.get("search_queries") or [],
        "warnings": result.get("warnings") or [],
    }), 200


@app.route("/admin/ai/agent-create", methods=["POST"])
def admin_ai_agent_create():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    if _agent is None:
        return jsonify({"error": _AGENT_IMPORT_ERROR}), 503
    payload = request.get_json(silent=True) or {}
    section = resolve_section(payload.get("section"))
    if not section:
        return jsonify({"error": "Choose a valid section."}), 400
    topic = str(payload.get("topic") or "").strip()[:300]
    try:
        result = _agent.run_agent(section, topic)
        return _agent_response(result)
    except Exception as exc:
        return jsonify({"error": f"The agent failed unexpectedly: {exc}"}), 500


@app.route("/admin/ai/agent-feedback", methods=["POST"])
def admin_ai_agent_feedback():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    if _agent is None:
        return jsonify({"error": _AGENT_IMPORT_ERROR}), 503
    payload = request.get_json(silent=True) or {}
    run_id = str(payload.get("run_id") or "").strip()
    feedback = str(payload.get("human_feedback") or "").strip()[:2000]
    if not feedback:
        return jsonify({"error": "Write what should change first."}), 400
    draft_row = get_pending_draft(run_id)
    if not draft_row:
        return jsonify({"error": "That draft no longer exists - run the agent again."}), 404
    if draft_row["status"] != "pending_review":
        return jsonify({"error": f"That draft is already {draft_row['status']}."}), 409
    try:
        saved_state = _json.loads(draft_row["state_json"])
        # The admin may have edited the title/body inline before asking for
        # changes; revise what they are looking at, not the original.
        for key, field in (("subject", "title"), ("body", "body")):
            edited = str(payload.get(field) or "").strip()
            if edited:
                saved_state[key] = edited
        result = _agent.resume_with_feedback(saved_state, feedback)
        response, code = _agent_response(result, parent_id=run_id)
    except Exception as exc:
        return jsonify({"error": f"The agent failed unexpectedly: {exc}"}), 500
    if code == 200:
        set_pending_draft_status(run_id, "superseded")
    return response, code


# --- Universal file upload -------------------------------------------------
# Accepts any file. Structured formats (xlsx/csv/json) keep their precise
# column-based import. Unstructured formats (pdf/docx/txt/md/html) are text-
# extracted and returned as draft entries for review - nothing publishes
# without the admin approving it in the AI creator's review step.

EXTRACTABLE_EXT = {".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm",
                   ".log", ".rtf"}
STRUCTURED_EXT = {".xlsx", ".csv", ".json"}


def extract_text_from_upload(filename, raw_bytes):
    """Returns (text, error). Supports pdf, docx, html, and any plain text."""
    ext = os.path.splitext(filename.lower())[1]
    try:
        if ext == ".pdf":
            try:
                import pdfplumber
            except ImportError:
                return None, ("Reading PDFs needs the pdfplumber package: "
                              "pip install pdfplumber --break-system-packages")
            pages = []
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                for page in pdf.pages[:60]:  # cap very long documents
                    pages.append(page.extract_text() or "")
            text = "\n\n".join(p for p in pages if p.strip())
            if not text.strip():
                return None, ("That PDF has no extractable text - it may be a "
                              "scanned image. Try a text-based PDF, or paste "
                              "the content into the AI creator instead.")
            return text, None

        if ext == ".docx":
            try:
                from docx import Document
            except ImportError:
                return None, ("Reading Word files needs python-docx: "
                              "pip install python-docx --break-system-packages")
            doc = Document(io.BytesIO(raw_bytes))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            text = "\n".join(parts)
            if not text.strip():
                return None, "That Word document appears to be empty."
            return text, None

        if ext in (".html", ".htm"):
            html = raw_bytes.decode("utf-8", errors="replace")
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for bad in soup(["script", "style"]):
                    bad.decompose()
                text = soup.get_text("\n")
            except ImportError:
                text = _re.sub(r"<[^>]+>", " ", html)
            text = _re.sub(r"\n{3,}", "\n\n", text).strip()
            return (text, None) if text else (None, "No readable text in that "
                                                    "HTML file.")

        # Everything else: treat as plain text.
        text = raw_bytes.decode("utf-8", errors="replace").strip()
        if not text:
            return None, "That file is empty."
        if "\x00" in text[:2000]:
            return None, ("That looks like a binary file. Supported types: "
                          "Excel, CSV, JSON, PDF, Word, text, Markdown and "
                          "HTML.")
        return text, None
    except Exception as exc:
        return None, f"Could not read that file: {exc}"


@app.route("/admin/import/file", methods=["POST"])
def import_any_file():
    """One endpoint for every file type.

    Structured files import directly (same behaviour as before).
    Unstructured files come back as `proposed` draft entries for review.
    """
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded."}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename.lower())[1]
    target_section = resolve_section(request.form.get("section"))
    raw = file.read()

    # ---- Structured: import straight into the digest ----
    if ext == ".xlsx":
        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header_row = next(rows_iter)
            header = [str(h).strip().lower() if h else "" for h in header_row]
            if looks_like_standard_schema(header):
                rows = []
                for raw_row in rows_iter:
                    row = dict(zip(header, raw_row))
                    if any(v not in (None, "") for v in row.values()):
                        if target_section and not row.get("section"):
                            row["section"] = target_section
                        rows.append(row)
                added, skipped = ingest_rows(rows, f"excel:{filename}")
            else:
                if not target_section:
                    return jsonify({
                        "error": "This spreadsheet doesn't use section/title/"
                                 "body columns. Choose a target section and "
                                 "it will be parsed as a grouped list."}), 400
                parsed = parse_grouped_rows(ws)
                if not parsed:
                    return jsonify({"error": "Could not find any rows to "
                                             "import from that spreadsheet."}), 400
                for row in parsed:
                    row["section"] = target_section
                added, skipped = ingest_rows(parsed, f"excel:{filename}")
        except Exception as exc:
            return jsonify({"error": f"Could not read that spreadsheet: {exc}"}), 400
        log_import("excel", filename, added, skipped)
        return jsonify({"status": "success", "kind": "imported",
                        "added": added, "skipped": skipped})

    if ext == ".csv":
        try:
            text = raw.decode("utf-8", errors="replace")
            reader = list(csv.DictReader(io.StringIO(text)))
            if reader and looks_like_standard_schema(
                    [k.strip().lower() for k in (reader[0].keys() or [])]):
                rows = []
                for row in reader:
                    norm = {str(k).strip().lower(): v for k, v in row.items()}
                    if target_section and not norm.get("section"):
                        norm["section"] = target_section
                    rows.append(norm)
                added, skipped = ingest_rows(rows, f"csv:{filename}")
                log_import("csv", filename, added, skipped)
                return jsonify({"status": "success", "kind": "imported",
                                "added": added, "skipped": skipped})
            # No recognisable columns - fall through to text extraction.
        except Exception as exc:
            return jsonify({"error": f"Could not read that CSV: {exc}"}), 400

    if ext == ".json":
        try:
            added, skipped = ingest_json(_json.loads(
                raw.decode("utf-8", errors="replace")), f"json:{filename}")
        except Exception as exc:
            return jsonify({"error": f"Could not parse that JSON: {exc}"}), 400
        log_import("json", filename, added, skipped)
        return jsonify({"status": "success", "kind": "imported",
                        "added": added, "skipped": skipped})

    # ---- Unstructured: extract text, draft entries, hand back for review ----
    text, err = extract_text_from_upload(filename, raw)
    if err:
        return jsonify({"error": err}), 400

    proposed, mode = None, "ai"
    if llm_available():
        sections_desc = ", ".join(f"'{k}'" for k in SECTION_META)
        drafted, _ = call_llm(
            "You turn documents into structured newsletter entries for an "
            "internal company digest. Respond ONLY with a JSON array, no "
            "markdown fences. Each element: {\"section\": one of "
            f"[{sections_desc}], \"title\": short headline, \"body\": 1-3 "
            "sentence summary, \"tag\": one of Active/Deployed/Testing/"
            "Development/Risk/Opportunity/Industry/Pending/Leadership/New}. "
            "One entry per distinct topic. Ignore boilerplate, headers and "
            "page numbers.",
            f"Document: {filename}\n\n{text[:12000]}",
            max_tokens=2000,
        )
        if drafted:
            try:
                cleaned = _re.sub(r"^```(json)?|```$", "", drafted.strip(),
                                  flags=_re.MULTILINE).strip()
                items = _json.loads(cleaned)
                proposed = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    sec = resolve_section(it.get("section")) or target_section or "news"
                    tag = it.get("tag") if it.get("tag") in _ALLOWED_TAGS else "New"
                    title = str(it.get("title") or "").strip()[:160]
                    body = str(it.get("body") or "").strip()
                    if title and body:
                        proposed.append({"section": sec, "title": title,
                                         "body": body, "tag": tag})
            except Exception:
                proposed = None
    if not proposed:
        mode = "rule-based" if not llm_available() else "fallback"
        proposed = _heuristic_entries_from_text(text)
        if target_section:
            for p in proposed:
                p["section"] = target_section
    if not proposed:
        return jsonify({"error": "Could not derive any entries from that "
                                 "file."}), 400

    return jsonify({"status": "success", "kind": "drafted", "mode": mode,
                    "filename": filename, "ai_enabled": llm_available(),
                    "chars_extracted": len(text), "proposed": proposed})


# --- Subscribers & email delivery ------------------------------------------

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_subscribers():
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT id, email, added FROM subscribers ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.route("/admin/subscribers", methods=["GET", "POST"])
def admin_subscribers():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    if request.method == "GET":
        return jsonify({"subscribers": get_subscribers()})
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return jsonify({"error": "That doesn't look like a valid email "
                                 "address."}), 400
    try:
        with closing(get_db()) as conn:
            conn.execute(
                "INSERT INTO subscribers (email, added) VALUES (?, ?)",
                (email, datetime.utcnow().strftime("%Y-%m-%d")),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "That address is already subscribed."}), 400
    return jsonify({"status": "success", "subscribers": get_subscribers()}), 201


@app.route("/admin/subscribers/delete", methods=["POST"])
def admin_subscribers_delete():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    sub_id = payload.get("id")
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM subscribers WHERE id = ?", (sub_id,))
        conn.commit()
    return jsonify({"status": "success", "subscribers": get_subscribers()})


def build_email_html():
    """Self-contained inline-styled HTML email of the current digest."""
    sections = get_sections()
    summary = latest_summary()
    today = datetime.utcnow().strftime("%B %d, %Y")
    tag_colors = {"Risk": "#C43A2C", "Opportunity": "#0F8F6E",
                  "Active": "#0F8F6E", "Pending": "#9BA0A8"}
    parts = [f"""
<!DOCTYPE html><html><body style="margin:0;padding:0;background:#F5F6F9;
font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:24px 16px;">
  <div style="background:linear-gradient(120deg,#14213D,#2F5FE0);
    border-radius:14px;padding:28px 26px;color:#fff;">
    <div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;
      color:#8FB2FF;font-weight:bold;">Internal &middot; Confidential</div>
    <div style="font-size:26px;font-weight:bold;margin-top:6px;">
      Technomak Executive Digest</div>
    <div style="font-size:13px;color:#C7D3EC;margin-top:4px;">{today}</div>
  </div>"""]
    if summary:
        bullets = "".join(
            f'<div style="font-size:13.5px;color:#333;line-height:1.6;'
            f'margin:4px 0;">{ln.strip()}</div>'
            for ln in summary["content"].splitlines() if ln.strip())
        parts.append(f"""
  <div style="background:#fff;border:1px solid #E7E8EC;border-radius:14px;
    padding:20px 22px;margin-top:14px;">
    <div style="font-size:15px;font-weight:bold;color:#181B20;">
      Executive summary</div>
    <div style="margin-top:8px;">{bullets}</div>
    <div style="font-size:11px;color:#9BA0A8;margin-top:10px;">
      Generated {summary['generated']} &middot; {summary['mode']}</div>
  </div>""")
    for key, sec in sections.items():
        if not sec["entries"]:
            continue
        cards = []
        for e in sec["entries"][:4]:
            color = tag_colors.get(e["tag"], "#2F5FE0")
            cards.append(f"""
      <div style="border-top:1px solid #F0F1F3;padding:12px 0;">
        <div style="font-size:14px;font-weight:bold;color:#181B20;">
          {e['title']}</div>
        <div style="font-size:13px;color:#5C6470;line-height:1.55;
          margin-top:4px;">{e['body']}</div>
        <div style="font-size:11px;margin-top:6px;">
          <span style="color:{color};font-weight:bold;">{e['tag']}</span>
          <span style="color:#9BA0A8;"> &middot; {e['date']}</span></div>
      </div>""")
        parts.append(f"""
  <div style="background:#fff;border:1px solid #E7E8EC;border-radius:14px;
    padding:18px 22px;margin-top:14px;">
    <div style="font-size:16px;font-weight:bold;color:#181B20;
      margin-bottom:4px;">{sec['label']}</div>{''.join(cards)}
  </div>""")
    parts.append("""
  <div style="text-align:center;font-size:11px;color:#9BA0A8;
    margin:20px 0 8px;">Confidential &mdash; for internal executive use
    only. Not for distribution.</div>
</div></body></html>""")
    return "".join(parts)


@app.route("/admin/newsletter/preview")
def newsletter_preview():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    return jsonify({"html": build_email_html(),
                    "subscriber_count": len(get_subscribers()),
                    "smtp_configured": bool(os.environ.get("SMTP_HOST"))})


@app.route("/admin/newsletter/send", methods=["POST"])
def newsletter_send():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    subs = get_subscribers()
    if not subs:
        return jsonify({"error": "No subscribers yet - add at least one email "
                                 "address first."}), 400
    host = os.environ.get("SMTP_HOST")
    if not host:
        return jsonify({"error": "SMTP is not configured. Set SMTP_HOST, "
                                 "SMTP_PORT, SMTP_USER, SMTP_PASS and "
                                 "SMTP_FROM environment variables, then "
                                 "restart the backend. (Gmail: use "
                                 "smtp.gmail.com, port 587, and an App "
                                 "Password.)"}), 400
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    sender = os.environ.get("SMTP_FROM", user or "digest@technomak.local")

    html = build_email_html()
    subject = ("Technomak Executive Digest - "
               + datetime.utcnow().strftime("%B %d, %Y"))
    sent, failed = 0, []
    try:
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass  # local/test servers without TLS
        if user and password:
            server.login(user, password)
        for sub in subs:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = sub["email"]
            msg.attach(MIMEText("Your email client does not support HTML. "
                                "Open the digest in a browser.", "plain"))
            msg.attach(MIMEText(html, "html"))
            try:
                server.sendmail(sender, [sub["email"]], msg.as_string())
                sent += 1
            except Exception as exc:
                failed.append({"email": sub["email"], "error": str(exc)})
        server.quit()
    except Exception as exc:
        return jsonify({"error": f"Could not connect to the SMTP server: "
                                 f"{exc}"}), 500
    log_import("email", f"newsletter -> {sent} subscriber(s)", sent, len(failed))
    return jsonify({"status": "success", "sent": sent, "failed": failed})

# ---------------------------------------------------------------------------
# History / archive - "old news should be removed and stored somewhere,
# and when wanted all current news can be removed and new news put in."
# ---------------------------------------------------------------------------

@app.route("/api/v1/archive", methods=["GET"])
def api_get_archive_list():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    return jsonify(get_archive_list())


@app.route("/api/v1/archive/<int:archive_id>", methods=["GET"])
def api_get_archive_detail(archive_id):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    detail = get_archive_detail(archive_id)
    if not detail:
        return jsonify({"error": "Archive not found"}), 404
    return jsonify(detail)


@app.route("/api/v1/archive-all", methods=["POST"])
def api_archive_all():
    """Snapshots every entry across every section into the archive, then
    clears the whole board so the admin can start fresh."""
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized. Admin login required."}), 401
    payload = request.get_json(silent=True) or {}
    label = (payload.get("label") or datetime.utcnow().strftime("%Y-%m-%d")).strip()
    archived_count = archive_all_entries(label)
    log_import("archive", label, archived_count, 0)
    return jsonify({"status": "success", "archived_count": archived_count, "label": label})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

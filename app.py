"""
SVC Vegetables Business Dashboard  v2.0
========================================
Upload daily Sales + Receipts Excel → MongoDB → Full Business Intelligence
New in v2: Running Balance, Bad Debts, Profit/Loss Analysis, Rewards
Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime, timedelta
import os
import re

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except Exception:
    FPDF_AVAILABLE = False

try:
    from escpos.printer import Network as EscposNetwork
    from escpos.printer import Usb as EscposUsb
    import pypdfium2 as pdfium
    ESCPOS_AVAILABLE = True
except Exception:
    ESCPOS_AVAILABLE = False

def _usb_backend():
    """libusb backend bundled via pip (no brew needed)."""
    try:
        import libusb_package
        return libusb_package.get_libusb1_backend()
    except Exception:
        return None

# ─── MongoDB ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to database…")
def _get_db():
    """One connection per server process, not per rerun. Raises if unreachable."""
    from pymongo import MongoClient, ASCENDING
    uri = st.secrets.get("MONGO_URI") or os.environ.get("MONGO_URI")
    if not uri:
        raise ValueError("MONGO_URI not set")
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, tlsAllowInvalidCertificates=True)
    d = client["svc_vegetables"]
    d.sales.create_index([("date", ASCENDING), ("Name", ASCENDING)])
    d.receipts.create_index([("date", ASCENDING), ("Name", ASCENDING)])
    d.customers.create_index([("name", ASCENDING)], unique=True, background=True)
    d.areas.create_index([("name", ASCENDING)], unique=True, background=True)
    d.vegetables.create_index([("name", ASCENDING)], unique=True, background=True)
    d.veg_prices.create_index([("date", ASCENDING), ("item", ASCENDING)])
    d.running_balance.create_index([("customer", ASCENDING)], unique=True, background=True)
    return d

MARGIN_PCT    = 0.05
# Areas whose data is never shown in any dashboard
# CHITS / EXPENSES / PATTY hold internal ledger entries (COOLY, STAFF EXPENSE,
# SWAMY CHIT, …) — not customer credit
EXCLUDE_AREAS = {"KANCHILI", "SENDER", "SVC STAFF", "HOTELS",
                 "CHITS", "EXPENSES", "PATTY"}
# Individual customers excluded regardless of which area they appear under
EXCLUDE_CUSTOMERS = {"PTC", "SVC", "SVC BABU", "SVC BHASKAR", "SVC PARMESH",
                     "SVC PER", "SVC RAJU", "SVC SANTOSH", "SVC SUDHA",
                     "AUROBINDO", "JEEVAN", "PMAS", "DAMAGE",
                     "BANK OF BARODA", "IDBI 5135", "SBI FORT BRANCH"}

st.set_page_config(page_title="SVC Vegetables · Dashboard", page_icon="🥬",
                   layout="wide", initial_sidebar_state="expanded")

try:
    db = _get_db()
    MONGO_AVAILABLE = True
except Exception:
    db = None
    MONGO_AVAILABLE = False

# ─── Password Gate ────────────────────────────────────────────────────────────
def _get_correct_password():
    try:
        return st.secrets["passwords"]["svc_password"]
    except Exception:
        pass
    try:
        return st.secrets["svc_password"]     # top-level fallback
    except Exception:
        return ""

if not st.session_state.get("_authenticated"):
    correct = _get_correct_password()
    st.markdown("## 🥬 SVC Vegetables · Login")
    pwd = st.text_input("Password", type="password", key="_pwd_input")
    if st.button("Login"):
        if correct and pwd == correct:
            st.session_state["_authenticated"] = True
            st.rerun()
        elif not correct:
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Try again.")
    st.stop()
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');
html,body,[class*="css"]{ font-family:'DM Sans',sans-serif; }
.kpi{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);border-radius:14px;padding:18px 20px;margin:4px 0;border-left:4px solid #00d4aa;color:white;}
.kpi.red{border-left-color:#ff6b6b;}.kpi.yellow{border-left-color:#ffd93d;}.kpi.green{border-left-color:#6bcb77;}.kpi.purple{border-left-color:#c084fc;}
.kpi .lbl{font-size:10px;text-transform:uppercase;letter-spacing:1.8px;opacity:.65;}
.kpi .val{font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;margin-top:3px;}
.kpi .sub{font-size:11px;opacity:.55;margin-top:2px;}
.sec{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:2.5px;color:#00d4aa;margin:24px 0 10px;padding-bottom:5px;border-bottom:1px solid rgba(0,212,170,.18);}
.reward-card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid gold;border-radius:12px;padding:16px 20px;text-align:center;color:white;}
.reward-card .rank{font-size:32px;}.reward-card .name{font-size:15px;font-weight:700;margin:6px 0 2px;}
.reward-card .amt{font-family:'JetBrains Mono',monospace;font-size:20px;color:gold;}
div[data-testid="stMetric"]{background:#0f172a;border-radius:8px;padding:12px 16px;}
div[data-testid="stMetricValue"]{color:white;}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# PARSE
# ══════════════════════════════════════════════════════════════
def _clean_sales_df(df):
    """Shared cleaning logic for both single-day and multi-day sales DataFrames."""
    df.columns = ['idx','Date','Name','Sno','Item','Bags','Kgs','Rate','Amount','Cooly']
    df['Date'] = df['Date'].ffill()
    df = df[df['Name'].notna() & (df['Name'].astype(str).str.strip() != '')]
    df = df[df['Name'].astype(str).str.strip() != 'Name']
    df = df[df['Sno'].notna()]  # subtotal rows have no Sno
    df['Name'] = df['Name'].astype(str).str.strip()
    df['Item'] = df['Item'].astype(str).str.strip()
    # Drop excluded customers from sales too
    df = df[~df['Name'].isin(EXCLUDE_CUSTOMERS)]
    for c in ['Bags','Kgs','Rate','Amount','Cooly']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df[['Date','Name','Item','Bags','Kgs','Rate','Amount','Cooly']]

def _clean_receipts_df(df):
    """Shared cleaning logic for both single-day and multi-day receipts DataFrames."""
    df.columns = ['idx','Schedule','Name','OB','Receipts','Balance','Sales','Total']
    df['Schedule'] = df['Schedule'].ffill()
    df = df[df['Name'].notna() & (df['Name'].astype(str).str.strip() != '')]
    df = df[df['Name'].astype(str).str.strip() != 'Name']
    df = df[df['Schedule'].astype(str).str.strip() != 'Total']
    df['Name']     = df['Name'].astype(str).str.strip()
    df['Schedule'] = df['Schedule'].astype(str).str.strip()
    # Drop excluded areas and excluded individual customers entirely at parse time
    df = df[~df['Schedule'].isin(EXCLUDE_AREAS)]
    df = df[~df['Name'].isin(EXCLUDE_CUSTOMERS)]
    for c in ['OB','Receipts','Balance','Sales','Total']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    df['is_internal'] = False  # everything remaining is external/valid
    return df[['Schedule','Name','OB','Receipts','Balance','Sales','Total','is_internal']]

def parse_sales(file):
    """Single-day or multi-day sales file — same format, header row 3 (0-indexed)."""
    df = pd.read_excel(file, header=3)
    return _clean_sales_df(df)

def parse_receipts(file):
    """Single-day or period receipts file — header row 3 (0-indexed)."""
    df = pd.read_excel(file, header=3)
    return _clean_receipts_df(df)

def parse_bulk_sales(file):
    """
    Multi-day sales file: returns dict of {date_str -> DataFrame}.
    Date column has real dates only on first row of each date group; rest are NaN (ffill).
    """
    df = pd.read_excel(file, header=3)
    df = _clean_sales_df(df)
    df['_date_raw'] = df['Date'].astype(str).str.strip()
    by_date = {}
    for raw_d, grp in df.groupby('_date_raw'):
        try:
            # Parse formats like '06-05-26' or '2026-05-06'
            parsed = pd.to_datetime(raw_d, dayfirst=True)
            date_key = parsed.strftime('%Y-%m-%d')
        except Exception:
            continue
        day_df = grp.drop(columns=['_date_raw']).reset_index(drop=True)
        by_date[date_key] = day_df
    return by_date

def parse_bulk_receipts(file):
    """
    Period receipts file: single aggregated summary for the whole period.
    Returns the cleaned DataFrame (no date column).
    """
    df = pd.read_excel(file, header=3)
    return _clean_receipts_df(df)


def detect_file_meta(file):
    """
    Read the title rows of an exported xlsx to find its type and date range.
    Titles look like: 'Customer Status for 18-05-26 to 18-05-26'
                      'Sales List for 30-04-26 to 30-04-26'
    Returns (kind, from_date, to_date) with dates as 'YYYY-MM-DD',
    kind in {'receipts', 'sales', None}.
    """
    try:
        head = pd.read_excel(file, header=None, nrows=3)
        title = " ".join(str(x) for x in head.values.ravel() if pd.notna(x))
    except Exception:
        return None, None, None
    m = re.search(r"(Customer Status|Sales List)\s*for\s*"
                  r"(\d{1,2}-\d{1,2}-\d{2,4})\s*to\s*(\d{1,2}-\d{1,2}-\d{2,4})",
                  title, re.I)
    if not m:
        return None, None, None
    kind = 'receipts' if 'customer' in m.group(1).lower() else 'sales'
    try:
        d_from = pd.to_datetime(m.group(2), dayfirst=True).strftime("%Y-%m-%d")
        d_to   = pd.to_datetime(m.group(3), dayfirst=True).strftime("%Y-%m-%d")
        return kind, d_from, d_to
    except Exception:
        return kind, None, None


# ══════════════════════════════════════════════════════════════
# STORAGE
# ══════════════════════════════════════════════════════════════
if "store" not in st.session_state:
    st.session_state.store = {}

def save_data(date_str, sdf, rdf):
    if MONGO_AVAILABLE:
        db.sales.delete_many({"date": date_str})
        s = sdf.copy(); s["date"] = date_str
        if not s.empty:
            db.sales.insert_many(s.to_dict("records"))
        # Only touch receipts collection if rdf has actual rows
        if not rdf.empty:
            db.receipts.delete_many({"date": date_str})
            r = rdf.copy(); r["date"] = date_str
            db.receipts.insert_many(r.to_dict("records"))
        # Upsert master customers list (all rows are already external — excluded at parse time)
        cust_external = rdf
        for _, row in cust_external.iterrows():
            db.customers.update_one(
                {"name": row['Name']},
                {"$set": {"name": row['Name'], "area": row['Schedule']},
                 "$setOnInsert": {"created_date": date_str}},
                upsert=True
            )
        # Upsert master areas list
        for area in cust_external['Schedule'].dropna().unique():
            db.areas.update_one(
                {"name": area},
                {"$set": {"name": area}},
                upsert=True
            )
        # Upsert vegetables master + daily price snapshots
        veg_summary = sdf.groupby('Item').agg(
            total_kgs=('Kgs','sum'),
            total_bags=('Bags','sum'),
            total_amount=('Amount','sum'),
            avg_rate=('Rate','mean'),
            min_rate=('Rate','min'),
            max_rate=('Rate','max'),
            txn_count=('Amount','count'),
        ).reset_index()
        for _, row in veg_summary.iterrows():
            item_name = str(row['Item']).strip()
            if not item_name or item_name.lower() in ('nan',''):
                continue
            db.vegetables.update_one(
                {"name": item_name},
                {"$set": {"name": item_name},
                 "$setOnInsert": {"first_seen": date_str}},
                upsert=True
            )
            db.veg_prices.update_one(
                {"date": date_str, "item": item_name},
                {"$set": {
                    "date": date_str, "item": item_name,
                    "avg_rate": round(float(row['avg_rate']), 2),
                    "min_rate": round(float(row['min_rate']), 2),
                    "max_rate": round(float(row['max_rate']), 2),
                    "total_kgs": round(float(row['total_kgs']), 2),
                    "total_bags": int(row['total_bags']),
                    "total_amount": round(float(row['total_amount']), 2),
                    "txn_count": int(row['txn_count']),
                }},
                upsert=True
            )
    # Keep the session cache truthful: a sales-only save must not hide the
    # receipts that already exist for this date (re-upload = correction flow)
    if rdf is None or rdf.empty:
        _existing_r = st.session_state.store.get(date_str, {}).get("receipts")
        if (_existing_r is None or _existing_r.empty) and MONGO_AVAILABLE:
            _r_docs = list(db.receipts.find({"date": date_str}, {"_id": 0}))
            if _r_docs:
                _existing_r = pd.DataFrame(_r_docs)
        if _existing_r is not None and not _existing_r.empty:
            rdf = _existing_r
    st.session_state.store[date_str] = {"sales": sdf, "receipts": rdf}

def load_data(date_str):
    if date_str in st.session_state.store:
        d = st.session_state.store[date_str]
        return d["sales"], d["receipts"]
    if MONGO_AVAILABLE:
        s = list(db.sales.find({"date": date_str}, {"_id": 0}))
        r = list(db.receipts.find({"date": date_str}, {"_id": 0}))
        if s or r:   # a day can have receipts only (collection day, no dispatch)
            sdf = pd.DataFrame(s) if s else pd.DataFrame(
                columns=['Date','Name','Item','Bags','Kgs','Rate','Amount','Cooly'])
            rdf = pd.DataFrame(r) if r else pd.DataFrame(
                columns=['Schedule','Name','OB','Receipts','Balance','Sales','Total','is_internal'])
            # Defence in depth: drop rows saved before an area/customer was excluded
            if 'Name' in sdf.columns:
                sdf = sdf[~sdf['Name'].isin(EXCLUDE_CUSTOMERS)]
            if 'Schedule' in rdf.columns:
                rdf = rdf[~rdf['Schedule'].isin(EXCLUDE_AREAS)]
            if 'Name' in rdf.columns:
                rdf = rdf[~rdf['Name'].isin(EXCLUDE_CUSTOMERS)]
            # Coerce numeric columns that MongoDB may return as mixed types
            for c in ['OB','Sales','Receipts','Balance','Total']:
                if c in rdf.columns:
                    rdf[c] = pd.to_numeric(rdf[c], errors='coerce').fillna(0)
            for c in ['Bags','Kgs','Rate','Amount','Cooly']:
                if c in sdf.columns:
                    sdf[c] = pd.to_numeric(sdf[c], errors='coerce').fillna(0)
            st.session_state.store[date_str] = {"sales": sdf, "receipts": rdf}
            return sdf, rdf
    return None, None

def get_all_dates():
    dates = set(st.session_state.store.keys())
    if MONGO_AVAILABLE:
        dates |= set(db.sales.distinct("date"))
        dates |= set(db.receipts.distinct("date"))   # collection-only days count too
    return sorted(dates, reverse=True)


# ══════════════════════════════════════════════════════════════
# RUNNING BALANCE CALCULATION (Forward from pre-6th May)
# ══════════════════════════════════════════════════════════════
def get_customer_running_balance(customer_name, up_to_date_str):
    """
    Calculate running balance for a customer up to a given date.
    Formula: max(0, Initial_RB + sum(Sales) - sum(Receipts)) for all dates <= up_to_date
    """
    if not MONGO_AVAILABLE:
        return 0, 0  # (previous_rb, current_rb)

    # Get initial running balance (pre-6th May)
    init_doc = db.running_balance.find_one({"customer": customer_name})
    initial_rb = float(init_doc.get("initial_balance", 0)) if init_doc else 0

    # Get all sales and receipts for this customer up to the date
    sales_sum = list(db.sales.aggregate([
        {"$match": {"Name": customer_name, "date": {"$lte": up_to_date_str}}},
        {"$group": {"_id": None, "total": {"$sum": "$Amount"}}}
    ]))
    receipts_sum = list(db.receipts.aggregate([
        {"$match": {"Name": customer_name, "date": {"$lte": up_to_date_str}}},
        {"$group": {"_id": None, "total": {"$sum": "$Receipts"}}}
    ]))

    total_sales = float(sales_sum[0]["total"]) if sales_sum else 0
    total_receipts = float(receipts_sum[0]["total"]) if receipts_sum else 0

    # Calculate: max(0, initial + sales - receipts)
    current_rb = max(0, initial_rb + total_sales - total_receipts)

    # Get previous day's running balance
    from datetime import datetime, timedelta
    try:
        prev_date = (datetime.strptime(up_to_date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        sales_sum_prev = list(db.sales.aggregate([
            {"$match": {"Name": customer_name, "date": {"$lte": prev_date}}},
            {"$group": {"_id": None, "total": {"$sum": "$Amount"}}}
        ]))
        receipts_sum_prev = list(db.receipts.aggregate([
            {"$match": {"Name": customer_name, "date": {"$lte": prev_date}}},
            {"$group": {"_id": None, "total": {"$sum": "$Receipts"}}}
        ]))
        prev_sales = float(sales_sum_prev[0]["total"]) if sales_sum_prev else 0
        prev_receipts = float(receipts_sum_prev[0]["total"]) if receipts_sum_prev else 0
        previous_rb = max(0, initial_rb + prev_sales - prev_receipts)
    except:
        previous_rb = initial_rb

    return previous_rb, current_rb


def get_running_balances_bulk(up_to_date_str):
    """
    Running balance for ALL customers as of a date, in 3 queries total.
    RB = initial_balance (pre-history) + Σ Sales − Σ Receipts, clamped at 0.
    Returns DataFrame [Name, initial_rb, cum_sales, cum_receipts, running_balance].
    """
    cols = ['Name','initial_rb','cum_sales','cum_receipts','running_balance']
    if MONGO_AVAILABLE:
        init_map = {d.get("customer"): float(d.get("initial_balance", 0) or 0)
                    for d in db.running_balance.find({}, {"_id": 0})}
        sales_map = {d["_id"]: float(d["total"] or 0) for d in db.sales.aggregate([
            {"$match": {"date": {"$lte": up_to_date_str},
                        "Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$Name", "total": {"$sum": "$Amount"}}}])}
        rcpt_map = {d["_id"]: float(d["total"] or 0) for d in db.receipts.aggregate([
            {"$match": {"date": {"$lte": up_to_date_str},
                        "Schedule": {"$nin": list(EXCLUDE_AREAS)},
                        "Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$Name", "total": {"$sum": "$Receipts"}}}])}
    else:
        # Session-only fallback: sum the in-memory store (no initial balances available)
        init_map, sales_map, rcpt_map = {}, {}, {}
        for d_str, d in st.session_state.store.items():
            if d_str > up_to_date_str:
                continue
            sdf_f, rdf_f = d.get("sales"), d.get("receipts")
            if sdf_f is not None and not sdf_f.empty:
                for n, v in sdf_f.groupby('Name')['Amount'].sum().items():
                    sales_map[n] = sales_map.get(n, 0) + float(v)
            if rdf_f is not None and not rdf_f.empty:
                for n, v in rdf_f.groupby('Name')['Receipts'].sum().items():
                    rcpt_map[n] = rcpt_map.get(n, 0) + float(v)
    names = (set(init_map) | set(sales_map) | set(rcpt_map)) - EXCLUDE_CUSTOMERS - {None}
    rows = []
    for n in sorted(names):
        i, cs, cr = init_map.get(n, 0), sales_map.get(n, 0), rcpt_map.get(n, 0)
        rows.append({"Name": n, "initial_rb": i, "cum_sales": cs,
                     "cum_receipts": cr, "running_balance": max(0, i + cs - cr)})
    return pd.DataFrame(rows, columns=cols)


def build_outstanding_series():
    """
    Business-wide daily totals: [date, sales, receipts, outstanding].
    outstanding = Σ initial balances + cumulative(sales − receipts) up to each day.
    """
    if MONGO_AVAILABLE:
        s = list(db.sales.aggregate([
            {"$match": {"Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$date", "sales": {"$sum": "$Amount"}}}]))
        r = list(db.receipts.aggregate([
            {"$match": {"Schedule": {"$nin": list(EXCLUDE_AREAS)},
                        "Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$date", "receipts": {"$sum": "$Receipts"}}}]))
        init_total = sum(float(d.get("initial_balance", 0) or 0)
                         for d in db.running_balance.find({}, {"_id": 0}))
    else:
        s, r, init_total = [], [], 0.0
        for d_str, d in st.session_state.store.items():
            sdf_f, rdf_f = d.get("sales"), d.get("receipts")
            if sdf_f is not None and not sdf_f.empty:
                s.append({"_id": d_str, "sales": float(sdf_f['Amount'].sum())})
            if rdf_f is not None and not rdf_f.empty:
                r.append({"_id": d_str, "receipts": float(rdf_f['Receipts'].sum())})
    sdf = pd.DataFrame(s).rename(columns={"_id": "date"}) if s else pd.DataFrame(columns=['date','sales'])
    rdf = pd.DataFrame(r).rename(columns={"_id": "date"}) if r else pd.DataFrame(columns=['date','receipts'])
    df = pd.merge(sdf, rdf, on="date", how="outer")
    if df.empty:
        return None
    df['sales']    = pd.to_numeric(df.get('sales'), errors='coerce').fillna(0)
    df['receipts'] = pd.to_numeric(df.get('receipts'), errors='coerce').fillna(0)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
    df['outstanding'] = init_total + (df['sales'] - df['receipts']).cumsum()
    return df


# ══════════════════════════════════════════════════════════════
# BUSINESS SETTINGS (monthly expense)
# ══════════════════════════════════════════════════════════════
DEFAULT_MONTHLY_EXPENSE = 300000

def get_monthly_expense():
    if MONGO_AVAILABLE:
        doc = db.settings.find_one({"_id": "business"})
        if doc:
            return float(doc.get("monthly_expense", DEFAULT_MONTHLY_EXPENSE))
    return float(st.session_state.get("_monthly_expense", DEFAULT_MONTHLY_EXPENSE))

def set_monthly_expense(value):
    st.session_state["_monthly_expense"] = float(value)
    if MONGO_AVAILABLE:
        db.settings.update_one({"_id": "business"},
                               {"$set": {"monthly_expense": float(value)}}, upsert=True)

def get_printer_ip():
    if MONGO_AVAILABLE:
        doc = db.settings.find_one({"_id": "business"})
        if doc and doc.get("printer_ip"):
            return doc["printer_ip"]
    return st.session_state.get("_printer_ip", "")

def set_printer_ip(ip):
    st.session_state["_printer_ip"] = ip
    if MONGO_AVAILABLE:
        db.settings.update_one({"_id": "business"},
                               {"$set": {"printer_ip": ip}}, upsert=True)

def get_printer_usb():
    """Saved (vid, pid) as ints, or (None, None)."""
    doc = db.settings.find_one({"_id": "business"}) if MONGO_AVAILABLE else None
    doc = doc or st.session_state.get("_printer_usb_doc", {})
    vid, pid = doc.get("printer_usb_vid"), doc.get("printer_usb_pid")
    return (int(vid), int(pid)) if vid and pid else (None, None)

def set_printer_usb(vid, pid):
    st.session_state["_printer_usb_doc"] = {"printer_usb_vid": int(vid), "printer_usb_pid": int(pid)}
    if MONGO_AVAILABLE:
        db.settings.update_one({"_id": "business"},
                               {"$set": {"printer_usb_vid": int(vid), "printer_usb_pid": int(pid)}},
                               upsert=True)

def detect_usb_printers():
    """List attached USB devices; printer-class (7) devices marked as likely printers."""
    import usb.core, usb.util
    found = []
    for d in usb.core.find(find_all=True, backend=_usb_backend()):
        try:
            name = usb.util.get_string(d, d.iProduct) if d.iProduct else ""
        except Exception:
            name = ""
        is_printer = d.bDeviceClass == 7
        if not is_printer:
            try:
                for cfg in d:
                    for intf in cfg:
                        if intf.bInterfaceClass == 7:
                            is_printer = True
            except Exception:
                pass
        found.append({"vid": d.idVendor, "pid": d.idProduct,
                      "name": name or "Unknown device", "printer": is_printer})
    return sorted(found, key=lambda x: not x["printer"])


# ══════════════════════════════════════════════════════════════
# DIRECT ESC/POS PRINTING (GOBBLER 80mm over LAN, port 9100)
# ══════════════════════════════════════════════════════════════
def pdf_to_thermal_images(pdf_bytes):
    """
    Rasterize each PDF page at true thermal resolution: 8 dots/mm (203 dpi),
    crop the 4mm page margins → 576-dot-wide 1-bit images, ready for ESC/POS.
    """
    doc = pdfium.PdfDocument(pdf_bytes)
    images = []
    try:
        for page in doc:
            # scale = px per pt; 8 dots/mm ÷ 2.8346 pt/mm
            pil = page.render(scale=8 / 2.8346).to_pil()
            g = pil.convert("L")
            w, h = g.size
            crop = round(w * 4 / 80)          # the 4mm left/right page margins
            g = g.crop((crop, 0, min(crop + 576, w), h))   # exactly 576 dots = 72mm printable
            images.append(g.point(lambda x: 0 if x < 160 else 255, mode='1'))
    finally:
        doc.close()
    return images


def print_images_escpos(images, host, port=9100):
    """Send raster images to the printer over LAN, auto-cutting after each one."""
    p = EscposNetwork(host, port=int(port), timeout=10)
    try:
        for img in images:
            p.image(img)
            p.cut()
    finally:
        try:
            p.close()
        except Exception:
            pass


def print_images_escpos_usb(images, vid, pid):
    """Send raster images to the USB-connected printer, auto-cutting after each one."""
    be = _usb_backend()
    usb_args = {"backend": be} if be else {}
    p = EscposUsb(vid, pid, usb_args=usb_args, timeout=10000)
    try:
        for img in images:
            p.image(img)
            p.cut()
    finally:
        try:
            p.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# 80mm THERMAL BILLS (GOBBLER 3-inch, one bill per page)
# ══════════════════════════════════════════════════════════════
def _amt(n):
    try:
        return f"{float(n):,.0f}"
    except Exception:
        return "0"

_LATIN_MAP = str.maketrans({'—': '-', '–': '-', '→': '>', '₹': 'Rs', '‘': "'", '’': "'",
                            '“': '"', '”': '"', '…': '...'})

TELUGU_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fonts", "NotoSansTelugu-Regular.ttf")

def get_veg_telugu_map():
    """{english_name: telugu_name} from db.vegetables (empty strings dropped)."""
    if not MONGO_AVAILABLE:
        return {}
    return {d["name"]: d["telugu_name"] for d in
            db.vegetables.find({"telugu_name": {"$exists": True, "$ne": ""}},
                               {"_id": 0, "name": 1, "telugu_name": 1})}

def _latin(t):
    """Core PDF fonts are latin-1 only — translate common unicode punctuation, replace the rest."""
    return str(t).translate(_LATIN_MAP).encode('latin-1', 'replace').decode('latin-1')

def build_bills_pdf(date_str, area=None, customer=None):
    """
    One 80mm-wide bill page per customer who has sales on date_str.
    Returns (pdf_bytes, n_bills) or (None, 0).
    """
    if not FPDF_AVAILABLE:
        return None, 0
    sdf, rdf = load_data(date_str)
    if sdf is None or sdf.empty:
        return None, 0
    sdf = sdf[~sdf['Name'].isin(EXCLUDE_CUSTOMERS)].copy()
    for c in ['Bags','Kgs','Rate','Amount']:
        sdf[c] = pd.to_numeric(sdf[c], errors='coerce').fillna(0)

    # Area per customer: today's receipts file first, master list as fallback
    area_map = {}
    if MONGO_AVAILABLE:
        for doc in db.customers.find({}, {"_id": 0, "name": 1, "area": 1}):
            area_map[doc.get("name")] = doc.get("area", "")
    if rdf is not None and not rdf.empty:
        area_map.update(dict(zip(rdf['Name'], rdf['Schedule'])))

    # Running balance track (prev running bal): initial + Σ(sales − receipts) up to yesterday
    prev_cal = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    rb_prev = get_running_balances_bulk(prev_cal)
    run_prev_map = dict(zip(rb_prev['Name'], rb_prev['running_balance'])) if not rb_prev.empty else {}

    # Opening balance = today's Excel OB column (ledger figure, kept separate from running balance)
    ob_map = {}
    if rdf is not None and not rdf.empty and 'OB' in rdf.columns:
        ob_map = dict(zip(rdf['Name'], pd.to_numeric(rdf['OB'], errors='coerce').fillna(0)))

    # Previous data date: cash received + closing Balance (OB fallback when today's
    # receipts file isn't uploaded yet, e.g. printing bills in the morning)
    prev_cash_map, prev_close_map = {}, {}
    prior_dates = [d for d in get_all_dates() if d < date_str]
    if prior_dates:
        _, prev_rdf = load_data(max(prior_dates))
        if prev_rdf is not None and not prev_rdf.empty:
            prev_cash_map = dict(zip(prev_rdf['Name'],
                                     pd.to_numeric(prev_rdf['Receipts'], errors='coerce').fillna(0)))
            if 'Balance' in prev_rdf.columns:
                prev_close_map = dict(zip(prev_rdf['Name'],
                                          pd.to_numeric(prev_rdf['Balance'], errors='coerce').fillna(0)))

    custs = sorted(sdf['Name'].unique(), key=lambda n: (str(area_map.get(n, "")), str(n)))
    if customer:
        custs = [c for c in custs if c == customer]
    elif area:
        custs = [c for c in custs if area_map.get(c, "") == area]
    if not custs:
        return None, 0

    disp_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    pdf = FPDF(unit="mm", format=(80, 200))
    pdf.set_auto_page_break(False)
    pdf.set_margins(4, 4, 4)
    LH  = 4.0                      # line height (mm) — sized for readable thermal print
    SEP = "-" * 42

    # Telugu item names: needs the Noto font + uharfbuzz text shaping
    telugu_map = get_veg_telugu_map()
    telugu_ok = False
    if telugu_map and os.path.exists(TELUGU_FONT_PATH):
        try:
            pdf.add_font("NotoTelugu", "", TELUGU_FONT_PATH)
            pdf.set_text_shaping(True)
            telugu_ok = True
        except Exception:
            telugu_ok = False
    ITEM_W = 33                    # mm for the item-name cell; numbers take the rest

    def line(txt, bold=False, size=9, align='L'):
        pdf.set_font("Courier", "B" if bold else "", size)
        pdf.cell(0, LH, _latin(txt), align=align, new_x="LMARGIN", new_y="NEXT")

    def money_line(label, value, bold=False):
        line(f"{label:<19}: {_amt(value):>16}", bold=bold)   # 37 chars ≈ 70.5mm at 9pt

    for name in custs:
        rows = sdf[sdf['Name'] == name]
        opening     = float(ob_map.get(name, prev_close_map.get(name, 0)))
        run_prev    = float(run_prev_map.get(name, 0))
        prev_cash   = float(prev_cash_map.get(name, 0))
        today_sales = float(rows['Amount'].sum())
        # Bill is handed over in the evening BEFORE cash is collected — no receipts deducted
        closing     = opening + today_sales
        running     = run_prev + today_sales
        cust_area   = str(area_map.get(name, "") or "")

        n_lines = 3 + 1 + 2 + 1 + 1 + len(rows) + 1 + 3 + 1 + 2   # header→footer
        page_h  = 8 + n_lines * LH + 8
        pdf.add_page(format=(80, max(page_h, 60)))

        line("SVC VEGETABLES", bold=True, size=11, align='C')
        line(str(name)[:30], bold=True, size=12, align='C')
        line(f"{cust_area[:22]}  {disp_date}".strip(), size=9, align='C')
        line(SEP, size=8)
        money_line("PREV DAY CASH PAID", prev_cash)
        money_line("OPENING BALANCE", opening, bold=True)
        line(SEP, size=8)
        # Header + item rows as two cells (item name | numbers) so columns stay
        # aligned even when the item cell switches to the Telugu font
        pdf.set_font("Courier", "B", 8)
        pdf.cell(ITEM_W, LH, "ITEM", align='L')
        pdf.cell(0, LH, f"{'BAG':>3}{'KGS':>6}{'RATE':>5}{'AMOUNT':>9}",
                 align='R', new_x="LMARGIN", new_y="NEXT")
        for _, r in rows.iterrows():
            b = float(r['Bags']); k = float(r['Kgs'])
            bags_s = f"{int(b)}" if b > 0 else "-"
            kgs_s  = f"{k:,.1f}" if k > 0 else "-"
            item_en = str(r['Item'])
            nums = f"{bags_s:>3}{kgs_s:>6}{_amt(r['Rate']):>5}{_amt(r['Amount']):>9}"
            tel = str(telugu_map.get(item_en, "") or "")
            if telugu_ok and tel:
                # Core fonts can't hold Telugu glyphs — compose the cell from
                # a Courier part (English + parens) and a Noto Telugu part
                en_part = f"{item_en[:10]}("
                pdf.set_font("Courier", "", 8)
                w_latin = pdf.get_string_width(en_part) + pdf.get_string_width(")")
                pdf.set_font("NotoTelugu", "", 8)
                while tel and w_latin + pdf.get_string_width(tel) > ITEM_W - 1:
                    tel = tel[:-1]
            if telugu_ok and tel:
                x0 = pdf.get_x()
                pdf.set_font("Courier", "", 8)
                pdf.cell(pdf.get_string_width(en_part) + 0.3, LH, _latin(en_part))
                pdf.set_font("NotoTelugu", "", 8)
                pdf.cell(pdf.get_string_width(tel) + 0.3, LH, tel)
                pdf.set_font("Courier", "", 8)
                pdf.cell(2, LH, ")")
                pdf.set_x(x0 + ITEM_W)
            else:
                pdf.set_font("Courier", "", 8)
                pdf.cell(ITEM_W, LH, _latin(item_en[:18]), align='L')
            pdf.set_font("Courier", "", 8)
            pdf.cell(0, LH, nums, align='R', new_x="LMARGIN", new_y="NEXT")
        line(SEP, size=8)
        money_line("TODAY SALES TOTAL", today_sales)
        money_line("CLOSING BALANCE", closing, bold=True)
        money_line("RUNNING BALANCE", running, bold=True)
        line(SEP, size=8)
        line("* Rate mostly per 10 kg", size=8)
        line("Thank you!", size=9, align='C')

    return bytes(pdf.output()), len(custs)


def build_summary_pdf(df, title_lines, fmt="a4"):
    """
    Quick-summary table PDF. df columns:
    [Area, Name, Period_Sales, Running_Balance, Day_Sales, Day_Receipts, Overall_Balance]
    fmt = "a4" (bordered table, repeats header per page) or "thermal" (80mm strip, one cut at end).
    """
    if not FPDF_AVAILABLE or df is None or df.empty:
        return None
    num_cols = ['Period_Sales', 'Running_Balance', 'Day_Sales', 'Day_Receipts', 'Overall_Balance']
    totals = {k: float(df[k].sum()) for k in num_cols}

    if fmt == "thermal":
        # Pages capped at 250mm — many thermal drivers reject longer pages,
        # and the auto-cutter separates pages anyway.
        LH = 3.4
        PAGE_H = 250
        MAX_Y = PAGE_H - 8

        def _camt(v):
            """Compact: 4,50,000 → '4.5L' so 7-char columns stay readable at 7pt."""
            v = float(v)
            return f"{v/100000:.1f}L" if abs(v) >= 100000 else f"{v:,.0f}"

        pdf = FPDF(unit="mm", format=(80, PAGE_H))
        pdf.set_auto_page_break(False)
        pdf.set_margins(3, 4, 3)
        sep = "-" * 48

        def tline(t, bold=False, size=7, align='L'):
            pdf.set_font("Courier", "B" if bold else "", size)
            pdf.cell(0, LH, _latin(t), align=align, new_x="LMARGIN", new_y="NEXT")

        def col_header():
            tline(sep)
            tline(f"{'NAME':<10} {'P.SALE':>7} {'R.BAL':>7} {'D.SAL':>6} {'RCPT':>6} {'BAL':>7}",
                  bold=True)

        pdf.add_page()
        for i, tl in enumerate(title_lines):
            tline(tl, bold=(i == 0), size=9 if i == 0 else 7, align='C')
        col_header()
        for _, r in df.iterrows():
            if pdf.get_y() + LH > MAX_Y:
                pdf.add_page()
                col_header()
            tline(f"{str(r['Name'])[:10]:<10} {_camt(r['Period_Sales']):>7} "
                  f"{_camt(r['Running_Balance']):>7} {_camt(r['Day_Sales']):>6} "
                  f"{_camt(r['Day_Receipts']):>6} {_camt(r['Overall_Balance']):>7}")
        if pdf.get_y() + 7 * LH > MAX_Y:
            pdf.add_page()
        tline(sep)
        tline(f"TOTALS ({len(df)} customers)", bold=True, size=8)
        for lbl, key in [("PERIOD SALES", 'Period_Sales'), ("RUNNING BALANCE", 'Running_Balance'),
                         ("DAY SALES", 'Day_Sales'), ("DAY RECEIPTS", 'Day_Receipts'),
                         ("OVERALL BALANCE", 'Overall_Balance')]:
            tline(f"{lbl:<16}: {_amt(totals[key]):>15}", bold=True, size=8)
        tline(sep)
        return bytes(pdf.output())

    # A4
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(8, 10, 8)
    pdf.add_page()
    for i, tl in enumerate(title_lines):
        pdf.set_font("Courier", "B" if i == 0 else "", 13 if i == 0 else 9)
        pdf.cell(0, 5.5, _latin(tl), align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    widths  = [26, 48, 24, 24, 24, 24, 24]
    headers = ["AREA", "CUSTOMER", "PERIOD SALE", "RUN. BAL", "DAY SALE", "RECEIPTS", "BALANCE"]
    aligns  = ['L', 'L', 'R', 'R', 'R', 'R', 'R']

    def header_row():
        pdf.set_font("Courier", "B", 7.5)
        pdf.set_fill_color(230, 230, 230)
        for w, hh in zip(widths, headers):
            pdf.cell(w, 5.5, hh, border=1, align='C', fill=True)
        pdf.ln()

    header_row()
    pdf.set_font("Courier", "", 7.5)
    for _, r in df.iterrows():
        if pdf.get_y() > 277:
            pdf.add_page()
            header_row()
            pdf.set_font("Courier", "", 7.5)
        vals = [str(r['Area'])[:15], str(r['Name'])[:27],
                _amt(r['Period_Sales']), _amt(r['Running_Balance']),
                _amt(r['Day_Sales']), _amt(r['Day_Receipts']), _amt(r['Overall_Balance'])]
        for w, v, al in zip(widths, vals, aligns):
            pdf.cell(w, 5, _latin(v), border=1, align=al)
        pdf.ln()
    if pdf.get_y() > 277:
        pdf.add_page()
        header_row()
    pdf.set_font("Courier", "B", 7.5)
    tvals = ["", "TOTAL", _amt(totals['Period_Sales']), _amt(totals['Running_Balance']),
             _amt(totals['Day_Sales']), _amt(totals['Day_Receipts']), _amt(totals['Overall_Balance'])]
    for w, v, al in zip(widths, tvals, aligns):
        pdf.cell(w, 5.5, v, border=1, align=al)
    pdf.ln()
    return bytes(pdf.output())


# ══════════════════════════════════════════════════════════════
# ANALYSIS — SINGLE DAY
# ══════════════════════════════════════════════════════════════
def analyze_day(sales, receipts):
    cust = receipts.copy()
    # Coerce all numeric columns — MongoDB may return them as strings/objects
    for c in ['OB','Sales','Receipts','Balance','Total']:
        if c in cust.columns:
            cust[c] = pd.to_numeric(cust[c], errors='coerce').fillna(0)
    for c in ['Bags','Kgs','Rate','Amount','Cooly']:
        if c in sales.columns:
            sales[c] = pd.to_numeric(sales[c], errors='coerce').fillna(0)
    cust['profit_potential'] = cust['Sales'] * MARGIN_PCT
    cust['profit_realized']  = cust.apply(lambda r: min(r['Receipts'], r['Sales']) * MARGIN_PCT, axis=1)
    cust['collection_rate']  = cust.apply(
        lambda r: round(r['Receipts'] / r['Sales'] * 100, 1) if r['Sales'] > 0 else 0.0, axis=1)
    def status(r):
        if r['Balance'] == 0: return "✅ Cleared"
        if r['Receipts'] == 0 and r['Sales'] > 0: return "🔴 No Payment"
        if r['collection_rate'] >= 90: return "🟢 Good"
        if r['collection_rate'] >= 50: return "🟡 Partial"
        return "🔴 Low"
    cust['status'] = cust.apply(status, axis=1)
    area = cust.groupby('Schedule').agg(
        OB=('OB','sum'), Sales=('Sales','sum'),
        Receipts=('Receipts','sum'), Balance=('Balance','sum'),
        Customers=('Name','count'),
        Profit_Potential=('profit_potential','sum'),
        Profit_Realized=('profit_realized','sum'),
    ).reset_index()
    area['Collection_Eff']   = (area['Receipts'] / area['Sales'].replace(0,1) * 100).round(1)
    area['Profit_Loss_Pct']  = (area['Profit_Realized'] / area['Profit_Potential'].replace(0,1) * 100).round(1)
    return dict(
        customers=cust, area=area,
        total_sales=sales['Amount'].sum(),
        total_receipts=cust['Receipts'].sum(),
        total_balance=cust['Balance'].sum(),
        total_ob=cust['OB'].sum(),
        profit_potential=cust['profit_potential'].sum(),
        profit_realized=cust['profit_realized'].sum(),
        sales_by_item=sales.groupby('Item')['Amount'].sum().sort_values(ascending=False),
        sales_by_cust=sales.groupby('Name')['Amount'].sum().sort_values(ascending=False),
    )


# ══════════════════════════════════════════════════════════════
# RUNNING BALANCE — MULTI-DAY
# ══════════════════════════════════════════════════════════════
def build_running_balance(all_dates, from_date=None, to_date=None):
    """
    Running Balance = Total Sales - Total Receipts over the selected date range.
    Handles both daily receipts and period-summary receipts correctly:
    - Daily receipts  : each row is one day's receipt → safe to sum across days
    - Period receipts : same row repeated for every day in the period → de-duplicate
      by keeping only one copy per customer (the one with the latest date in range)
    """
    rows = []
    for d in all_dates:
        _, rdf = load_data(d)
        if rdf is None: continue
        cust = rdf.copy()
        cust['date'] = d
        rows.append(cust)
    if not rows:
        return None
    df = pd.concat(rows, ignore_index=True)
    df['date'] = pd.to_datetime(df['date'])
    if from_date:
        df = df[df['date'] >= pd.to_datetime(from_date)]
    if to_date:
        df = df[df['date'] <= pd.to_datetime(to_date)]

    # De-duplicate period-summary receipts: keep only the latest row per customer
    # so their OB/Receipts/Balance are counted once, not once per day
    is_period = df.get('period_summary', pd.Series(False, index=df.index)).astype(bool)
    df_daily  = df[~is_period]
    df_period = df[is_period]
    if not df_period.empty:
        # For period rows, keep the single latest date entry per customer
        df_period = df_period.sort_values('date').groupby('Name', as_index=False).last()
    df = pd.concat([df_daily, df_period], ignore_index=True)
    if df.empty:
        return None
    df = df.sort_values(['Name','date'])

    # Customer-level: Running Balance = sum(Sales) - sum(Receipts) in period
    cust_grp = df.groupby('Name').agg(
        Area=('Schedule','last'),
        Days_Active=('date','nunique'),
        Period_Sales=('Sales','sum'),
        Period_Receipts=('Receipts','sum'),
        Latest_Balance=('Balance','last'),
        Earliest_OB=('OB','first'),
    ).reset_index()
    # Running Balance is what was NOT collected in this period
    cust_grp['Running_Balance'] = cust_grp['Period_Sales'] - cust_grp['Period_Receipts']
    cust_grp['Cumulative_Sales']    = cust_grp['Period_Sales']
    cust_grp['Cumulative_Receipts'] = cust_grp['Period_Receipts']
    cust_grp['Cumulative_Profit_Potential'] = cust_grp['Period_Sales'] * MARGIN_PCT
    cust_grp['Cumulative_Profit_Realized']  = cust_grp.apply(
        lambda r: min(r['Period_Receipts'], r['Period_Sales']) * MARGIN_PCT, axis=1)
    cust_grp['Collection_Rate'] = (
        cust_grp['Period_Receipts'] / cust_grp['Period_Sales'].replace(0,1) * 100).round(1)
    cust_grp['Profit_Realization_Rate'] = (
        cust_grp['Cumulative_Profit_Realized'] / cust_grp['Cumulative_Profit_Potential'].replace(0,1) * 100).round(1)
    cust_grp['Net_Credit_Extended'] = cust_grp['Running_Balance']
    cust_grp['Bad_Debt_Risk'] = (
        (cust_grp['Running_Balance'] > 200000) & (cust_grp['Collection_Rate'] < 30))

    # Area-level: Running Balance per area per day
    area_daily = df.groupby(['date','Schedule']).agg(
        Sales=('Sales','sum'), Receipts=('Receipts','sum'), Balance=('Balance','sum')).reset_index()
    area_daily['Running_Balance'] = area_daily['Sales'] - area_daily['Receipts']
    area_daily['date'] = area_daily['date'].dt.strftime('%Y-%m-%d')

    # Area summary for the entire period
    area_grp = df.groupby('Schedule').agg(
        Period_Sales=('Sales','sum'),
        Period_Receipts=('Receipts','sum'),
        Latest_Balance=('Balance','sum'),
        Customers=('Name','nunique'),
    ).reset_index()
    area_grp['Running_Balance'] = area_grp['Period_Sales'] - area_grp['Period_Receipts']
    area_grp['Collection_Rate'] = (
        area_grp['Period_Receipts'] / area_grp['Period_Sales'].replace(0,1) * 100).round(1)

    # Force all numeric columns to float to prevent object dtype errors after MongoDB load
    for col in ['Period_Sales','Period_Receipts','Running_Balance','Collection_Rate',
                'Cumulative_Sales','Cumulative_Receipts','Cumulative_Profit_Potential',
                'Cumulative_Profit_Realized','Profit_Realization_Rate','Net_Credit_Extended',
                'Latest_Balance','Days_Active','Earliest_OB']:
        if col in cust_grp.columns:
            cust_grp[col] = pd.to_numeric(cust_grp[col], errors='coerce').fillna(0)
    for col in ['Period_Sales','Period_Receipts','Running_Balance','Collection_Rate','Latest_Balance']:
        if col in area_grp.columns:
            area_grp[col] = pd.to_numeric(area_grp[col], errors='coerce').fillna(0)
    for col in ['Sales','Receipts','Balance','Running_Balance']:
        if col in area_daily.columns:
            area_daily[col] = pd.to_numeric(area_daily[col], errors='coerce').fillna(0)

    return dict(
        cust_grp=cust_grp,
        area_grp=area_grp,
        area_daily=area_daily,
        raw=df,
        dates_used=sorted(df['date'].dt.strftime('%Y-%m-%d').unique()),
    )


def build_veg_analytics(all_dates, from_date=None, to_date=None):
    """
    Aggregate daily sales data by Item across a date range.
    Returns per-item price history, volume, revenue contribution.
    """
    rows = []
    for d in all_dates:
        sdf, _ = load_data(d)
        if sdf is None: continue
        tmp = sdf.copy()
        tmp['date'] = d
        rows.append(tmp)
    if not rows:
        return None
    df = pd.concat(rows, ignore_index=True)
    df['date'] = pd.to_datetime(df['date'])
    if from_date:
        df = df[df['date'] >= pd.to_datetime(from_date)]
    if to_date:
        df = df[df['date'] <= pd.to_datetime(to_date)]
    df = df[df['Item'].notna() & (df['Item'].astype(str).str.strip() != '')]
    if df.empty:
        return None
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')

    # Daily price history per item (for trend charts)
    daily = df.groupby(['date_str','Item']).agg(
        avg_rate=('Rate','mean'),
        min_rate=('Rate','min'),
        max_rate=('Rate','max'),
        total_kgs=('Kgs','sum'),
        total_bags=('Bags','sum'),
        total_amount=('Amount','sum'),
        txn_count=('Rate','count'),
    ).reset_index()
    daily['avg_rate']     = daily['avg_rate'].round(2)
    daily['total_amount'] = daily['total_amount'].round(0)

    # Summary per item across full period
    summary = df.groupby('Item').agg(
        days_sold=('date','nunique'),
        total_kgs=('Kgs','sum'),
        total_bags=('Bags','sum'),
        total_amount=('Amount','sum'),
        avg_rate=('Rate','mean'),
        min_rate=('Rate','min'),
        max_rate=('Rate','max'),
        txn_count=('Rate','count'),
    ).reset_index()
    grand_total = summary['total_amount'].sum()
    summary['revenue_pct'] = (summary['total_amount'] / max(grand_total, 1) * 100).round(1)
    summary['avg_daily_kgs'] = (summary['total_kgs'] / summary['days_sold'].replace(0,1)).round(1)
    summary = summary.sort_values('total_amount', ascending=False).reset_index(drop=True)

    # Per-item customer reach (how many unique customers bought each item)
    cust_reach = df.groupby('Item')['Name'].nunique().reset_index()
    cust_reach.columns = ['Item','unique_customers']
    summary = summary.merge(cust_reach, on='Item', how='left')

    return dict(
        daily=daily,
        summary=summary,
        raw=df,
        grand_total=grand_total,
        dates_used=sorted(df['date_str'].unique()),
    )


def inr(n):
    try: return f"₹{float(n):,.0f}"
    except: return "₹0"

def ct():
    return dict(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(15,32,39,.85)',
                font_color='#e2e8f0', margin=dict(l=4,r=4,t=40,b=4))

def kpi(cls, lbl, val, sub):
    return f'<div class="kpi {cls}"><div class="lbl">{lbl}</div><div class="val">{val}</div><div class="sub">{sub}</div></div>'


# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🥬 SVC Vegetables")
    st.caption("Visakhapatnam · 5% margin")
    if MONGO_AVAILABLE:
        st.success("🟢 MongoDB connected", icon="✅")
    else:
        st.warning("🟡 Session-only mode")
    st.divider()

    # ── SECTION 1: Bulk Sales Import (multi-day sales file) ──────
    st.markdown("#### 📦 Import Sales (Multi-day)")
    st.caption("One file covering multiple dates — dates split automatically")
    bulk_sales_file = st.file_uploader("Sales list (e.g. 06–17 May)", type=["xlsx"], key="sf_bulk")
    if bulk_sales_file:
        if st.button("� Import Sales", use_container_width=True):
            with st.spinner("Splitting by date…"):
                try:
                    sales_by_date = parse_bulk_sales(bulk_sales_file)
                    saved = []
                    for d_str, day_sdf in sales_by_date.items():
                        # Save sales only — receipts uploaded separately per day
                        empty_rdf = pd.DataFrame(columns=['Schedule','Name','OB','Receipts','Balance','Sales','Total','is_internal'])
                        save_data(d_str, day_sdf, empty_rdf)
                        saved.append(d_str)
                    saved.sort()
                    if saved:
                        st.session_state["active_date"] = saved[-1]
                        st.success(f"✅ {len(saved)} days imported: {saved[0]} → {saved[-1]}")
                    else:
                        st.warning("No valid dates found.")
                except Exception as e:
                    st.error(f"Error: {e}")

    st.divider()

    # ── SECTION 2: Upload Receipts — MULTI-FILE ──────────────────
    st.markdown("#### 📋 Upload Receipts (Multi-file)")
    st.caption("Drop many Customer Status files at once — each file's date is read "
               "from its title row automatically")

    # Result report from the previous import (survives the rerun)
    if "_import_report" in st.session_state:
        _ok, _fail = st.session_state.pop("_import_report")
        for _msg in _ok:
            st.success(_msg)
        for _msg in _fail:
            st.error(_msg)

    receipt_files = st.file_uploader("Customer Status files", type=["xlsx"],
                                     accept_multiple_files=True, key="rf_multi")
    if receipt_files:
        # Preview: what will go where
        _preview = []
        for _f in receipt_files:
            _kind, _dfrom, _dto = detect_file_meta(_f)
            _f.seek(0)
            if _kind == 'receipts' and _dfrom and _dfrom == _dto:
                _what = f"Receipts → {_dfrom}"
            elif _kind == 'sales' and _dfrom:
                _what = f"Sales → {_dfrom}" + (f" to {_dto}" if _dto != _dfrom else "")
            elif _kind == 'receipts':
                _what = f"⚠️ period file ({_dfrom} to {_dto}) — will be skipped"
            else:
                _what = "⚠️ no date found — will be skipped"
            _preview.append({"File": _f.name, "Detected": _what})
        st.dataframe(pd.DataFrame(_preview), use_container_width=True, hide_index=True)

        if st.button(f"💾 Import {len(receipt_files)} file(s)", type="primary",
                     use_container_width=True):
            ok_msgs, fail_msgs, imported_dates = [], [], []
            prog = st.progress(0.0, text="Importing…")
            for _i, _f in enumerate(receipt_files):
                try:
                    _kind, _dfrom, _dto = detect_file_meta(_f)
                    _f.seek(0)
                    if _kind == 'receipts' and _dfrom and _dfrom == _dto:
                        _rdf = parse_receipts(_f)
                        _ex_sdf, _ = load_data(_dfrom)
                        if _ex_sdf is None:
                            _ex_sdf = pd.DataFrame(columns=['Date','Name','Item','Bags','Kgs','Rate','Amount','Cooly'])
                        save_data(_dfrom, _ex_sdf, _rdf)
                        imported_dates.append(_dfrom)
                        ok_msgs.append(f"✅ {_f.name} → receipts saved for {_dfrom} ({len(_rdf)} customers)")
                    elif _kind == 'sales' and _dfrom:
                        _by_date = parse_bulk_sales(_f)
                        for _d_str, _day_sdf in sorted(_by_date.items()):
                            _, _ex_rdf = load_data(_d_str)
                            if _ex_rdf is None:
                                _ex_rdf = pd.DataFrame(columns=['Schedule','Name','OB','Receipts','Balance','Sales','Total','is_internal'])
                            save_data(_d_str, _day_sdf, _ex_rdf)
                            imported_dates.append(_d_str)
                        ok_msgs.append(f"✅ {_f.name} → sales saved for {', '.join(sorted(_by_date))}")
                    elif _kind == 'receipts':
                        fail_msgs.append(f"⚠️ {_f.name}: covers a period ({_dfrom} to {_dto}) — "
                                         f"export one file per day and upload those")
                    else:
                        fail_msgs.append(f"⚠️ {_f.name}: couldn't find a date in the title row — "
                                         f"use the manual upload below")
                except Exception as e:
                    fail_msgs.append(f"❌ {_f.name}: {e}")
                prog.progress((_i + 1) / len(receipt_files), text=f"Importing… {_i+1}/{len(receipt_files)}")
            if imported_dates:
                st.session_state["active_date"] = max(imported_dates)
            st.session_state["_import_report"] = (ok_msgs, fail_msgs)
            st.rerun()

    with st.expander("Manual upload — pick the date yourself"):
        _manual_avail = get_all_dates()
        _manual_def = (datetime.strptime(_manual_avail[0], "%Y-%m-%d").date()
                       if _manual_avail else date.today())
        sel_date      = st.date_input("Business Date", value=_manual_def, key="manual_date")
        date_str      = sel_date.strftime("%Y-%m-%d")
        receipts_file = st.file_uploader("Customer Status File", type=["xlsx"], key="rf_daily")
        if receipts_file:
            if st.button("💾 Save Receipts", use_container_width=True, key="manual_save"):
                with st.spinner("Parsing…"):
                    try:
                        rdf = parse_receipts(receipts_file)
                        existing_sdf, _ = load_data(date_str)
                        if existing_sdf is None:
                            existing_sdf = pd.DataFrame(columns=['Date','Name','Item','Bags','Kgs','Rate','Amount','Cooly'])
                        save_data(date_str, existing_sdf, rdf)
                        st.session_state["active_date"] = date_str
                        st.success(f"✅ Receipts saved · {date_str}")
                    except Exception as e:
                        st.error(f"Parse error: {e}")

    st.divider()

    # ── SECTION 3: Business Settings ─────────────────────────────
    st.markdown("#### ⚙️ Business Settings")
    _cur_exp = get_monthly_expense()
    _new_exp = st.number_input("Monthly Expense (₹)", min_value=0, step=10000,
                               value=int(_cur_exp), key="exp_input",
                               help="Fixed business expense per month — used for net profit & break-even")
    if float(_new_exp) != _cur_exp:
        set_monthly_expense(_new_exp)
    st.caption(f"≈ {inr(_new_exp/30)}/day · Break-even sales {inr(_new_exp/MARGIN_PCT)}/month")
    st.caption("🏦 Initial running balances → **📑 Reports** tab (bulk editor)")

    st.divider()

    # ── SECTION 4: Custom Running Balance (Date Range) ─────────────
    st.markdown("#### 📊 Custom Running Balance")
    st.caption("Calculate running balance for any date range")

    all_avail_dates = get_all_dates()
    if len(all_avail_dates) >= 2:
        rb_from = st.date_input("From Date", value=datetime.strptime(all_avail_dates[-1], "%Y-%m-%d").date() if all_avail_dates else date.today(), key="crb_from")
        rb_to = st.date_input("To Date", value=datetime.strptime(all_avail_dates[0], "%Y-%m-%d").date() if all_avail_dates else date.today(), key="crb_to")

        if st.button("🔍 Calculate Running Balance", use_container_width=True):
            with st.spinner("Computing..."):
                from_date_str = rb_from.strftime("%Y-%m-%d")
                to_date_str = rb_to.strftime("%Y-%m-%d")

                # Get all customers who have data in this range
                all_custs_in_range = set()
                if MONGO_AVAILABLE:
                    all_custs_in_range |= set(db.sales.distinct("Name", {"date": {"$gte": from_date_str, "$lte": to_date_str}}))
                    all_custs_in_range |= set(db.receipts.distinct("Name", {"date": {"$gte": from_date_str, "$lte": to_date_str}}))

                if not all_custs_in_range:
                    st.warning("No data found in selected date range.")
                else:
                    # Build running balance for each customer
                    crb_rows = []
                    # Get all dates in range
                    sorted_dates = sorted([d for d in all_avail_dates if from_date_str <= d <= to_date_str])

                    for cust in sorted(all_custs_in_range):
                        if MONGO_AVAILABLE:
                            # Get daily breakdown
                            sales_by_date = {d: 0 for d in sorted_dates}
                            receipts_by_date = {d: 0 for d in sorted_dates}

                            s_docs = list(db.sales.find({"Name": cust, "date": {"$gte": from_date_str, "$lte": to_date_str}}, {"_id": 0, "date": 1, "Amount": 1}))
                            r_docs = list(db.receipts.find({"Name": cust, "date": {"$gte": from_date_str, "$lte": to_date_str}}, {"_id": 0, "date": 1, "Receipts": 1}))

                            for doc in s_docs:
                                sales_by_date[doc.get("date", "")] = sales_by_date.get(doc.get("date", ""), 0) + float(doc.get("Amount", 0))
                            for doc in r_docs:
                                receipts_by_date[doc.get("date", "")] = receipts_by_date.get(doc.get("date", ""), 0) + float(doc.get("Receipts", 0))

                            # Calculate running balance day by day
                            running_bal = 0
                            for d in sorted_dates:
                                running_bal += sales_by_date[d] - receipts_by_date[d]
                                crb_rows.append({
                                    "Customer": cust,
                                    "Date": d,
                                    "Sales": sales_by_date[d],
                                    "Receipts": receipts_by_date[d],
                                    "Daily_Change": sales_by_date[d] - receipts_by_date[d],
                                    "Running_Balance": max(0, running_bal)
                                })

                    if crb_rows:
                        crb_df = pd.DataFrame(crb_rows)
                        st.session_state["custom_rb"] = crb_df
                        st.success(f"✅ Calculated running balance for {len(all_custs_in_range)} customers across {len(sorted_dates)} days")
                    else:
                        st.info("No transactions found in range.")
    else:
        st.caption("Need at least 2 days of data to calculate range")

    # Show stored custom running balance if available
    if "custom_rb" in st.session_state and st.session_state["custom_rb"] is not None:
        st.markdown("<div style='font-size:11px;color:#00d4aa;margin-top:8px;'>✓ Custom RB ready — view in Ledger tab</div>", unsafe_allow_html=True)

    st.divider()
    all_dates = get_all_dates()
    st.markdown(f"#### 📅 History ({len(all_dates)} days)")
    if all_dates:
        chosen = st.selectbox("View a past date", all_dates, label_visibility="collapsed")
        if st.button("📂 Load Selected Date", use_container_width=True):
            st.session_state["active_date"] = chosen
    else:
        st.caption("No data uploaded yet")


# ══════════════════════════════════════════════════════════════
# LOAD DATA
# ══════════════════════════════════════════════════════════════
active_date = st.session_state.get("active_date")
if not active_date and all_dates:
    active_date = all_dates[0]           # auto-load the most recent data day
    st.session_state["active_date"] = active_date
sales = receipts = None
if active_date:
    sales, receipts = load_data(active_date)
    if sales is None and all_dates:      # stale session date with no data → latest real day
        active_date = all_dates[0]
        st.session_state["active_date"] = active_date
        sales, receipts = load_data(active_date)

# Anchor all default date pickers to the newest DATA day (not the calendar today)
LATEST_DATE = (datetime.strptime(all_dates[0], "%Y-%m-%d").date()
               if all_dates else date.today())

st.markdown(f"""
<div style="background:linear-gradient(90deg,#0f2027,#2c5364);padding:18px 26px;border-radius:12px;margin-bottom:18px;border-left:5px solid #00d4aa;">
  <h2 style="margin:0;color:white;font-size:20px;">🥬 SVC Vegetables · Business Intelligence</h2>
  <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
    {'Viewing: <b style="color:#00d4aa">' + active_date + '</b> &nbsp;|&nbsp; ' + str(len(all_dates)) + ' days on record' if active_date else 'Upload files from the sidebar to begin'}
  </p>
</div>
""", unsafe_allow_html=True)

if not active_date or sales is None:
    if not MONGO_AVAILABLE:
        st.error("⚠️ Database not reachable right now — check your internet / MongoDB Atlas and reload the page. "
                 "You can still upload today's files to work in this session.")
    st.info("👈  Upload today's files from the sidebar and click **Save & Analyze**.")
    st.stop()

a = analyze_day(sales, receipts)


# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════
TAB_OVERVIEW, TAB_TODAY, TAB_REPORTS, TAB_BILLS, TAB_RUNNING, TAB_PREVWEEK, TAB_VEG, TAB_BADDEBT, TAB_PROFIT, TAB_REWARDS, TAB_LEDGER = st.tabs([
    "📌 Overview", "📊 Today", "📑 Reports", "🖨️ Print Bills", "📈 Running Balance", "📋 Unpaid Tracker",
    "🥦 Vegetables", "⚠️ Bad Debts", "💰 Profit", "🏆 Rewards", "📒 Ledger"
])


# ─────────────────────────────────────────────────────────────
# TAB 0 — OVERVIEW · BUSINESS COMMAND CENTER
# ─────────────────────────────────────────────────────────────
with TAB_OVERVIEW:
    ov_dates = get_all_dates()
    ser_ov = build_outstanding_series()
    if not ov_dates or ser_ov is None or ser_ov.empty:
        st.info("Upload sales & receipts to see the overview.")
    else:
        latest_str = ov_dates[0]
        latest_ts  = pd.Timestamp(latest_str)
        _exp_m = get_monthly_expense()
        _exp_d = _exp_m / 30
        be_month = _exp_m / MARGIN_PCT

        _upto = ser_ov[ser_ov['date'] <= latest_ts]
        _row  = _upto[_upto['date'] == latest_ts]
        d_sales = float(_row['sales'].sum()); d_rcpts = float(_row['receipts'].sum())
        d_coll  = d_rcpts / max(d_sales, 1) * 100
        d_net   = d_sales * MARGIN_PCT - _exp_d
        book_out = float(_upto['outstanding'].iloc[-1])
        pd_sales = float(_upto['sales'].iloc[-2]) if len(_upto) >= 2 else 0

        w_cur = ser_ov[(ser_ov['date'] > latest_ts - pd.Timedelta(days=7))  & (ser_ov['date'] <= latest_ts)]
        w_prv = ser_ov[(ser_ov['date'] > latest_ts - pd.Timedelta(days=14)) &
                       (ser_ov['date'] <= latest_ts - pd.Timedelta(days=7))]
        ws,  wr  = float(w_cur['sales'].sum()), float(w_cur['receipts'].sum())
        pws, pwr = float(w_prv['sales'].sum()), float(w_prv['receipts'].sum())
        w_coll, pw_coll   = wr / max(ws, 1) * 100, pwr / max(pws, 1) * 100
        w_credit, pw_credit = ws - wr, pws - pwr

        mtd = _upto[_upto['date'].dt.to_period('M') == latest_ts.to_period('M')]
        mtd_sales = float(mtd['sales'].sum())
        mtd_net   = mtd_sales * MARGIN_PCT - _exp_d * latest_ts.day
        be_prog   = mtd_sales / max(be_month, 1) * 100

        _, _rd_ov = load_data(latest_str)
        zero_ov = pd.DataFrame()
        if _rd_ov is not None and not _rd_ov.empty:
            _rz = _rd_ov.copy()
            for _c in ['OB', 'Sales', 'Receipts', 'Balance']:
                _rz[_c] = pd.to_numeric(_rz[_c], errors='coerce').fillna(0)
            zero_ov = _rz[(_rz['Receipts'] == 0) & (_rz['Sales'] > 0)]

        def _delta(cur, prev, invert=False):
            if prev == 0: return "no prev week data"
            ch = (cur - prev) / abs(prev) * 100
            good = (ch >= 0) != invert
            return f"{'▲' if ch >= 0 else '▼'} {abs(ch):.0f}% vs prev week {'🟢' if good else '🔴'}"

        st.caption(f"📅 Latest data: **{latest_str}** · {len(ov_dates)} days on record · "
                   f"break-even {inr(be_month)}/month ≈ {inr(be_month/30)}/day")

        # ── ROW 1: LATEST DAY ──
        st.markdown('<div class="sec">LATEST DAY AT A GLANCE</div>', unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns(5)
        for col, args in zip([c1, c2, c3, c4, c5], [
            ("green",  "Day Sales", inr(d_sales),
             _delta(d_sales, pd_sales) if pd_sales else "first day"),
            ("green" if d_coll >= 70 else "yellow", "Day Collected", inr(d_rcpts),
             f"{d_coll:.1f}% of sales"),
            ("yellow", "Day Pending", inr(d_sales - d_rcpts), "given on credit today"),
            ("green" if d_net >= 0 else "red", "Day Net Profit", inr(d_net),
             f"5% margin − {inr(_exp_d)} expense"),
            ("red" if len(zero_ov) > 0 else "green", "Zero-Payment Buyers", str(len(zero_ov)),
             f"bought {inr(zero_ov['Sales'].sum())}, paid ₹0" if len(zero_ov) else "everyone paid something"),
        ]):
            with col: st.markdown(kpi(*args), unsafe_allow_html=True)

        # ── ROW 2: WEEK & MONTH HEALTH ──
        st.markdown('<div class="sec">WEEK & MONTH HEALTH</div>', unsafe_allow_html=True)
        h1, h2, h3, h4, h5 = st.columns(5)
        for col, args in zip([h1, h2, h3, h4, h5], [
            ("green",  "Week Sales", inr(ws), _delta(ws, pws)),
            ("green" if w_coll >= 70 else "yellow", "Week Collection", f"{w_coll:.1f}%",
             _delta(w_coll, pw_coll)),
            ("red" if w_credit > pw_credit else "yellow", "Week Credit Added", inr(w_credit),
             _delta(w_credit, pw_credit, invert=True)),
            ("green" if mtd_net >= 0 else "red", "Month Net Profit", inr(mtd_net),
             f"gross {inr(mtd_sales*MARGIN_PCT)} − exp {inr(_exp_d*latest_ts.day)}"),
            ("green" if be_prog >= latest_ts.day/30*100 else "red", "Break-even Progress",
             f"{be_prog:.0f}%", f"{inr(mtd_sales)} of {inr(be_month)} this month"),
        ]):
            with col: st.markdown(kpi(*args), unsafe_allow_html=True)

        # ── ROW 3: OUTSTANDING BOOK + CASH FLOW ──
        st.markdown('<div class="sec">CASH FLOW & OUTSTANDING (LAST 30 DAYS)</div>', unsafe_allow_html=True)
        f1, f2 = st.columns([3, 2])
        with f1:
            w30 = ser_ov[(ser_ov['date'] > latest_ts - pd.Timedelta(days=30)) &
                         (ser_ov['date'] <= latest_ts)].copy()
            w30['date_str'] = w30['date'].dt.strftime('%d %b')
            fig_ov = make_subplots(specs=[[{"secondary_y": True}]])
            fig_ov.add_trace(go.Bar(name='Sales', x=w30['date_str'], y=w30['sales'],
                                    marker_color='rgba(0,212,170,.45)'))
            fig_ov.add_trace(go.Bar(name='Receipts', x=w30['date_str'], y=w30['receipts'],
                                    marker_color='#6bcb77'))
            fig_ov.add_trace(go.Scatter(name='Outstanding', x=w30['date_str'], y=w30['outstanding'],
                                        mode='lines+markers', line=dict(color='#ff6b6b', width=2)),
                             secondary_y=True)
            fig_ov.update_layout(**ct(), height=320, barmode='group',
                                 title="Daily Sales vs Receipts · red line = total outstanding",
                                 legend=dict(font_size=10, orientation='h'))
            fig_ov.update_yaxes(gridcolor='rgba(255,255,255,.05)', secondary_y=False)
            fig_ov.update_yaxes(showgrid=False, secondary_y=True)
            st.plotly_chart(fig_ov, use_container_width=True)
        with f2:
            st.markdown(kpi("red", "Total Outstanding (Book)", inr(book_out),
                            "initial balances + all sales − all receipts"), unsafe_allow_html=True)
            if _rd_ov is not None and not _rd_ov.empty:
                _ag = _rz.groupby('Schedule').agg(
                    Sales=('Sales', 'sum'), Receipts=('Receipts', 'sum'),
                    Balance=('Balance', 'sum')).reset_index()
                _ag['Coll%'] = (_ag['Receipts'] / _ag['Sales'].replace(0, 1) * 100).round(0)
                _ag['⚡'] = _ag['Coll%'].apply(lambda x: "🔴" if x < 40 else ("🟡" if x < 75 else "🟢"))
                _ag = _ag.sort_values('Balance', ascending=False)
                for _c in ['Sales', 'Receipts', 'Balance']:
                    _ag[_c] = _ag[_c].apply(inr)
                _ag['Coll%'] = _ag['Coll%'].apply(lambda x: f"{x:.0f}%")
                _ag.columns = ['Area', 'Day Sales', 'Day Collected', 'Outstanding', 'Coll %', '⚡']
                st.dataframe(_ag, use_container_width=True, hide_index=True, height=250)
            else:
                st.caption("No receipts uploaded for the latest day yet — area scoreboard appears after the evening upload.")

        # ── ROW 4: ACTION LISTS ──
        st.markdown('<div class="sec">⚡ WHERE TO ACT TODAY</div>', unsafe_allow_html=True)
        a1, a2, a3 = st.columns(3)
        with a1:
            st.markdown("**🔴 Top 5 Debtors (whole book)**")
            _bulk_ov = get_running_balances_bulk(latest_str)
            if not _bulk_ov.empty:
                _top_d = _bulk_ov.nlargest(5, 'running_balance')[['Name', 'running_balance']].copy()
                _top_d['running_balance'] = _top_d['running_balance'].apply(inr)
                _top_d.columns = ['Customer', 'Owes']
                st.dataframe(_top_d, use_container_width=True, hide_index=True)
            st.caption("Collect here first — biggest money stuck.")
        with a2:
            st.markdown("**📈 Top 5 Credit Risers (this week)**")
            _rb_w = build_running_balance(ov_dates,
                                          (latest_ts - pd.Timedelta(days=6)).date(), latest_ts.date())
            if _rb_w is not None:
                _ris = _rb_w['cust_grp']
                _ris = _ris[_ris['Running_Balance'] > 0].nlargest(5, 'Running_Balance')[
                    ['Name', 'Running_Balance', 'Collection_Rate']].copy()
                _ris['Running_Balance'] = _ris['Running_Balance'].apply(inr)
                _ris['Collection_Rate'] = _ris['Collection_Rate'].apply(lambda x: f"{float(x):.0f}%")
                _ris.columns = ['Customer', '+Credit (7d)', 'Paid %']
                st.dataframe(_ris, use_container_width=True, hide_index=True)
            else:
                st.caption("No data this week.")
            st.caption("Buying fast, paying slow — set limits now.")
        with a3:
            st.markdown("**🚫 Bought Today, Paid ₹0**")
            if not zero_ov.empty:
                _z = zero_ov.nlargest(5, 'Balance')[['Name', 'Sales', 'Balance']].copy()
                _z['Sales'] = _z['Sales'].apply(inr)
                _z['Balance'] = _z['Balance'].apply(inr)
                _z.columns = ['Customer', 'Took Today', 'Total Owes']
                st.dataframe(_z, use_container_width=True, hide_index=True)
                st.caption(f"{len(zero_ov)} such customers — call before tomorrow's dispatch.")
            else:
                st.success("Everyone who bought today paid something.")


# ─────────────────────────────────────────────────────────────
# TAB 1 — TODAY
# ─────────────────────────────────────────────────────────────
with TAB_TODAY:
    st.markdown('<div class="sec">TODAY\'S SNAPSHOT</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5 = st.columns(5)
    for col, args in zip([c1,c2,c3,c4,c5],[
        ("green","Today Sales", inr(a['total_sales']), f"{len(sales)} lines"),
        ("green","Gross Profit 5%", inr(a['profit_potential']), "On today's dispatch"),
        ("yellow","Cash Collected", inr(a['total_receipts']), f"{a['total_receipts']/max(a['total_sales'],1)*100:.1f}% of sales"),
        ("red","Total Outstanding", inr(a['total_balance']), "All customers"),
        ("red","Profit At Risk", inr(a['profit_potential']-a['profit_realized']), "Uncollected margin"),
    ]):
        with col: st.markdown(kpi(*args), unsafe_allow_html=True)

    st.markdown('<div class="sec">WHERE IS MONEY STUCK?</div>', unsafe_allow_html=True)
    ca, cb = st.columns([3,2])
    with ca:
        top20 = a['customers'].nlargest(20,'Balance')
        fig = px.bar(top20, x='Balance', y='Name', orientation='h',
                     color='Balance', color_continuous_scale=["#ffd93d","#ff6b6b","#c0392b"],
                     title="Top 20 Customers — Outstanding Balance",
                     labels={'Balance':'₹','Name':''})
        fig.update_layout(**ct(), height=420, coloraxis_showscale=False,
                          yaxis=dict(tickfont=dict(size=10)))
        fig.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fig, use_container_width=True)
    with cb:
        fig2 = px.pie(a['area'], names='Schedule', values='Balance', hole=.55,
                      title="Outstanding by Area",
                      color_discrete_sequence=px.colors.sequential.Teal)
        fig2.update_layout(**ct(), height=240, showlegend=True, legend=dict(font_size=10))
        st.plotly_chart(fig2, use_container_width=True)
        ad = a['area'][['Schedule','Receipts','Balance','Collection_Eff']].copy()
        ad.columns=['Area','Collected','Outstanding','Coll %']
        ad['Collected']   = ad['Collected'].apply(inr)
        ad['Outstanding'] = ad['Outstanding'].apply(inr)
        ad['Coll %']      = ad['Coll %'].apply(lambda x: f"{x}%")
        st.dataframe(ad, use_container_width=True, hide_index=True)

    st.markdown('<div class="sec">CUSTOMER HEALTH</div>', unsafe_allow_html=True)
    disp = a['customers'][['Schedule','Name','OB','Sales','Receipts','Balance','status','collection_rate']].copy()

    # Calculate Running Balance for each customer (2 bulk queries, not 4 per row)
    if MONGO_AVAILABLE and active_date:
        _prev_day = (datetime.strptime(active_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        _rb_curr = get_running_balances_bulk(active_date)
        _rb_prev = get_running_balances_bulk(_prev_day)
        _curr_map = dict(zip(_rb_curr['Name'], _rb_curr['running_balance']))
        _prev_map = dict(zip(_rb_prev['Name'], _rb_prev['running_balance']))
        disp = disp.reset_index(drop=True)
        disp['Prev_Running_Balance'] = disp['Name'].map(_prev_map).fillna(0)
        disp['Curr_Running_Balance'] = disp['Name'].map(_curr_map).fillna(0)
    else:
        disp['Prev_Running_Balance'] = 0
        disp['Curr_Running_Balance'] = disp['Balance']

    disp.columns = ['Area','Customer','Opening','Today Sales','Collected','Balance','Status','Pay %','Prev Running Balance','Curr Running Balance']
    for c in ['Opening','Today Sales','Collected','Balance','Prev Running Balance','Curr Running Balance']:
        disp[c] = disp[c].apply(inr)
    disp['Pay %'] = disp['Pay %'].apply(lambda x: f"{x}%")
    disp['Status'] = disp['Status'].astype(str)  # guard against float dtype when receipts empty
    t1,t2,t3,t4 = st.tabs([f"All ({len(disp)})","🔴 Not Paid","🟡 Partial","🟢 Good"])
    with t1: st.dataframe(disp, use_container_width=True, hide_index=True, height=300)
    with t2: st.dataframe(disp[disp['Status'].str.contains('No Payment|Low', na=False)], use_container_width=True, hide_index=True, height=300)
    with t3: st.dataframe(disp[disp['Status'].str.contains('Partial', na=False)], use_container_width=True, hide_index=True, height=300)
    with t4: st.dataframe(disp[disp['Status'].str.contains('Good|Cleared', na=False)], use_container_width=True, hide_index=True, height=300)

    st.markdown('<div class="sec">SALES BREAKDOWN</div>', unsafe_allow_html=True)
    s1,s2 = st.columns(2)
    with s1:
        fi = px.bar(a['sales_by_item'].reset_index(), x='Amount', y='Item', orientation='h',
                    color='Amount', color_continuous_scale='Teal', title='Revenue by Item',
                    labels={'Amount':'₹','Item':''})
        fi.update_layout(**ct(), height=300, coloraxis_showscale=False)
        fi.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fi, use_container_width=True)
    with s2:
        fc = px.bar(a['sales_by_cust'].head(15).reset_index(), x='Amount', y='Name', orientation='h',
                    color='Amount', color_continuous_scale='Purp', title="Top 15 Customers by Purchase",
                    labels={'Amount':'₹','Name':''})
        fc.update_layout(**ct(), height=300, coloraxis_showscale=False)
        fc.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fc, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# TAB — REPORTS (Day/Period Summary · Credits Increasing · Account Analysis)
# ─────────────────────────────────────────────────────────────
with TAB_REPORTS:
    monthly_expense = get_monthly_expense()

    if not MONGO_AVAILABLE:
        st.warning("Reports need MongoDB. Session-only mode has limited history.")

    # ── ONE-TIME SETUP: INITIAL RUNNING BALANCES (BULK) ──────────
    with st.expander("🏦 Initial Running Balances — one-time setup (balance before 8 May)"):
        st.caption("Enter each customer's outstanding balance as it stood before the first upload (8 May). "
                   "The app carries it forward automatically: Running Balance = Initial + Sales − Receipts.")
        if MONGO_AVAILABLE:
            _cust_docs = list(db.customers.find({}, {"_id": 0, "name": 1, "area": 1}))
            _init_map = {d.get("customer"): float(d.get("initial_balance", 0) or 0)
                         for d in db.running_balance.find({}, {"_id": 0})}
            if _cust_docs:
                _base = pd.DataFrame(_cust_docs).rename(columns={"name": "Customer", "area": "Area"})
                _base = _base[~_base['Customer'].isin(EXCLUDE_CUSTOMERS)]
                _base['Initial Running Balance'] = _base['Customer'].map(_init_map).fillna(0.0)
                _base = _base[['Area', 'Customer', 'Initial Running Balance']].sort_values(
                    ['Area', 'Customer']).reset_index(drop=True)
                _edited = st.data_editor(
                    _base, hide_index=True, use_container_width=True, height=380,
                    disabled=['Area', 'Customer'], key="init_rb_editor",
                    column_config={"Initial Running Balance": st.column_config.NumberColumn(
                        "Initial Running Balance (₹)", min_value=0, step=500, format="%.0f")})
                if st.button("💾 Save All Initial Balances", use_container_width=True):
                    _saved = 0
                    for _, _row in _edited.iterrows():
                        _val = float(_row['Initial Running Balance'] or 0)
                        if _val != _init_map.get(_row['Customer'], 0):
                            db.running_balance.update_one(
                                {"customer": _row['Customer']},
                                {"$set": {"customer": _row['Customer'],
                                          "initial_balance": _val, "date": "initial"}},
                                upsert=True)
                            _saved += 1
                    st.success(f"✅ Saved {_saved} balance(s). All reports now include them.")
            else:
                st.info("Import some data first to see customers.")
        else:
            st.info("MongoDB required to store initial balances.")

    # ══ SECTION A — DAY & PERIOD SUMMARY ═════════════════════════
    st.markdown('<div class="sec">A · DAY & PERIOD SUMMARY</div>', unsafe_allow_html=True)
    ser = build_outstanding_series()
    if ser is None or ser.empty:
        st.info("No data yet — upload sales/receipts first.")
    else:
        _def_date = (datetime.strptime(active_date, "%Y-%m-%d").date()
                     if active_date else ser['date'].max().date())
        rep_date = st.date_input("Report Date", value=_def_date, key="rep_date")
        rep_ts = pd.Timestamp(rep_date)

        day_row   = ser[ser['date'] == rep_ts]
        day_sales = float(day_row['sales'].sum())
        day_rcpts = float(day_row['receipts'].sum())
        day_pending = day_sales - day_rcpts
        upto = ser[ser['date'] <= rep_ts]
        overall_out = float(upto['outstanding'].iloc[-1]) if not upto.empty else 0.0
        day_net = day_sales * MARGIN_PCT - monthly_expense / 30

        c1, c2, c3, c4, c5 = st.columns(5)
        for col, args in zip([c1, c2, c3, c4, c5], [
            ("green",  "Day Sales",        inr(day_sales),   str(rep_date)),
            ("green",  "Day Receipts",     inr(day_rcpts),
             f"{day_rcpts/max(day_sales,1)*100:.1f}% of sales"),
            ("yellow", "Day Pending",      inr(day_pending), "Sales − Receipts today"),
            ("red",    "Overall Balance",  inr(overall_out), "All customers, up to this date"),
            ("green" if day_net >= 0 else "red", "Day Net Profit", inr(day_net),
             f"5% margin − {inr(monthly_expense/30)} expense"),
        ]):
            with col: st.markdown(kpi(*args), unsafe_allow_html=True)

        # Period strip: 1 week / 1 month / 3 months ending on report date
        _rows = []
        for _label, _nd in [("1 Day", 1), ("1 Week", 7), ("1 Month", 30), ("3 Months", 90)]:
            _w = ser[(ser['date'] > rep_ts - pd.Timedelta(days=_nd)) & (ser['date'] <= rep_ts)]
            _s = float(_w['sales'].sum()); _r = float(_w['receipts'].sum())
            _gross = _s * MARGIN_PCT
            _exp = monthly_expense / 30 * _nd
            _rows.append({
                "Period": _label, "Sales": inr(_s), "Receipts": inr(_r),
                "Credit Change": inr(_s - _r),
                "Coll %": f"{_r/max(_s,1)*100:.1f}%",
                "Gross Profit (5%)": inr(_gross), "Expenses": inr(_exp),
                "Net Profit": inr(_gross - _exp),
            })
        st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)
        st.caption(f"Break-even sales: {inr(monthly_expense/MARGIN_PCT)}/month "
                   f"≈ {inr(monthly_expense/MARGIN_PCT/30)}/day (expense {inr(monthly_expense)}/month ÷ 5% margin)")

        t1, t2 = st.columns(2)
        _w90 = ser[(ser['date'] > rep_ts - pd.Timedelta(days=90)) & (ser['date'] <= rep_ts)].copy()
        _w90['date_str'] = _w90['date'].dt.strftime('%Y-%m-%d')
        with t1:
            fig_out = px.area(_w90, x='date_str', y='outstanding',
                              title="Overall Outstanding Balance — last 3 months",
                              labels={'date_str': 'Date', 'outstanding': '₹ Outstanding'},
                              color_discrete_sequence=['#ff6b6b'])
            fig_out.update_layout(**ct(), height=300)
            fig_out.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
            fig_out.update_yaxes(gridcolor='rgba(255,255,255,.05)')
            st.plotly_chart(fig_out, use_container_width=True)
        with t2:
            fig_sr = go.Figure()
            fig_sr.add_trace(go.Bar(name='Sales', x=_w90['date_str'], y=_w90['sales'],
                                    marker_color='rgba(0,212,170,.45)'))
            fig_sr.add_trace(go.Bar(name='Receipts', x=_w90['date_str'], y=_w90['receipts'],
                                    marker_color='#6bcb77'))
            fig_sr.add_hline(y=monthly_expense/MARGIN_PCT/30, line_dash="dash", line_color="#ffd93d",
                             annotation_text="Break-even/day", annotation_font_color="#ffd93d")
            fig_sr.update_layout(**ct(), height=300, barmode='group',
                                 title="Daily Sales vs Receipts — last 3 months",
                                 legend=dict(font_size=10))
            fig_sr.update_yaxes(gridcolor='rgba(255,255,255,.05)')
            st.plotly_chart(fig_sr, use_container_width=True)

        # ── QUICK SUMMARY — PER CUSTOMER · DOWNLOADABLE PDF ──────
        st.markdown('<div class="sec">QUICK SUMMARY — PER CUSTOMER · PDF DOWNLOAD</div>', unsafe_allow_html=True)
        st.caption("Per customer: period sales, running balance (before the day), that day's sales & receipts, "
                   "and overall balance (after the day). Uses the Report Date above as 'that day'.")
        q1, q2, q3, q4 = st.columns([2, 2, 3, 2])
        with q1:
            qs_preset = st.selectbox("Period for 'Overall Sale'",
                                     ["1 Week", "1 Month", "3 Months", "Custom"], key="qs_preset")
        if qs_preset == "Custom":
            with q2:
                qs_from = st.date_input("Period From", value=rep_date - timedelta(days=6), key="qs_from")
        else:
            qs_from = rep_date - timedelta(days={"1 Week": 7, "1 Month": 30, "3 Months": 90}[qs_preset] - 1)
            with q2:
                st.caption(f"Period: **{qs_from} → {rep_date}**")
        with q3:
            _qs_known = sorted(set(db.areas.distinct("name")) - EXCLUDE_AREAS) if MONGO_AVAILABLE else []
            qs_areas = st.multiselect("Area filter", _qs_known, default=_qs_known,
                                      key="qs_areas") if _qs_known else []
        with q4:
            qs_name = st.text_input("Search name", key="qs_name")
        qs_hide_zero = st.checkbox("Hide customers with no activity and zero balance",
                                   value=True, key="qs_zero")

        rep_date_str = rep_date.strftime("%Y-%m-%d")
        _qprev_str = (rep_date - timedelta(days=1)).strftime("%Y-%m-%d")

        _qday_s, _qday_r = load_data(rep_date_str)
        _day_sales_map = (_qday_s.groupby('Name')['Amount'].sum().to_dict()
                          if _qday_s is not None and not _qday_s.empty else {})
        _day_rcpt_map, _qs_area_map = {}, {}
        if _qday_r is not None and not _qday_r.empty:
            _day_rcpt_map = dict(zip(_qday_r['Name'],
                                     pd.to_numeric(_qday_r['Receipts'], errors='coerce').fillna(0)))
            _qs_area_map.update(dict(zip(_qday_r['Name'], _qday_r['Schedule'])))

        _qs_period = build_running_balance(get_all_dates(), qs_from, rep_date)
        _p_sales_map = {}
        if _qs_period is not None:
            _pg = _qs_period['cust_grp']
            _p_sales_map = dict(zip(_pg['Name'], _pg['Period_Sales']))
            for _n, _a in zip(_pg['Name'], _pg['Area']):
                _qs_area_map.setdefault(_n, _a)
        if MONGO_AVAILABLE:
            for _doc in db.customers.find({}, {"_id": 0, "name": 1, "area": 1}):
                _qs_area_map.setdefault(_doc.get("name"), _doc.get("area", ""))

        _rb_open  = get_running_balances_bulk(_qprev_str)
        _rb_close = get_running_balances_bulk(rep_date_str)
        _open_map  = dict(zip(_rb_open['Name'], _rb_open['running_balance'])) if not _rb_open.empty else {}
        _close_map = dict(zip(_rb_close['Name'], _rb_close['running_balance'])) if not _rb_close.empty else {}

        _qnames = ((set(_p_sales_map) | set(_day_sales_map) | set(_day_rcpt_map) | set(_close_map))
                   - EXCLUDE_CUSTOMERS)
        qdf = pd.DataFrame([{
            "Area": str(_qs_area_map.get(n, "") or ""),
            "Name": n,
            "Period_Sales": float(_p_sales_map.get(n, 0)),
            "Running_Balance": float(_open_map.get(n, 0)),
            "Day_Sales": float(_day_sales_map.get(n, 0)),
            "Day_Receipts": float(_day_rcpt_map.get(n, 0)),
            "Overall_Balance": float(_close_map.get(n, 0)),
        } for n in sorted(_qnames)])

        if qdf.empty:
            st.info("No customer data for this selection.")
        else:
            if qs_areas:
                qdf = qdf[qdf['Area'].isin(qs_areas) | (qdf['Area'] == "")]
            if qs_name.strip():
                qdf = qdf[qdf['Name'].str.contains(qs_name.strip(), case=False, na=False)]
            if qs_hide_zero:
                qdf = qdf[(qdf[['Period_Sales', 'Day_Sales', 'Day_Receipts', 'Overall_Balance']]
                           .abs().sum(axis=1)) > 0]
            qdf = qdf.sort_values('Overall_Balance', ascending=False).reset_index(drop=True)

            if qdf.empty:
                st.info("No rows match the filters.")
            else:
                _q_show = qdf.copy()
                for _c in ['Period_Sales', 'Running_Balance', 'Day_Sales', 'Day_Receipts', 'Overall_Balance']:
                    _q_show[_c] = _q_show[_c].apply(inr)
                _q_show.columns = ['Area', 'Customer', f'Period Sales ({qs_from}→{rep_date})',
                                   'Running Balance (before day)', 'Day Sales', 'Day Receipts',
                                   'Overall Balance']
                st.dataframe(_q_show, use_container_width=True, hide_index=True, height=360)
                st.caption(f"**{len(qdf)} customers** · Period Sales {inr(qdf['Period_Sales'].sum())} · "
                           f"Day Sales {inr(qdf['Day_Sales'].sum())} · Day Receipts {inr(qdf['Day_Receipts'].sum())} · "
                           f"Overall Balance {inr(qdf['Overall_Balance'].sum())}")

                if FPDF_AVAILABLE:
                    _q_title = ["SVC VEGETABLES", "QUICK SUMMARY — PER CUSTOMER",
                                f"Day: {rep_date}   Period: {qs_from} to {rep_date}",
                                f"Areas: {', '.join(qs_areas) if qs_areas else 'All'}"]
                    _q_a4 = build_summary_pdf(qdf, _q_title, fmt="a4")
                    _q_th = build_summary_pdf(qdf, _q_title, fmt="thermal")
                    d1, d2 = st.columns(2)
                    with d1:
                        st.download_button("⬇️ Download PDF (A4)", data=_q_a4,
                                           file_name=f"quick_summary_A4_{rep_date_str}.pdf",
                                           mime="application/pdf", use_container_width=True,
                                           key="qs_dl_a4")
                    with d2:
                        st.download_button("⬇️ Download PDF (80mm Thermal)", data=_q_th,
                                           file_name=f"quick_summary_80mm_{rep_date_str}.pdf",
                                           mime="application/pdf", use_container_width=True,
                                           key="qs_dl_th")
                else:
                    st.error("PDF library missing. Run: `pip install fpdf2`")

    # ══ SECTION B — CREDITS INCREASING ═══════════════════════════
    st.markdown('<div class="sec">B · CREDITS INCREASING — THIS PERIOD vs PREVIOUS PERIOD</div>', unsafe_allow_html=True)
    st.caption("Customers whose outstanding credit GREW in the selected period, compared with the equal period before it.")
    all_dates_rep = get_all_dates()
    if not all_dates_rep:
        st.info("No data yet.")
    else:
        b1, b2, b3, b4 = st.columns([2, 2, 3, 2])
        with b1:
            ci_preset = st.selectbox("Period", ["1 Week", "1 Day", "1 Month", "Custom"], key="ci_preset")
        _ci_to_default = (datetime.strptime(active_date, "%Y-%m-%d").date()
                          if active_date else date.today())
        if ci_preset == "Custom":
            with b2:
                ci_from = st.date_input("From", value=_ci_to_default - timedelta(days=6), key="ci_from")
            with b3:
                ci_to = st.date_input("To", value=_ci_to_default, key="ci_to")
        else:
            _nd = {"1 Day": 1, "1 Week": 7, "1 Month": 30}[ci_preset]
            with b2:
                ci_to = st.date_input("Ending on", value=_ci_to_default, key="ci_to2")
            ci_from = ci_to - timedelta(days=_nd - 1)
            with b3:
                st.caption(f"Current: **{ci_from} → {ci_to}**")
        _plen = (ci_to - ci_from).days + 1
        prev_to = ci_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=_plen - 1)
        with b4:
            ci_name_q = st.text_input("Search customer", key="ci_name")

        _known_areas = sorted(set(db.areas.distinct("name")) - EXCLUDE_AREAS) if MONGO_AVAILABLE else []
        ci_areas = st.multiselect("Filter by Area / Schedule", _known_areas,
                                  default=_known_areas, key="ci_areas") if _known_areas else []

        ci_cur = build_running_balance(all_dates_rep, ci_from, ci_to)
        ci_prv = build_running_balance(all_dates_rep, prev_from, prev_to)

        if ci_cur is None:
            st.warning(f"No data between {ci_from} and {ci_to}.")
        else:
            cur_g = ci_cur['cust_grp'][['Name', 'Area', 'Period_Sales', 'Period_Receipts',
                                        'Running_Balance', 'Collection_Rate']].copy()
            cur_g = cur_g.rename(columns={'Running_Balance': 'This_Delta'})
            if ci_prv is not None:
                prv_g = ci_prv['cust_grp'][['Name', 'Running_Balance']].rename(
                    columns={'Running_Balance': 'Prev_Delta'})
                cur_g = cur_g.merge(prv_g, on='Name', how='left')
            else:
                cur_g['Prev_Delta'] = 0.0
            cur_g['Prev_Delta'] = pd.to_numeric(cur_g['Prev_Delta'], errors='coerce').fillna(0)
            cur_g['Change'] = cur_g['This_Delta'] - cur_g['Prev_Delta']

            _rb_now = get_running_balances_bulk(ci_to.strftime("%Y-%m-%d"))
            _rb_map = dict(zip(_rb_now['Name'], _rb_now['running_balance'])) if not _rb_now.empty else {}
            cur_g['Current_RB'] = cur_g['Name'].map(_rb_map).fillna(0)

            if ci_areas:
                cur_g = cur_g[cur_g['Area'].isin(ci_areas)]
            if ci_name_q.strip():
                cur_g = cur_g[cur_g['Name'].str.contains(ci_name_q.strip(), case=False, na=False)]

            growing = cur_g[cur_g['This_Delta'] > 0].sort_values('This_Delta', ascending=False)
            _tot_this = float(cur_g['This_Delta'].clip(lower=0).sum())
            _tot_prev = float(cur_g['Prev_Delta'].clip(lower=0).sum())

            k1, k2, k3, k4 = st.columns(4)
            for col, args in zip([k1, k2, k3, k4], [
                ("red",    "Customers w/ Growing Credit", str(len(growing)),
                 f"out of {len(cur_g)} active"),
                ("red",    "New Credit This Period", inr(_tot_this),
                 f"{ci_from} → {ci_to}"),
                ("yellow", "New Credit Prev Period", inr(_tot_prev),
                 f"{prev_from} → {prev_to}"),
                ("red" if _tot_this > _tot_prev else "green", "Trend vs Prev Period",
                 f"{'▲' if _tot_this > _tot_prev else '▼'} {inr(abs(_tot_this - _tot_prev))}",
                 "Credit is rising!" if _tot_this > _tot_prev else "Credit growth slowing"),
            ]):
                with col: st.markdown(kpi(*args), unsafe_allow_html=True)

            if growing.empty:
                st.success("✅ No customer added credit in this period (with current filters).")
            else:
                ci_disp = growing.copy()
                ci_disp['Trend'] = ci_disp['Change'].apply(
                    lambda x: "🔺 Rising faster" if x > 0 else ("➖ Same" if x == 0 else "🔻 Slowing"))
                for _c in ['Period_Sales', 'Period_Receipts', 'Prev_Delta', 'This_Delta', 'Change', 'Current_RB']:
                    ci_disp[_c] = ci_disp[_c].apply(inr)
                ci_disp['Collection_Rate'] = ci_disp['Collection_Rate'].apply(lambda x: f"{float(x):.1f}%")
                ci_disp = ci_disp[['Area', 'Name', 'Period_Sales', 'Period_Receipts',
                                   'Prev_Delta', 'This_Delta', 'Change', 'Trend',
                                   'Current_RB', 'Collection_Rate']]
                ci_disp.columns = ['Area', 'Customer', 'Sales', 'Receipts',
                                   'Prev Period +Credit', 'This Period +Credit', 'Change', 'Trend',
                                   'Total Running Balance', 'Coll %']
                st.dataframe(ci_disp, use_container_width=True, hide_index=True, height=380)

                _top15 = growing.nlargest(15, 'This_Delta')
                fig_ci = px.bar(_top15, x='This_Delta', y='Name', orientation='h',
                                color='Collection_Rate',
                                color_continuous_scale=[(0, '#ff6b6b'), (.5, '#ffd93d'), (1, '#6bcb77')],
                                range_color=[0, 100],
                                title="Top 15 — Credit Added This Period (colour = collection rate)",
                                labels={'This_Delta': 'Credit Added (₹)', 'Name': ''})
                fig_ci.update_layout(**ct(), height=420, coloraxis_colorbar=dict(title='Coll %'))
                fig_ci.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_ci, use_container_width=True)

    # ══ SECTION C — ACCOUNT ANALYSIS ═════════════════════════════
    st.markdown('<div class="sec">C · ACCOUNT ANALYSIS — ONE CUSTOMER IN DEPTH</div>', unsafe_allow_html=True)
    if not MONGO_AVAILABLE:
        st.info("MongoDB required for account analysis.")
    else:
        _excl_acct = set(db.receipts.distinct("Name", {"Schedule": {"$in": list(EXCLUDE_AREAS)}}))
        _acct_names = sorted((set(db.sales.distinct("Name")) | set(db.receipts.distinct("Name")))
                             - EXCLUDE_CUSTOMERS - _excl_acct)
        if not _acct_names:
            st.info("No customers yet.")
        else:
            acct = st.selectbox("Select Account", _acct_names, key="acct_sel")
            _sd = list(db.sales.aggregate([
                {"$match": {"Name": acct}},
                {"$group": {"_id": "$date", "sales": {"$sum": "$Amount"}}}]))
            _rd = list(db.receipts.aggregate([
                {"$match": {"Name": acct}},
                {"$group": {"_id": "$date", "receipts": {"$sum": "$Receipts"}}}]))
            _init_doc = db.running_balance.find_one({"customer": acct})
            _acct_init = float(_init_doc.get("initial_balance", 0)) if _init_doc else 0.0

            _adf = pd.merge(
                pd.DataFrame(_sd).rename(columns={"_id": "date"}) if _sd else pd.DataFrame(columns=['date', 'sales']),
                pd.DataFrame(_rd).rename(columns={"_id": "date"}) if _rd else pd.DataFrame(columns=['date', 'receipts']),
                on="date", how="outer")
            if _adf.empty:
                st.info(f"No transactions for **{acct}**.")
            else:
                _adf['sales']    = pd.to_numeric(_adf.get('sales'), errors='coerce').fillna(0)
                _adf['receipts'] = pd.to_numeric(_adf.get('receipts'), errors='coerce').fillna(0)
                _adf['date'] = pd.to_datetime(_adf['date'], errors='coerce')
                _adf = _adf.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
                _adf['daily_change'] = _adf['sales'] - _adf['receipts']
                _adf['running_balance'] = (_acct_init + _adf['daily_change'].cumsum()).clip(lower=0)

                _tot_s = float(_adf['sales'].sum()); _tot_r = float(_adf['receipts'].sum())
                _cur_rb = float(_adf['running_balance'].iloc[-1])
                _active_days = int((_adf['sales'] > 0).sum())
                _pay_dates = _adf[_adf['receipts'] > 0]['date']
                _days_since_pay = (_adf['date'].max() - _pay_dates.max()).days if not _pay_dates.empty else None
                _streak = 0
                for _ch in reversed(_adf['daily_change'].tolist()):
                    if _ch > 0: _streak += 1
                    else: break

                g1, g2, g3, g4, g5, g6 = st.columns(6)
                for col, args in zip([g1, g2, g3, g4, g5, g6], [
                    ("red" if _cur_rb > 0 else "green", "Running Balance", inr(_cur_rb),
                     f"incl. {inr(_acct_init)} initial"),
                    ("green",  "Total Sales", inr(_tot_s), f"{_active_days} buying day(s)"),
                    ("green",  "Total Receipts", inr(_tot_r),
                     f"{_tot_r/max(_tot_s,1)*100:.1f}% collected"),
                    ("yellow", "Avg Purchase/Day", inr(_tot_s / max(_active_days, 1)),
                     "on days they bought"),
                    ("red" if (_days_since_pay or 0) > 7 else "green", "Days Since Payment",
                     str(_days_since_pay) if _days_since_pay is not None else "Never paid",
                     f"last: {_pay_dates.max().strftime('%d %b') if not _pay_dates.empty else '—'}"),
                    ("red" if _streak >= 3 else "yellow" if _streak > 0 else "green",
                     "Credit Growth Streak", f"{_streak} day(s)",
                     "consecutive days balance rose"),
                ]):
                    with col: st.markdown(kpi(*args), unsafe_allow_html=True)

                ac1, ac2 = st.columns([3, 2])
                with ac1:
                    _adf['date_str'] = _adf['date'].dt.strftime('%Y-%m-%d')
                    fig_acct = px.area(_adf, x='date_str', y='running_balance',
                                       title=f"{acct} — Running Balance Over Time",
                                       labels={'date_str': 'Date', 'running_balance': '₹ Outstanding'},
                                       color_discrete_sequence=['#c084fc'])
                    fig_acct.update_layout(**ct(), height=300)
                    fig_acct.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                    fig_acct.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                    st.plotly_chart(fig_acct, use_container_width=True)
                with ac2:
                    _adf['Month'] = _adf['date'].dt.strftime('%b %Y')
                    _mon = _adf.groupby('Month', sort=False).agg(
                        Sales=('sales', 'sum'), Receipts=('receipts', 'sum'),
                        Net_Change=('daily_change', 'sum')).reset_index()
                    for _c in ['Sales', 'Receipts', 'Net_Change']:
                        _mon[_c] = _mon[_c].apply(inr)
                    _mon.columns = ['Month', 'Sales', 'Receipts', 'Credit Change']
                    st.markdown("**Monthly Summary**")
                    st.dataframe(_mon, use_container_width=True, hide_index=True, height=260)
                st.caption("Full day-by-day debit/credit entries for this customer are in the **📒 Ledger** tab.")


# ─────────────────────────────────────────────────────────────
# TAB — PRINT BILLS (80mm THERMAL)
# ─────────────────────────────────────────────────────────────
with TAB_BILLS:
    st.markdown('<div class="sec">🖨️ CUSTOMER BILLS — 80mm (3-INCH) THERMAL PRINTER</div>', unsafe_allow_html=True)
    st.caption("One bill per customer, one page each — the printer's auto-cutter separates them. "
               "Print the PDF at **100% scale / actual size** (no fit-to-page) on the GOBBLER 80mm printer.")

    if not FPDF_AVAILABLE:
        st.error("PDF library missing. Run: `pip install fpdf2` and restart the app.")
    else:
        _bill_def = (datetime.strptime(active_date, "%Y-%m-%d").date()
                     if active_date else date.today())
        pb1, pb2, pb3 = st.columns(3)
        with pb1:
            bill_date = st.date_input("Bill Date", value=_bill_def, key="bill_date")
        bill_date_str = bill_date.strftime("%Y-%m-%d")

        bill_sdf, bill_rdf = load_data(bill_date_str)
        if bill_sdf is None or bill_sdf.empty:
            st.info(f"No sales data for {bill_date_str}. Upload/import sales for this date first.")
        else:
            _bnames = sorted(set(bill_sdf['Name'].unique()) - EXCLUDE_CUSTOMERS)
            _bamap = {}
            if MONGO_AVAILABLE:
                for _doc in db.customers.find({}, {"_id": 0, "name": 1, "area": 1}):
                    _bamap[_doc.get("name")] = _doc.get("area", "")
            if bill_rdf is not None and not bill_rdf.empty:
                _bamap.update(dict(zip(bill_rdf['Name'], bill_rdf['Schedule'])))
            _bareas = sorted({str(_bamap.get(n, "")) for n in _bnames if _bamap.get(n, "")})

            with pb2:
                bill_area = st.selectbox("Area / Schedule", ["All Areas"] + _bareas, key="bill_area")
            with pb3:
                bill_cust = st.selectbox("Single Customer (optional)",
                                         ["All Customers"] + _bnames, key="bill_cust")

            if bill_cust != "All Customers":
                _n_bills = 1
            elif bill_area != "All Areas":
                _n_bills = sum(1 for n in _bnames if _bamap.get(n, "") == bill_area)
            else:
                _n_bills = len(_bnames)
            st.caption(f"**{_n_bills}** bill(s) will be generated · each bill shows: previous day cash, "
                       f"opening balance, item lines (bags/kgs/rate/amount), today's total, "
                       f"closing balance (opening + today's sales) and running balance "
                       f"(prev running bal + today's sales) — hand to the buyer in the evening "
                       f"when collecting cash.")

            if st.button("🖨️ Generate Bills PDF", type="primary", use_container_width=True):
                with st.spinner("Building bills…"):
                    _pdf_bytes, _n = build_bills_pdf(
                        bill_date_str,
                        area=None if bill_area == "All Areas" else bill_area,
                        customer=None if bill_cust == "All Customers" else bill_cust)
                if _pdf_bytes:
                    _tag = (bill_cust if bill_cust != "All Customers"
                            else bill_area if bill_area != "All Areas" else "ALL")
                    _fname = f"bills_{_tag}_{bill_date_str}.pdf".replace(" ", "_").replace("/", "-")
                    st.session_state["bills_pdf"] = (_fname, _pdf_bytes, _n)
                else:
                    st.session_state.pop("bills_pdf", None)
                    st.warning("No bills matched that selection.")

            if "bills_pdf" in st.session_state:
                _fname, _data, _n = st.session_state["bills_pdf"]
                st.success(f"✅ {_n} bill(s) ready — {_fname}")
                st.download_button("⬇️ Download Bills PDF (backup)", data=_data, file_name=_fname,
                                   mime="application/pdf", use_container_width=True,
                                   key="bills_dl")

            # ── DIRECT ESC/POS PRINTING — no PDF, no driver, auto-cut ──
            st.markdown('<div class="sec">🖨️ DIRECT PRINT — ESC/POS (USB or LAN)</div>', unsafe_allow_html=True)
            if not ESCPOS_AVAILABLE:
                st.error("Direct printing needs: `pip install python-escpos pypdfium2 pyusb libusb-package` "
                         "— then restart the app.")
            else:
                st.caption("Prints straight to the GOBBLER — no PDF scaling, no driver, "
                           "auto-cutter fires after every bill.")
                conn_kind = st.radio("Connection", ["USB (cable)", "LAN (network)"],
                                     horizontal=True, key="printer_conn")

                if conn_kind == "USB (cable)":
                    _vid, _pid = get_printer_usb()
                    u1, u2 = st.columns([1, 2])
                    with u1:
                        if st.button("🔍 Detect USB printer", use_container_width=True, key="usb_detect"):
                            try:
                                _devs = detect_usb_printers()
                            except Exception as _de:
                                _devs = []
                                st.error(f"USB scan failed: {_de}")
                            _printers = [d for d in _devs if d["printer"]]
                            if _printers:
                                _d0 = _printers[0]
                                set_printer_usb(_d0["vid"], _d0["pid"])
                                st.success(f"✅ Found: {_d0['name']} "
                                           f"(vid=0x{_d0['vid']:04x}, pid=0x{_d0['pid']:04x}) — saved.")
                                _vid, _pid = _d0["vid"], _d0["pid"]
                            elif _devs:
                                st.warning("No printer-class device found. Devices seen: " +
                                           ", ".join(f"{d['name']} (0x{d['vid']:04x}:0x{d['pid']:04x})"
                                                     for d in _devs[:6]) +
                                           " — plug the printer in and switch it on, then detect again.")
                            else:
                                st.warning("No USB devices visible — plug the printer in, switch it on, "
                                           "and click Detect again.")
                    with u2:
                        if _vid:
                            st.caption(f"Saved printer: vid=0x{_vid:04x} · pid=0x{_pid:04x} — ready to print.")
                        else:
                            st.caption("No USB printer saved yet — plug it in and click Detect (one-time setup).")

                    if st.button(f"🖨️ Print {_n_bills} bill(s) NOW via USB", type="primary",
                                 use_container_width=True, key="print_now_usb",
                                 disabled=not _vid):
                        with st.spinner("Building bills…"):
                            _pb, _pn = build_bills_pdf(
                                bill_date_str,
                                area=None if bill_area == "All Areas" else bill_area,
                                customer=None if bill_cust == "All Customers" else bill_cust)
                        if not _pb:
                            st.warning("No bills matched that selection.")
                        else:
                            try:
                                with st.spinner(f"Printing {_pn} bill(s)…"):
                                    _imgs = pdf_to_thermal_images(_pb)
                                    print_images_escpos_usb(_imgs, _vid, _pid)
                                st.success(f"✅ {_pn} bill(s) printed via USB — each one auto-cut.")
                            except Exception as _pe:
                                st.error(f"USB printing failed: {_pe}. Make sure the printer is on and "
                                         f"NOT added in macOS System Settings → Printers (the system can "
                                         f"lock the USB port); unplug/replug and Detect again. "
                                         f"The PDF download below always works as backup.")

                else:  # LAN
                    dp1, dp2 = st.columns([3, 1])
                    with dp1:
                        printer_ip = st.text_input("Printer IP address", value=get_printer_ip(),
                                                   placeholder="e.g. 192.168.0.100", key="printer_ip_in")
                    with dp2:
                        printer_port = st.number_input("Port", value=9100, min_value=1, max_value=65535,
                                                       key="printer_port")
                    if st.button(f"🖨️ Print {_n_bills} bill(s) NOW via LAN", type="primary",
                                 use_container_width=True, key="print_now"):
                        if not printer_ip.strip():
                            st.error("Enter the printer's IP address first (print the printer self-test page to find it).")
                        else:
                            set_printer_ip(printer_ip.strip())
                            with st.spinner("Building bills…"):
                                _pb, _pn = build_bills_pdf(
                                    bill_date_str,
                                    area=None if bill_area == "All Areas" else bill_area,
                                    customer=None if bill_cust == "All Customers" else bill_cust)
                            if not _pb:
                                st.warning("No bills matched that selection.")
                            else:
                                try:
                                    with st.spinner(f"Printing {_pn} bill(s)…"):
                                        _imgs = pdf_to_thermal_images(_pb)
                                        print_images_escpos(_imgs, printer_ip.strip(), int(printer_port))
                                    st.success(f"✅ {_pn} bill(s) sent to {printer_ip} — each one auto-cut.")
                                except Exception as _pe:
                                    st.error(f"Printing failed: {_pe}. Check the IP / LAN cable "
                                             f"(printer must be on the same network), or use the PDF download.")


# ─────────────────────────────────────────────────────────────
# TAB 2 — RUNNING BALANCE
# ─────────────────────────────────────────────────────────────
with TAB_RUNNING:
    st.markdown('<div class="sec">RUNNING BALANCE = TOTAL SALES − TOTAL RECEIPTS (DATE RANGE)</div>', unsafe_allow_html=True)
    st.caption("Select a date range to see exactly how much money was NOT collected in that period, by area and by customer.")
    all_dates_rb = get_all_dates()

    if len(all_dates_rb) < 1:
        st.info("No data uploaded yet.")
    else:
        f1, f2, f3 = st.columns([2, 2, 3])
        with f1:
            rb_from = st.date_input("From", value=LATEST_DATE-timedelta(days=7), key="rf")
        with f2:
            rb_to   = st.date_input("To",   value=LATEST_DATE, key="rt")
        with f3:
            known_areas = sorted(a['area']['Schedule'].tolist())
            if not known_areas:
                known_areas = ["MARKET INDIA BATCH","R&B","RING ROAD+BD+MRH","OUTER","HOTELS","BANDOLU"]
            area_filter = st.multiselect("Filter by Area", known_areas, default=known_areas, key="ra")

        rb = build_running_balance(all_dates_rb, rb_from, rb_to)

        if rb is None:
            st.warning("No data in that date range.")
        else:
            rb_cust      = rb['cust_grp'].copy()
            rb_area      = rb['area_grp'].copy()
            area_daily_data = rb['area_daily']

            if area_filter:
                rb_cust = rb_cust[rb_cust['Area'].isin(area_filter)]
                rb_area = rb_area[rb_area['Schedule'].isin(area_filter)]

            total_sales_period     = rb_cust['Period_Sales'].sum()
            total_receipts_period  = rb_cust['Period_Receipts'].sum()
            total_running_balance  = rb_cust['Running_Balance'].sum()
            bad_count = int(rb_cust['Bad_Debt_Risk'].sum())

            # ── KPIs ──
            c1, c2, c3, c4 = st.columns(4)
            for col, args in zip([c1,c2,c3,c4],[
                ("yellow","Total Sales in Period", inr(total_sales_period),
                 f"{rb_from} → {rb_to}"),
                ("green","Total Collected in Period", inr(total_receipts_period),
                 f"{total_receipts_period/max(total_sales_period,1)*100:.1f}% of sales"),
                ("red","Running Balance (Uncollected)", inr(total_running_balance),
                 "Sales − Receipts · money not yet paid"),
                ("red" if bad_count>0 else "green","High-Risk Accounts", str(bad_count),
                 "Running Bal >₹2L & <30% collected"),
            ]):
                with col: st.markdown(kpi(*args), unsafe_allow_html=True)

            # ── AREA-WISE RUNNING BALANCE ──
            st.markdown('<div class="sec">AREA-WISE RUNNING BALANCE</div>', unsafe_allow_html=True)
            ag1, ag2 = st.columns([3, 2])
            with ag1:
                fig_arb = px.bar(rb_area.sort_values('Running_Balance', ascending=False),
                                 x='Schedule', y=['Period_Sales','Period_Receipts','Running_Balance'],
                                 barmode='group',
                                 color_discrete_map={
                                     'Period_Sales':'rgba(0,212,170,.35)',
                                     'Period_Receipts':'#6bcb77',
                                     'Running_Balance':'#ff6b6b'},
                                 title="Area: Sales vs Collected vs Running Balance",
                                 labels={'value':'₹','Schedule':'Area','variable':''})
                fig_arb.update_layout(**ct(), height=320)
                fig_arb.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_arb, use_container_width=True)
            with ag2:
                area_disp = rb_area[['Schedule','Period_Sales','Period_Receipts','Running_Balance','Collection_Rate','Customers']].copy()
                area_disp.columns = ['Area','Sales','Collected','Running Balance','Coll %','Customers']
                for c in ['Sales','Collected','Running Balance']:
                    area_disp[c] = area_disp[c].apply(inr)
                area_disp['Coll %'] = area_disp['Coll %'].apply(lambda x: f"{x:.1f}%")
                st.dataframe(area_disp.sort_values('Running Balance', ascending=False),
                             use_container_width=True, hide_index=True)

            # ── DAILY RUNNING BALANCE TREND ──
            if area_daily_data is not None and not area_daily_data.empty:
                adf = area_daily_data[area_daily_data['Schedule'].isin(area_filter)] if area_filter else area_daily_data
                st.markdown('<div class="sec">DAILY RUNNING BALANCE TREND BY AREA</div>', unsafe_allow_html=True)
                fig_t = px.line(adf, x='date', y='Running_Balance', color='Schedule',
                                title="Daily Running Balance (Sales − Receipts) per Area",
                                markers=True, labels={'date':'Date','Running_Balance':'Uncollected (₹)'})
                fig_t.update_layout(**ct(), height=320)
                fig_t.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                fig_t.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_t, use_container_width=True)

            # ── CUSTOMER RUNNING BALANCE TABLE ──
            st.markdown('<div class="sec">CUSTOMER-WISE RUNNING BALANCE</div>', unsafe_allow_html=True)
            rb_disp = rb_cust.copy().sort_values('Running_Balance', ascending=False)
            rb_disp['Bad_Debt_Risk'] = rb_disp['Bad_Debt_Risk'].apply(lambda x: "🔴" if x else "")
            for col in ['Period_Sales','Period_Receipts','Running_Balance','Latest_Balance']:
                if col in rb_disp.columns:
                    rb_disp[col] = rb_disp[col].apply(inr)
            rb_disp['Collection_Rate'] = rb_disp['Collection_Rate'].apply(lambda x: f"{float(x):.1f}%")
            show_cols = [c for c in ['Area','Name','Days_Active','Period_Sales',
                         'Period_Receipts','Running_Balance','Latest_Balance',
                         'Collection_Rate','Bad_Debt_Risk'] if c in rb_disp.columns]
            rb_disp = rb_disp[show_cols].rename(columns={
                'Days_Active':'Days','Period_Sales':'Period Sales',
                'Period_Receipts':'Period Collected','Running_Balance':'Running Balance',
                'Latest_Balance':'Last Day Balance','Collection_Rate':'Coll %','Bad_Debt_Risk':'⚠'})
            st.dataframe(rb_disp, use_container_width=True, hide_index=True, height=420)

            # ── TOP OFFENDERS CHART ──
            st.markdown('<div class="sec">WHO IS PILING UP DEBT? — TOP 15</div>', unsafe_allow_html=True)
            top_off = rb_cust.nlargest(15, 'Running_Balance')
            fig_off = px.bar(top_off, x='Running_Balance', y='Name', orientation='h',
                             color='Collection_Rate',
                             color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'#6bcb77')],
                             range_color=[0,100],
                             title="Highest Running Balance (colour = collection rate — red = at risk)",
                             labels={'Running_Balance':'Uncollected (₹)','Name':'','Collection_Rate':'Coll %'})
            fig_off.update_layout(**ct(), height=420, coloraxis_colorbar=dict(title='Coll %'))
            fig_off.update_xaxes(gridcolor='rgba(255,255,255,.05)')
            st.plotly_chart(fig_off, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# TAB 3 — PREVIOUS WEEK UNPAID TRACKER
# ─────────────────────────────────────────────────────────────
with TAB_PREVWEEK:
    st.markdown('<div class="sec">📋 UNPAID TRACKER — HOW MUCH WAS NOT GIVEN IN THE SELECTED WEEK</div>', unsafe_allow_html=True)
    st.caption("Pick any week to see who still owes money from that week. Use this every day to follow up and collect.")

    all_dates_pw = get_all_dates()
    if not all_dates_pw:
        st.info("No data uploaded yet.")
    else:
        pw1, pw2, pw3 = st.columns([2, 2, 3])
        with pw1:
            # Default: last 7 days of available data
            pw_from = st.date_input("Week Start", value=LATEST_DATE-timedelta(days=6), key="pw_from")
        with pw2:
            pw_to   = st.date_input("Week End",   value=LATEST_DATE, key="pw_to")
        with pw3:
            pw_areas_all = sorted(a['area']['Schedule'].tolist())
            if not pw_areas_all:
                pw_areas_all = ["MARKET INDIA BATCH","R&B","RING ROAD+BD+MRH","OUTER","HOTELS","BANDOLU"]
            pw_area_filter = st.multiselect("Filter Area", pw_areas_all, default=pw_areas_all, key="pw_area")

        rb_pw = build_running_balance(all_dates_pw, pw_from, pw_to)

        if rb_pw is None:
            st.warning(f"No data found for {pw_from} to {pw_to}. Try a different date range.")
        else:
            pw_cust = rb_pw['cust_grp'].copy()
            pw_area = rb_pw['area_grp'].copy()

            if pw_area_filter:
                pw_cust = pw_cust[pw_cust['Area'].isin(pw_area_filter)]
                pw_area = pw_area[pw_area['Schedule'].isin(pw_area_filter)]

            # Only show customers who have unpaid balance (Running_Balance > 0)
            unpaid = pw_cust[pw_cust['Running_Balance'] > 0].copy()
            fully_paid = pw_cust[pw_cust['Running_Balance'] <= 0].copy()

            total_week_sales    = pw_cust['Period_Sales'].sum()
            total_week_receipts = pw_cust['Period_Receipts'].sum()
            total_unpaid        = unpaid['Running_Balance'].sum()
            unpaid_customers    = len(unpaid)

            # ── KPIs ──
            k1, k2, k3, k4 = st.columns(4)
            for col, args in zip([k1,k2,k3,k4],[
                ("yellow","Week Sales", inr(total_week_sales),
                 f"{pw_from} to {pw_to}"),
                ("green","Week Collected", inr(total_week_receipts),
                 f"{total_week_receipts/max(total_week_sales,1)*100:.1f}% collected"),
                ("red","Week Unpaid Amount", inr(total_unpaid),
                 f"NOT given this week — follow up!"),
                ("red","Customers Not Cleared", str(unpaid_customers),
                 f"out of {len(pw_cust)} active"),
            ]):
                with col: st.markdown(kpi(*args), unsafe_allow_html=True)

            # ── AREA-WISE UNPAID SUMMARY ──
            st.markdown('<div class="sec">AREA-WISE UNPAID SUMMARY</div>', unsafe_allow_html=True)
            pw_area_disp = pw_area[['Schedule','Period_Sales','Period_Receipts','Running_Balance','Collection_Rate','Customers']].copy()
            pw_area_disp.columns = ['Area','Week Sales','Week Collected','Week Unpaid','Coll %','Customers']
            pw_area_disp['Urgency'] = pw_area_disp['Coll %'].apply(
                lambda x: "🔴 Urgent" if float(x) < 40 else ("🟡 Follow Up" if float(x) < 75 else "🟢 OK"))
            for c in ['Week Sales','Week Collected','Week Unpaid']:
                pw_area_disp[c] = pw_area_disp[c].apply(inr)
            pw_area_disp['Coll %'] = pw_area_disp['Coll %'].apply(lambda x: f"{float(x):.1f}%")

            pa1, pa2 = st.columns([3, 2])
            with pa1:
                unpaid_area_raw = pw_area[pw_area['Running_Balance'] > 0].sort_values('Running_Balance', ascending=False)
                fig_pw_area = px.bar(unpaid_area_raw, x='Schedule', y='Running_Balance',
                                     color='Collection_Rate',
                                     color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'#6bcb77')],
                                     range_color=[0,100],
                                     text='Running_Balance',
                                     title="Unpaid Amount by Area (colour = collection rate)",
                                     labels={'Running_Balance':'Unpaid (₹)','Schedule':'Area'})
                fig_pw_area.update_traces(texttemplate='₹%{text:,.0f}', textposition='outside')
                fig_pw_area.update_layout(**ct(), height=300, coloraxis_showscale=False)
                st.plotly_chart(fig_pw_area, use_container_width=True)
            with pa2:
                st.dataframe(pw_area_disp.sort_values('Week Unpaid', ascending=False),
                             use_container_width=True, hide_index=True)

            # ── CUSTOMER UNPAID LIST — CALL SHEET ──
            st.markdown('<div class="sec">📞 CUSTOMER FOLLOW-UP CALL SHEET — UNPAID THIS WEEK</div>', unsafe_allow_html=True)
            st.caption(f"These {unpaid_customers} customers bought but haven't paid in full. Call them today.")

            if unpaid.empty:
                st.success("✅ All customers have paid in full for this week!")
            else:
                unpaid_disp = unpaid[['Area','Name','Period_Sales','Period_Receipts','Running_Balance','Collection_Rate','Days_Active']].copy()
                unpaid_disp['Running_Balance_raw'] = unpaid_disp['Running_Balance']
                unpaid_disp['Priority'] = unpaid_disp['Running_Balance_raw'].apply(
                    lambda x: "🔴 HIGH" if x > 50000 else ("🟡 MEDIUM" if x > 10000 else "🟢 LOW"))
                unpaid_disp['Action'] = unpaid_disp['Running_Balance_raw'].apply(
                    lambda x: "🚨 Call immediately" if x > 50000 else ("📞 Call today" if x > 10000 else "💬 Remind tomorrow"))
                unpaid_disp = unpaid_disp.drop(columns=['Running_Balance_raw'])
                for c in ['Period_Sales','Period_Receipts','Running_Balance']:
                    unpaid_disp[c] = unpaid_disp[c].apply(inr)
                unpaid_disp['Collection_Rate'] = unpaid_disp['Collection_Rate'].apply(lambda x: f"{float(x):.1f}%")
                unpaid_disp.columns = ['Area','Customer','Week Sales','Week Paid','Still Owes','Paid %','Days','Priority','Action']
                unpaid_disp = unpaid_disp.sort_values('Still Owes', ascending=False)

                # Filter tabs
                pt1, pt2, pt3, pt4 = st.tabs([
                    f"All Unpaid ({len(unpaid_disp)})",
                    f"🔴 High Priority",
                    f"🟡 Medium",
                    f"🟢 Low"])
                with pt1:
                    st.dataframe(unpaid_disp, use_container_width=True, hide_index=True, height=380)
                with pt2:
                    st.dataframe(unpaid_disp[unpaid_disp['Priority'].str.contains('HIGH')],
                                 use_container_width=True, hide_index=True, height=300)
                with pt3:
                    st.dataframe(unpaid_disp[unpaid_disp['Priority'].str.contains('MEDIUM')],
                                 use_container_width=True, hide_index=True, height=300)
                with pt4:
                    st.dataframe(unpaid_disp[unpaid_disp['Priority'].str.contains('LOW')],
                                 use_container_width=True, hide_index=True, height=300)

            # ── CUSTOMERS WHO FULLY PAID ──
            if not fully_paid.empty:
                with st.expander(f"✅ {len(fully_paid)} Customers fully cleared for this week"):
                    fp_disp = fully_paid[['Area','Name','Period_Sales','Period_Receipts','Collection_Rate']].copy()
                    fp_disp.columns = ['Area','Customer','Week Sales','Week Paid','Coll %']
                    for c in ['Week Sales','Week Paid']:
                        fp_disp[c] = fp_disp[c].apply(inr)
                    fp_disp['Coll %'] = fp_disp['Coll %'].apply(lambda x: f"{float(x):.1f}%")
                    st.dataframe(fp_disp, use_container_width=True, hide_index=True)

            # ── CHART: TOP UNPAID CUSTOMERS ──
            st.markdown('<div class="sec">TOP 20 UNPAID CUSTOMERS THIS WEEK</div>', unsafe_allow_html=True)
            top_unpaid = unpaid.nlargest(20, 'Running_Balance')
            if not top_unpaid.empty:
                fig_tu = px.bar(top_unpaid, x='Running_Balance', y='Name', orientation='h',
                                color='Area',
                                title="Top 20 Customers by Unpaid Amount",
                                labels={'Running_Balance':'Still Owes (₹)','Name':''})
                fig_tu.update_layout(**ct(), height=500)
                fig_tu.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_tu, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# TAB 4 — VEGETABLES
# ─────────────────────────────────────────────────────────────
with TAB_VEG:
    st.markdown('<div class="sec">🥦 VEGETABLE PRICE TRACKER & ANALYTICS</div>', unsafe_allow_html=True)
    st.caption("Track how prices move day-to-day, which vegetables drive the most revenue, and volume sold per item.")

    with st.expander("🌿 Telugu Names — shown on printed bills; edit or add for new vegetables"):
        if MONGO_AVAILABLE:
            _vdocs = list(db.vegetables.find({}, {"_id": 0, "name": 1, "telugu_name": 1, "description": 1}))
            if _vdocs:
                _vdf = pd.DataFrame(_vdocs)
                for _c in ["telugu_name", "description"]:
                    if _c not in _vdf.columns:
                        _vdf[_c] = ""
                _vdf = (_vdf[["name", "telugu_name", "description"]].fillna("")
                        .sort_values("name").reset_index(drop=True))
                _vedit = st.data_editor(_vdf, hide_index=True, use_container_width=True,
                                        height=350, disabled=["name"], key="veg_telugu_editor",
                                        column_config={
                                            "name": "Vegetable (English)",
                                            "telugu_name": "Telugu Name",
                                            "description": "Description"})
                if st.button("💾 Save Telugu Names", use_container_width=True, key="veg_telugu_save"):
                    for _, _vrow in _vedit.iterrows():
                        db.vegetables.update_one(
                            {"name": _vrow["name"]},
                            {"$set": {"telugu_name": str(_vrow["telugu_name"]).strip(),
                                      "description": str(_vrow["description"]).strip()}})
                    st.success(f"✅ Saved {len(_vedit)} vegetables — bills will use the new names immediately.")
            else:
                st.info("No vegetables yet — upload sales first.")
        else:
            st.info("MongoDB required to store Telugu names.")

    all_dates_veg = get_all_dates()
    if not all_dates_veg:
        st.info("No data uploaded yet.")
    else:
        vf1, vf2 = st.columns([2, 2])
        with vf1:
            veg_from = st.date_input("From", value=LATEST_DATE-timedelta(days=30), key="vf")
        with vf2:
            veg_to   = st.date_input("To",   value=LATEST_DATE, key="vt")

        va = build_veg_analytics(all_dates_veg, veg_from, veg_to)

        if va is None:
            st.warning("No sales data found for that date range.")
        else:
            summary  = va['summary']
            daily    = va['daily']
            grand_total = va['grand_total']
            n_days   = len(va['dates_used'])
            n_items  = len(summary)

            # ── KPIs ──
            top_item  = summary.iloc[0]
            total_kgs = summary['total_kgs'].sum()
            v1, v2, v3, v4 = st.columns(4)
            for col, args in zip([v1,v2,v3,v4],[
                ("green",  "Total Revenue (period)", inr(grand_total),
                 f"{n_days} day(s) · {n_items} vegetables"),
                ("yellow", "Total Volume Sold",      f"{total_kgs:,.0f} Kgs",
                 f"Across all vegetables"),
                ("purple", "Top Vegetable",          top_item['Item'],
                 f"{inr(top_item['total_amount'])} · {top_item['revenue_pct']:.1f}% of sales"),
                ("green",  "Avg Daily Revenue",      inr(grand_total / max(n_days, 1)),
                 f"Per day average"),
            ]):
                with col: st.markdown(kpi(*args), unsafe_allow_html=True)

            # ── REVENUE CONTRIBUTION ──
            st.markdown('<div class="sec">REVENUE CONTRIBUTION BY VEGETABLE</div>', unsafe_allow_html=True)
            rc1, rc2 = st.columns([3, 2])
            with rc1:
                fig_contrib = px.bar(
                    summary.head(20), x='total_amount', y='Item', orientation='h',
                    color='revenue_pct',
                    color_continuous_scale=[(0,'#2c5364'),(0.4,'#ffd93d'),(1,'#6bcb77')],
                    text='revenue_pct',
                    title="Top 20 Vegetables by Revenue",
                    labels={'total_amount':'Revenue (₹)', 'Item':'', 'revenue_pct':'% of Sales'}
                )
                fig_contrib.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_contrib.update_layout(**ct(), height=460, coloraxis_showscale=False)
                fig_contrib.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_contrib, use_container_width=True)
            with rc2:
                fig_pie = px.pie(
                    summary.head(10), names='Item', values='total_amount', hole=0.5,
                    title="Revenue Share — Top 10",
                    color_discrete_sequence=px.colors.qualitative.Bold
                )
                fig_pie.update_layout(**ct(), height=280, showlegend=True,
                                      legend=dict(font_size=9))
                fig_pie.update_traces(textinfo='percent', textfont_size=10)
                st.plotly_chart(fig_pie, use_container_width=True)

                # Volume share
                fig_vol_pie = px.pie(
                    summary.head(10), names='Item', values='total_kgs', hole=0.5,
                    title="Volume Share (Kgs) — Top 10",
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                fig_vol_pie.update_layout(**ct(), height=220, showlegend=False)
                fig_vol_pie.update_traces(textinfo='label+percent', textfont_size=9)
                st.plotly_chart(fig_vol_pie, use_container_width=True)

            # ── PRICE TREND OVER TIME ──
            st.markdown('<div class="sec">PRICE TREND — RATE PER KG OVER TIME</div>', unsafe_allow_html=True)
            _tel_map = get_veg_telugu_map()
            _tel_label = lambda x: f"{x} · {_tel_map[x]}" if _tel_map.get(x) else x
            all_items = sorted(summary['Item'].tolist())
            default_items = summary.head(6)['Item'].tolist()
            sel_items = st.multiselect(
                "Select vegetables to compare prices",
                all_items, default=default_items, key="veg_sel",
                format_func=_tel_label
            )
            if sel_items:
                price_df = daily[daily['Item'].isin(sel_items)]
                fig_price = px.line(
                    price_df, x='date_str', y='avg_rate', color='Item',
                    markers=True,
                    title="Average Rate (₹/Kg) — Day by Day",
                    labels={'date_str':'Date', 'avg_rate':'Rate (₹/Kg)', 'Item':'Vegetable'}
                )
                fig_price.update_layout(**ct(), height=360)
                fig_price.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                fig_price.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_price, use_container_width=True)

                # Volume (Kgs) over time
                fig_vol = px.bar(
                    price_df, x='date_str', y='total_kgs', color='Item',
                    barmode='group',
                    title="Volume Sold (Kgs) — Day by Day",
                    labels={'date_str':'Date', 'total_kgs':'Kgs Sold', 'Item':'Vegetable'}
                )
                fig_vol.update_layout(**ct(), height=280)
                fig_vol.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                st.plotly_chart(fig_vol, use_container_width=True)

            # ── SUMMARY TABLE ──
            st.markdown('<div class="sec">VEGETABLE SUMMARY TABLE</div>', unsafe_allow_html=True)
            st_sum = summary.copy()
            st_sum['avg_rate']    = st_sum['avg_rate'].apply(lambda x: f"₹{x:.2f}/kg")
            st_sum['min_rate']    = st_sum['min_rate'].apply(lambda x: f"₹{x:.2f}")
            st_sum['max_rate']    = st_sum['max_rate'].apply(lambda x: f"₹{x:.2f}")
            st_sum['total_amount']= st_sum['total_amount'].apply(inr)
            st_sum['total_kgs']   = st_sum['total_kgs'].apply(lambda x: f"{x:,.1f}")
            st_sum['revenue_pct'] = st_sum['revenue_pct'].apply(lambda x: f"{x:.1f}%")
            st_sum['avg_daily_kgs']= st_sum['avg_daily_kgs'].apply(lambda x: f"{x:,.1f}")
            st_sum.insert(1, 'Telugu', st_sum['Item'].map(_tel_map).fillna(''))
            st_sum.columns = [
                'Vegetable','Telugu','Days Sold','Total Kgs','Total Bags','Revenue','Avg Rate',
                'Min Rate','Max Rate','Transactions','Revenue %','Avg Daily Kgs','Unique Customers'
            ]
            st.dataframe(st_sum, use_container_width=True, hide_index=True, height=380)

            # ── DEEP DIVE: SINGLE ITEM ──
            st.markdown('<div class="sec">DEEP DIVE — SINGLE VEGETABLE</div>', unsafe_allow_html=True)
            dive_item = st.selectbox("Pick a vegetable to deep dive", all_items, key="veg_dive",
                                     format_func=_tel_label)
            if dive_item:
                item_daily = daily[daily['Item'] == dive_item].copy()
                item_raw   = va['raw'][va['raw']['Item'] == dive_item].copy()

                d1, d2, d3, d4 = st.columns(4)
                item_s = summary[summary['Item'] == dive_item].iloc[0]
                for col, args in zip([d1, d2, d3, d4],[
                    ("green",  "Total Revenue",   inr(item_s['total_amount']),
                     f"{item_s['revenue_pct']:.1f}% of all veg sales"),
                    ("yellow", "Total Volume",    f"{item_s['total_kgs']:,.1f} Kgs",
                     f"{int(item_s['total_bags'])} bags"),
                    ("purple", "Avg Rate",        f"₹{item_s['avg_rate']:.2f}/kg",
                     f"Min ₹{item_s['min_rate']:.2f} · Max ₹{item_s['max_rate']:.2f}"),
                    ("green",  "Unique Customers",str(int(item_s['unique_customers'])),
                     f"across {int(item_s['days_sold'])} day(s)"),
                ]):
                    with col: st.markdown(kpi(*args), unsafe_allow_html=True)

                dd1, dd2 = st.columns(2)
                with dd1:
                    fig_dd_rate = px.line(
                        item_daily, x='date_str', y=['avg_rate','min_rate','max_rate'],
                        markers=True,
                        title=f"{dive_item} — Rate Range (₹/Kg)",
                        labels={'date_str':'Date','value':'Rate (₹/Kg)','variable':''}
                    )
                    fig_dd_rate.update_layout(**ct(), height=280)
                    fig_dd_rate.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                    fig_dd_rate.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                    st.plotly_chart(fig_dd_rate, use_container_width=True)
                with dd2:
                    fig_dd_vol = px.bar(
                        item_daily, x='date_str', y='total_kgs',
                        color='total_amount',
                        color_continuous_scale='Teal',
                        title=f"{dive_item} — Kgs Sold (bar colour = revenue)",
                        labels={'date_str':'Date','total_kgs':'Kgs Sold','total_amount':'Revenue (₹)'}
                    )
                    fig_dd_vol.update_layout(**ct(), height=280, coloraxis_showscale=False)
                    fig_dd_vol.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                    st.plotly_chart(fig_dd_vol, use_container_width=True)

                # Who buys this vegetable the most?
                st.markdown(f'<div class="sec">WHO BUYS {dive_item.upper()} THE MOST?</div>', unsafe_allow_html=True)
                cust_buy = item_raw.groupby('Name').agg(
                    total_kgs=('Kgs','sum'),
                    total_amount=('Amount','sum'),
                    avg_rate=('Rate','mean'),
                    times_purchased=('Amount','count'),
                ).reset_index().sort_values('total_amount', ascending=False).head(20)
                fig_cust_buy = px.bar(
                    cust_buy, x='total_amount', y='Name', orientation='h',
                    color='total_kgs',
                    color_continuous_scale='Teal',
                    title=f"Top Buyers of {dive_item}",
                    labels={'total_amount':'Revenue (₹)','Name':'','total_kgs':'Kgs'}
                )
                fig_cust_buy.update_layout(**ct(), height=420, coloraxis_showscale=True,
                                           coloraxis_colorbar=dict(title='Kgs'))
                fig_cust_buy.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_cust_buy, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# TAB 5 — BAD DEBTS & LOSS
# ─────────────────────────────────────────────────────────────
with TAB_BADDEBT:
    st.markdown('<div class="sec">BAD DEBT IDENTIFICATION & LOSS ANALYSIS</div>', unsafe_allow_html=True)

    rb_all = build_running_balance(get_all_dates())
    if rb_all:
        rc = rb_all['cust_grp']
        s_col = 'Period_Sales'; r_col = 'Period_Receipts'; b_col = 'Running_Balance'; rate_col = 'Collection_Rate'
    else:
        rc = a['customers'].copy()
        rc = rc.rename(columns={'Sales':'Period_Sales','Receipts':'Period_Receipts',
                                 'Balance':'Running_Balance','collection_rate':'Collection_Rate','Schedule':'Area'})
        s_col='Period_Sales'; r_col='Period_Receipts'; b_col='Running_Balance'; rate_col='Collection_Rate'

    def debt_tier(r):
        bal, rate = r[b_col], r[rate_col]
        if bal > 500000 and rate < 20: return "🔴 Critical"
        if bal > 200000 and rate < 30: return "🟠 High Risk"
        if bal > 100000 and rate < 50: return "🟡 Watch"
        if rate == 0 and bal > 50000:  return "🟡 Watch"
        return ""

    rc['Tier'] = rc.apply(debt_tier, axis=1)
    bad = rc[rc['Tier'] != ""].sort_values(b_col, ascending=False)

    crit = bad[bad['Tier']=="🔴 Critical"]
    high = bad[bad['Tier']=="🟠 High Risk"]
    wtch = bad[bad['Tier']=="🟡 Watch"]

    c1,c2,c3 = st.columns(3)
    with c1: st.markdown(kpi("red","Critical Accounts",str(len(crit)),inr(crit[b_col].sum())+" at stake"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("yellow","High Risk",str(len(high)),inr(high[b_col].sum())+" at stake"), unsafe_allow_html=True)
    with c3: st.markdown(kpi("yellow","Watch List",str(len(wtch)),inr(wtch[b_col].sum())+" at stake"), unsafe_allow_html=True)

    if not bad.empty:
        st.markdown('<div class="sec">BAD DEBT MAP</div>', unsafe_allow_html=True)
        fig_bd = px.scatter(bad.reset_index(), x=s_col, y=b_col, size=b_col,
                            color='Tier',
                            color_discrete_map={"🔴 Critical":"#ff6b6b","🟠 High Risk":"#ff9a3c","🟡 Watch":"#ffd93d"},
                            hover_name='Name',
                            title="Bad Debt Map — bubble size = outstanding balance",
                            labels={s_col:'Total Sales (₹)', b_col:'Outstanding (₹)'})
        fig_bd.update_layout(**ct(), height=400)
        fig_bd.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        fig_bd.update_yaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fig_bd, use_container_width=True)

        st.markdown('<div class="sec">ACTION LIST</div>', unsafe_allow_html=True)
        bd_show = bad[['Tier','Area','Name',s_col,r_col,b_col,rate_col]].copy()
        bd_show.columns = ['Risk','Area','Customer','Total Sales','Collected','Outstanding','Coll %']
        for c in ['Total Sales','Collected','Outstanding']:
            bd_show[c] = bd_show[c].apply(inr)
        bd_show['Coll %']  = bd_show['Coll %'].apply(lambda x: f"{float(x):.1f}%")
        bd_show['Action']  = bd_show['Risk'].apply(lambda x:
            "🚨 STOP SUPPLY · Send legal notice" if "Critical" in x else
            ("⛔ Reduce credit · Collect first" if "High" in x else "📞 Call this week"))
        st.dataframe(bd_show, use_container_width=True, hide_index=True)

        total_at_risk = bad[b_col].sum()
        st.error(f"💸 **Estimated Profit at Risk = {inr(total_at_risk * MARGIN_PCT)}** "
                 f"(5% on {inr(total_at_risk)} outstanding in bad/watch accounts)")
    else:
        st.success("✅ No bad debt accounts with current data. Upload more days for better signals.")

    st.markdown('<div class="sec">COLLECTION EFFICIENCY BY AREA (TODAY)</div>', unsafe_allow_html=True)
    ae = a['area'].sort_values('Collection_Eff')
    fig_ae = px.bar(ae, x='Schedule', y='Collection_Eff', color='Collection_Eff', text='Collection_Eff',
                    color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'#6bcb77')],
                    range_color=[0,100], title="Lower = more money slipping away",
                    labels={'Collection_Eff':'Collection %','Schedule':'Area'})
    fig_ae.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
    fig_ae.update_layout(**ct(), height=300, coloraxis_showscale=False)
    st.plotly_chart(fig_ae, use_container_width=True)

    st.markdown('<div class="sec">ZERO PAYMENT CUSTOMERS TODAY</div>', unsafe_allow_html=True)
    zero_pay = a['customers'][(a['customers']['Receipts']==0) & (a['customers']['Sales']>0)].copy()
    zero_pay = zero_pay[['Schedule','Name','OB','Sales','Balance']].copy()
    zero_pay.columns = ['Area','Customer','Opening Balance','Today Sales','Outstanding']
    for c in ['Opening Balance','Today Sales','Outstanding']:
        zero_pay[c] = zero_pay[c].apply(inr)
    st.dataframe(zero_pay.sort_values('Outstanding', ascending=False), use_container_width=True, hide_index=True)
    st.caption(f"{len(zero_pay)} customers bought today but paid ₹0 this evening. Total sales from them: {inr(a['customers'][(a['customers']['Receipts']==0) & (a['customers']['Sales']>0)]['Sales'].sum())}")


# ─────────────────────────────────────────────────────────────
# TAB 4 — PROFIT ANALYSIS
# ─────────────────────────────────────────────────────────────
with TAB_PROFIT:
    st.markdown('<div class="sec">PROFIT ANALYSIS</div>', unsafe_allow_html=True)
    realized_pct = a['profit_realized'] / max(a['profit_potential'],1) * 100
    c1,c2,c3,c4 = st.columns(4)
    for col, args in zip([c1,c2,c3,c4],[
        ("green","Profit Potential", inr(a['profit_potential']), f"5% on {inr(a['total_sales'])}"),
        ("green" if realized_pct>70 else "yellow","Realized Profit", inr(a['profit_realized']), f"{realized_pct:.1f}% of potential"),
        ("red","Profit Gap", inr(a['profit_potential']-a['profit_realized']), "From uncollected credit"),
        ("purple","Collection Needed","→ Same-day", "To maximize margin"),
    ]):
        with col: st.markdown(kpi(*args), unsafe_allow_html=True)

    p1,p2 = st.columns(2)
    with p1:
        fig_pp = go.Figure()
        fig_pp.add_trace(go.Bar(name='Potential', x=a['area']['Schedule'],
                                y=a['area']['Profit_Potential'], marker_color='rgba(0,212,170,.3)'))
        fig_pp.add_trace(go.Bar(name='Realized', x=a['area']['Schedule'],
                                y=a['area']['Profit_Realized'], marker_color='#00d4aa'))
        fig_pp.update_layout(**ct(), height=320, title="Potential vs Realized Profit by Area",
                             barmode='overlay', legend=dict(font_size=11))
        fig_pp.update_yaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fig_pp, use_container_width=True)
    with p2:
        fig_pr = px.bar(a['area'].sort_values('Profit_Loss_Pct'),
                        x='Schedule', y='Profit_Loss_Pct', color='Profit_Loss_Pct', text='Profit_Loss_Pct',
                        color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'#6bcb77')],
                        range_color=[0,100], title="Profit Realization % by Area",
                        labels={'Profit_Loss_Pct':'%','Schedule':'Area'})
        fig_pr.update_traces(texttemplate='%{text:.0f}%', textposition='outside')
        fig_pr.update_layout(**ct(), height=320, coloraxis_showscale=False)
        st.plotly_chart(fig_pr, use_container_width=True)

    st.markdown('<div class="sec">CUSTOMER PROFIT TABLE — SORTED BY PROFIT GAP</div>', unsafe_allow_html=True)
    cp = a['customers'][['Schedule','Name','Sales','Receipts','profit_potential','profit_realized','collection_rate']].copy()
    cp['Profit Gap'] = cp['profit_potential'] - cp['profit_realized']
    cp = cp.sort_values('Profit Gap', ascending=False)
    for c in ['Sales','Receipts','profit_potential','profit_realized','Profit Gap']:
        cp[c] = cp[c].apply(inr)
    cp['collection_rate'] = cp['collection_rate'].apply(lambda x: f"{x}%")
    cp.columns = ['Area','Customer','Sales','Collected','Profit Potential','Profit Earned','Coll %','Profit Gap']
    st.dataframe(cp, use_container_width=True, hide_index=True, height=360)

    st.markdown('<div class="sec">HOW TO MAXIMIZE PROFIT</div>', unsafe_allow_html=True)
    area_sorted = a['area'].sort_values('Collection_Eff')
    if len(area_sorted) >= 1:
        worst = area_sorted.iloc[0]
        best  = area_sorted.iloc[-1]
        st.markdown(f"""
| Insight | Action |
|---|---|
| 🔴 **{worst['Schedule']}** collects only {worst['Collection_Eff']:.1f}% | Prioritize evening collection there first |
| 🟢 **{best['Schedule']}** collects {best['Collection_Eff']:.1f}% | Model for other areas — what's working? |
| Every ₹1L collected same-day | Saves you ₹5,000 in risk (your 5% margin secured) |
| Stop supply to Critical debtors | Redirect stock to good-paying customers |
| Enforce daily credit limits | Cap each customer at max 7-day outstanding |
| ₹ per day uncollected = bad debt risk | After 30 days, recovery probability drops sharply |
""")
    else:
        st.info("Upload receipts for this date to see profit insights.")


# ─────────────────────────────────────────────────────────────
# TAB 5 — REWARDS
# ─────────────────────────────────────────────────────────────
with TAB_REWARDS:
    st.markdown('<div class="sec">🏆 CUSTOMER REWARDS & RANKINGS</div>', unsafe_allow_html=True)
    st.caption("Based on profit realized (collections × 5%) — your truly valuable customers")

    rb_all_rew = build_running_balance(get_all_dates())
    if rb_all_rew:
        rew = rb_all_rew['cust_grp']
        p_col = 'Cumulative_Profit_Realized'; s_col = 'Period_Sales'
        r_col = 'Period_Receipts'; b_col = 'Running_Balance'; rate_col = 'Collection_Rate'
        pp_col = 'Cumulative_Profit_Potential'
    else:
        rew = a['customers'].copy()
        rew['Cumulative_Profit_Realized']  = rew['profit_realized']
        rew['Cumulative_Profit_Potential'] = rew['profit_potential']
        rew['Period_Sales']     = rew['Sales']
        rew['Period_Receipts']  = rew['Receipts']
        rew['Running_Balance']  = rew['Balance']
        rew['Collection_Rate']  = rew['collection_rate']
        rew['Area']             = rew['Schedule']
        rew['Days_Active']      = 1
        p_col='Cumulative_Profit_Realized'; s_col='Period_Sales'
        r_col='Period_Receipts'; b_col='Running_Balance'; rate_col='Collection_Rate'
        pp_col='Cumulative_Profit_Potential'

    rew = rew[~rew['Area'].isin(EXCLUDE_AREAS)].sort_values(p_col, ascending=False)

    # Medal cards
    medals = ["🥇","🥈","🥉"]
    top3_cols = st.columns(3)
    for i, (col, (_, row)) in enumerate(zip(top3_cols, rew.head(3).iterrows())):
        with col:
            st.markdown(f"""
<div class="reward-card">
  <div class="rank">{medals[i]}</div>
  <div class="name">{row['Name']}</div>
  <div style="font-size:11px;opacity:.6;margin-bottom:8px;">{row['Area']}</div>
  <div class="amt">{inr(row[p_col])}</div>
  <div style="font-size:11px;opacity:.5;margin-top:6px;">profit contributed · {float(row[rate_col]):.1f}% collection rate</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec">TOP 20 — MOST PROFITABLE CUSTOMERS</div>', unsafe_allow_html=True)
    top20r = rew.head(20)
    fig_rew = px.bar(top20r, x=p_col, y='Name', orientation='h',
                     color=rate_col,
                     color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'gold')],
                     range_color=[0,100],
                     title="Profit Contributed (colour = collection rate)",
                     labels={p_col:'Profit Earned (₹)','Name':''})
    fig_rew.update_layout(**ct(), height=540, coloraxis_colorbar=dict(title='Coll %'))
    fig_rew.update_xaxes(gridcolor='rgba(255,255,255,.05)')
    st.plotly_chart(fig_rew, use_container_width=True)

    st.markdown('<div class="sec">🏅 BEST AREAS</div>', unsafe_allow_html=True)
    ar = a['area'].sort_values('Profit_Realized', ascending=False)
    fig_ar = px.bar(ar, x='Schedule', y=['Profit_Potential','Profit_Realized'],
                    barmode='group',
                    color_discrete_map={'Profit_Potential':'rgba(0,212,170,.3)','Profit_Realized':'#00d4aa'},
                    title="Area Profit: Potential vs Realized",
                    labels={'value':'₹','Schedule':'Area'})
    fig_ar.update_layout(**ct(), height=300)
    fig_ar.update_yaxes(gridcolor='rgba(255,255,255,.05)')
    st.plotly_chart(fig_ar, use_container_width=True)

    st.markdown('<div class="sec">🔴 BOTTOM 10 — LOSS MAKERS (PROFIT YOU NEVER GOT)</div>', unsafe_allow_html=True)
    rew['Profit_Gap'] = rew[pp_col] - rew[p_col]
    bot10 = rew.nlargest(10,'Profit_Gap')
    fig_bot = px.bar(bot10, x='Profit_Gap', y='Name', orientation='h',
                     color='Profit_Gap', color_continuous_scale=["#ff9a3c","#ff6b6b","#c0392b"],
                     title="Profit Gap — Customers who buy but don't pay",
                     labels={'Profit_Gap':'Uncollected Profit (₹)','Name':''})
    fig_bot.update_layout(**ct(), height=380, coloraxis_showscale=False)
    fig_bot.update_xaxes(gridcolor='rgba(255,255,255,.05)')
    st.plotly_chart(fig_bot, use_container_width=True)

    st.markdown('<div class="sec">FULL CUSTOMER RANKINGS</div>', unsafe_allow_html=True)
    rank = rew.copy().reset_index(drop=True)
    rank.index += 1
    rank['Profit_Gap'] = rank[pp_col] - rank[p_col]
    cols_r = ['Area','Name', s_col, r_col, b_col, p_col, 'Profit_Gap', rate_col]
    rank = rank[[c for c in cols_r if c in rank.columns]]
    for c in [s_col, r_col, b_col, p_col, 'Profit_Gap']:
        if c in rank.columns:
            rank[c] = rank[c].apply(inr)
    if rate_col in rank.columns:
        rank[rate_col] = rank[rate_col].apply(lambda x: f"{float(x):.1f}%")
    rank.columns = ['Area','Customer','Total Sales','Total Collected','Balance','Profit Earned','Profit Gap','Coll %'][:len(rank.columns)]
    st.dataframe(rank, use_container_width=True, height=420)

# ─────────────────────────────────────────────────────────────
# TAB 8 — LEDGER
# ─────────────────────────────────────────────────────────────
with TAB_LEDGER:
    st.markdown('<div class="sec">📒 CUSTOMER LEDGER</div>', unsafe_allow_html=True)
    st.caption("Day-by-day debit (sales) and credit (receipts) with running balance for any customer")

    # ── Custom Running Balance View ────────────────────────────
    if "custom_rb" in st.session_state and st.session_state["custom_rb"] is not None:
        st.markdown('<div class="sec" style="color:#00d4aa;">📊 CUSTOM RUNNING BALANCE (Date Range)</div>', unsafe_allow_html=True)
        crb_df = st.session_state["custom_rb"]

        # Summary metrics
        cust_summary = crb_df.groupby('Customer').agg(
            Total_Sales=('Sales','sum'),
            Total_Receipts=('Receipts','sum'),
            Final_Running_Balance=('Running_Balance','last')
        ).reset_index().sort_values('Final_Running_Balance', ascending=False)

        k1, k2, k3 = st.columns(3)
        with k1: st.metric("Total Sales", inr(cust_summary['Total_Sales'].sum()))
        with k2: st.metric("Total Receipts", inr(cust_summary['Total_Receipts'].sum()))
        with k3: st.metric("Net Outstanding", inr(cust_summary['Final_Running_Balance'].sum()), delta=f"{len(cust_summary)} customers")

        # Customer selector for detailed view
        sel_cust = st.selectbox("View Customer Details", ['All'] + sorted(cust_summary['Customer'].unique().tolist()), key="crb_cust_sel")

        if sel_cust == 'All':
            disp_crb = crb_df.copy()
        else:
            disp_crb = crb_df[crb_df['Customer'] == sel_cust].copy()

        # Format for display
        disp_crb['Sales'] = disp_crb['Sales'].apply(inr)
        disp_crb['Receipts'] = disp_crb['Receipts'].apply(inr)
        disp_crb['Daily_Change'] = disp_crb['Daily_Change'].apply(lambda x: f"{'+' if x>0 else ''}{inr(abs(x))}" if x != 0 else "—")
        disp_crb['Running_Balance'] = disp_crb['Running_Balance'].apply(inr)
        st.dataframe(disp_crb[['Customer','Date','Sales','Receipts','Daily_Change','Running_Balance']], use_container_width=True, hide_index=True, height=350)

        # Running balance trend chart
        if sel_cust != 'All':
            cust_crb = crb_df[crb_df['Customer'] == sel_cust]
            fig_crb = px.area(cust_crb, x='Date', y='Running_Balance',
                              title=f"{sel_cust} — Running Balance Trend",
                              labels={'Running_Balance': '₹'}, color_discrete_sequence=['#00d4aa'])
            fig_crb.update_layout(**ct(), height=250)
            fig_crb.add_hline(y=0, line_dash="dash", line_color="#6bcb77")
            st.plotly_chart(fig_crb, use_container_width=True)

        if st.button("🗑️ Clear Custom RB", use_container_width=True):
            st.session_state["custom_rb"] = None
            st.rerun()

        st.divider()

    # Build customer list from MongoDB or session state
    all_custs = set()
    if MONGO_AVAILABLE:
        all_custs |= set(db.sales.distinct("Name"))
        all_custs |= set(db.receipts.distinct("Name"))
        all_custs -= set(db.receipts.distinct("Name", {"Schedule": {"$in": list(EXCLUDE_AREAS)}}))
    for d in st.session_state.store.values():
        if "sales" in d and not d["sales"].empty and "Name" in d["sales"].columns:
            all_custs |= set(d["sales"]["Name"].dropna().unique())
        if "receipts" in d and not d["receipts"].empty and "Name" in d["receipts"].columns:
            all_custs |= set(d["receipts"]["Name"].dropna().unique())
    all_custs -= EXCLUDE_CUSTOMERS
    all_custs = sorted(all_custs)

    if not all_custs:
        st.info("No data yet. Import sales or upload receipts first.")
    else:
        chosen_cust = st.selectbox("Select Customer", all_custs, key="ledger_cust")

        # Pull all sales rows for this customer
        if MONGO_AVAILABLE:
            s_rows = list(db.sales.find({"Name": chosen_cust}, {"_id": 0}))
            r_rows = list(db.receipts.find({"Name": chosen_cust}, {"_id": 0}))
            sdf_all = pd.DataFrame(s_rows) if s_rows else pd.DataFrame()
            rdf_all = pd.DataFrame(r_rows) if r_rows else pd.DataFrame()
        else:
            # Fallback: scrape session state
            s_parts, r_parts = [], []
            for d_str, d in st.session_state.store.items():
                if "sales" in d and not d["sales"].empty:
                    chunk = d["sales"][d["sales"]["Name"] == chosen_cust].copy()
                    chunk["date"] = d_str
                    s_parts.append(chunk)
                if "receipts" in d and not d["receipts"].empty:
                    chunk = d["receipts"][d["receipts"]["Name"] == chosen_cust].copy()
                    chunk["date"] = d_str
                    r_parts.append(chunk)
            sdf_all = pd.concat(s_parts, ignore_index=True) if s_parts else pd.DataFrame()
            rdf_all = pd.concat(r_parts, ignore_index=True) if r_parts else pd.DataFrame()

        # Build ledger entries list
        ledger_rows = []
        if not sdf_all.empty and "date" in sdf_all.columns:
            for _, row in sdf_all.iterrows():
                ledger_rows.append({
                    "Date":        row["date"],
                    "Type":        "🛒 Sale",
                    "Particulars": str(row.get("Item","")),
                    "Debit":       float(row.get("Amount", 0)),
                    "Credit":      0.0,
                })
        if not rdf_all.empty and "date" in rdf_all.columns:
            for _, row in rdf_all.iterrows():
                rec = float(row.get("Receipts", 0))
                if rec > 0:
                    ledger_rows.append({
                        "Date":        row["date"],
                        "Type":        "💰 Receipt",
                        "Particulars": "Payment received",
                        "Debit":       0.0,
                        "Credit":      rec,
                    })

        if not ledger_rows:
            st.info(f"No transactions found for **{chosen_cust}**.")
        else:
            ledger = pd.DataFrame(ledger_rows)
            ledger["Date"] = pd.to_datetime(ledger["Date"])
            ledger = ledger.sort_values(["Date","Type"]).reset_index(drop=True)
            ledger["Running Balance"] = (ledger["Debit"] - ledger["Credit"]).cumsum()

            # KPI summary
            total_debit  = ledger["Debit"].sum()
            total_credit = ledger["Credit"].sum()
            final_bal    = total_debit - total_credit
            k1, k2, k3 = st.columns(3)
            with k1: st.markdown(kpi("green", "Total Sales (Dr)", inr(total_debit), f"{len(ledger[ledger['Type']=='🛒 Sale'])} entries"), unsafe_allow_html=True)
            with k2: st.markdown(kpi("yellow", "Total Collected (Cr)", inr(total_credit), f"{total_credit/max(total_debit,1)*100:.1f}% collected"), unsafe_allow_html=True)
            with k3: st.markdown(kpi("red" if final_bal > 0 else "green", "Net Balance", inr(final_bal), "Outstanding" if final_bal > 0 else "Cleared"), unsafe_allow_html=True)

            st.markdown('<div class="sec">LEDGER ENTRIES</div>', unsafe_allow_html=True)

            # Format for display
            disp_l = ledger.copy()
            disp_l["Date"]            = disp_l["Date"].dt.strftime("%d %b %Y")
            disp_l["Debit"]           = disp_l["Debit"].apply(lambda x: inr(x) if x > 0 else "—")
            disp_l["Credit"]          = disp_l["Credit"].apply(lambda x: inr(x) if x > 0 else "—")
            disp_l["Running Balance"] = disp_l["Running Balance"].apply(inr)
            st.dataframe(disp_l[["Date","Type","Particulars","Debit","Credit","Running Balance"]],
                         use_container_width=True, hide_index=True, height=420)

            # Balance trend chart
            st.markdown('<div class="sec">BALANCE TREND</div>', unsafe_allow_html=True)
            fig_l = px.area(
                ledger, x="Date", y="Running Balance",
                title=f"{chosen_cust} — Running Balance Over Time",
                labels={"Running Balance": "₹ Outstanding"},
                color_discrete_sequence=["#ff6b6b"],
            )
            fig_l.update_layout(**ct(), height=280)
            fig_l.add_hline(y=0, line_dash="dash", line_color="#6bcb77", annotation_text="Cleared")
            fig_l.update_xaxes(gridcolor='rgba(255,255,255,.05)')
            fig_l.update_yaxes(gridcolor='rgba(255,255,255,.05)')
            st.plotly_chart(fig_l, use_container_width=True)

st.divider()
st.caption(f"SVC Vegetables v2.0 · Visakhapatnam · {'MongoDB' if MONGO_AVAILABLE else 'Session'} · Margin 5% · Excludes: Kanchili, Sender, SVC Staff")
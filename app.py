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

# ─── MongoDB ─────────────────────────────────────────────────────────────────
try:
    from pymongo import MongoClient, ASCENDING
    MONGO_URI = (
        st.secrets.get("MONGO_URI")          # Streamlit Cloud secrets
        or os.environ.get("MONGO_URI")        # local env var fallback
    )
    if not MONGO_URI:
        raise ValueError("MONGO_URI not set")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, tlsAllowInvalidCertificates=True)
    db = client["svc_vegetables"]
    # Ensure indexes on all collections
    db.sales.create_index([("date", ASCENDING), ("Name", ASCENDING)])
    db.receipts.create_index([("date", ASCENDING), ("Name", ASCENDING)])
    db.customers.create_index([("name", ASCENDING)], unique=True, background=True)
    db.areas.create_index([("name", ASCENDING)], unique=True, background=True)
    db.vegetables.create_index([("name", ASCENDING)], unique=True, background=True)
    db.veg_prices.create_index([("date", ASCENDING), ("item", ASCENDING)])
    MONGO_AVAILABLE = True
except Exception:
    MONGO_AVAILABLE = False
    db = None

MARGIN_PCT    = 0.05
# Areas whose data is never shown in any dashboard
EXCLUDE_AREAS = {"KANCHILI", "SENDER", "SVC STAFF", "HOTELS"}
# Individual customers excluded regardless of which area they appear under
EXCLUDE_CUSTOMERS = {"PTC", "SVC", "SVC BABU", "SVC BHASKAR", "SVC PARMESH",
                     "SVC PER", "SVC RAJU", "SVC SANTOSH", "SVC SUDHA",
                     "AUROBINDO", "JEEVAN", "PMAS", "DAMAGE",
                     "BANK OF BARODA", "IDBI 5135", "SBI FORT BRANCH"}

st.set_page_config(page_title="SVC Vegetables · Dashboard", page_icon="🥬",
                   layout="wide", initial_sidebar_state="expanded")

# ─── Password Gate ────────────────────────────────────────────────────────────
def _check_password():
    if st.session_state.get("_authenticated"):
        return True
    correct = st.secrets.get("passwords", {}).get("svc_password", "")
    st.markdown("## 🥬 SVC Vegetables · Login")
    pwd = st.text_input("Password", type="password", key="_pwd_input")
    if st.button("Login"):
        if pwd == correct:
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False

if not _check_password():
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
    st.session_state.store[date_str] = {"sales": sdf, "receipts": rdf}

def load_data(date_str):
    if date_str in st.session_state.store:
        d = st.session_state.store[date_str]
        return d["sales"], d["receipts"]
    if MONGO_AVAILABLE:
        s = list(db.sales.find({"date": date_str}, {"_id": 0}))
        r = list(db.receipts.find({"date": date_str}, {"_id": 0}))
        if s:
            sdf = pd.DataFrame(s)
            rdf = pd.DataFrame(r) if r else pd.DataFrame(
                columns=['Schedule','Name','OB','Receipts','Balance','Sales','Total','is_internal'])
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
    return sorted(dates, reverse=True)


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
sales = receipts = None
if active_date:
    sales, receipts = load_data(active_date)

st.markdown(f"""
<div style="background:linear-gradient(90deg,#0f2027,#2c5364);padding:18px 26px;border-radius:12px;margin-bottom:18px;border-left:5px solid #00d4aa;">
  <h2 style="margin:0;color:white;font-size:20px;">🥬 SVC Vegetables · Business Intelligence</h2>
  <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
    {'Viewing: <b style="color:#00d4aa">' + active_date + '</b> &nbsp;|&nbsp; ' + str(len(all_dates)) + ' days on record' if active_date else 'Upload files from the sidebar to begin'}
  </p>
</div>
""", unsafe_allow_html=True)

if not active_date or sales is None:
    st.info("👈  Upload today's files from the sidebar and click **Save & Analyze**.")
    st.stop()

a = analyze_day(sales, receipts)


# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════
TAB_TODAY, TAB_RUNNING, TAB_PREVWEEK, TAB_VEG, TAB_BADDEBT, TAB_PROFIT, TAB_REWARDS = st.tabs([
    "📊 Today", "📈 Running Balance", "📋 Unpaid Tracker",
    "🥦 Vegetables", "⚠️ Bad Debts", "💰 Profit", "🏆 Rewards"
])


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
    disp.columns = ['Area','Customer','Opening','Today Sales','Collected','Balance','Status','Pay %']
    for c in ['Opening','Today Sales','Collected','Balance']:
        disp[c] = disp[c].apply(inr)
    disp['Pay %'] = disp['Pay %'].apply(lambda x: f"{x}%")
    t1,t2,t3,t4 = st.tabs([f"All ({len(disp)})","🔴 Not Paid","🟡 Partial","🟢 Good"])
    with t1: st.dataframe(disp, use_container_width=True, hide_index=True, height=300)
    with t2: st.dataframe(disp[disp['Status'].str.contains('No Payment|Low')], use_container_width=True, hide_index=True, height=300)
    with t3: st.dataframe(disp[disp['Status'].str.contains('Partial')], use_container_width=True, hide_index=True, height=300)
    with t4: st.dataframe(disp[disp['Status'].str.contains('Good|Cleared')], use_container_width=True, hide_index=True, height=300)

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
            rb_from = st.date_input("From", value=date.today()-timedelta(days=7), key="rf")
        with f2:
            rb_to   = st.date_input("To",   value=date.today(), key="rt")
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
            # Default: previous week Mon-Sun
            today = date.today()
            last_mon = today - timedelta(days=today.weekday()+7)
            last_sun = last_mon + timedelta(days=6)
            pw_from = st.date_input("Week Start", value=last_mon, key="pw_from")
        with pw2:
            pw_to   = st.date_input("Week End",   value=last_sun, key="pw_to")
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

    all_dates_veg = get_all_dates()
    if not all_dates_veg:
        st.info("No data uploaded yet.")
    else:
        vf1, vf2 = st.columns([2, 2])
        with vf1:
            veg_from = st.date_input("From", value=date.today()-timedelta(days=30), key="vf")
        with vf2:
            veg_to   = st.date_input("To",   value=date.today(), key="vt")

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
            all_items = sorted(summary['Item'].tolist())
            default_items = summary.head(6)['Item'].tolist()
            sel_items = st.multiselect(
                "Select vegetables to compare prices",
                all_items, default=default_items, key="veg_sel"
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
            st_sum.columns = [
                'Vegetable','Days Sold','Total Kgs','Total Bags','Revenue','Avg Rate',
                'Min Rate','Max Rate','Transactions','Revenue %','Avg Daily Kgs','Unique Customers'
            ]
            st.dataframe(st_sum, use_container_width=True, hide_index=True, height=380)

            # ── DEEP DIVE: SINGLE ITEM ──
            st.markdown('<div class="sec">DEEP DIVE — SINGLE VEGETABLE</div>', unsafe_allow_html=True)
            dive_item = st.selectbox("Pick a vegetable to deep dive", all_items, key="veg_dive")
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
    worst = a['area'].sort_values('Collection_Eff').iloc[0]
    best  = a['area'].sort_values('Collection_Eff').iloc[-1]
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

st.divider()
st.caption(f"SVC Vegetables v2.0 · Visakhapatnam · {'MongoDB' if MONGO_AVAILABLE else 'Session'} · Margin 5% · Excludes: Kanchili, Sender, SVC Staff")
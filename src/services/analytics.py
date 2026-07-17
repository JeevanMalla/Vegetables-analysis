"""Balances, day analysis, period aggregations, vegetable analytics."""
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

from ..config import EXCLUDE_AREAS, EXCLUDE_CUSTOMERS, MARGIN_PCT
from . import database as dbs
from .storage import load_data

def get_customer_running_balance(customer_name, up_to_date_str):
    """
    Calculate running balance for a customer up to a given date.
    Formula: max(0, Initial_RB + sum(Sales) - sum(Receipts)) for all dates <= up_to_date
    """
    if not dbs.MONGO_AVAILABLE:
        return 0, 0  # (previous_rb, current_rb)

    # Get initial running balance (pre-6th May)
    init_doc = dbs.db.running_balance.find_one({"customer": customer_name})
    initial_rb = float(init_doc.get("initial_balance", 0)) if init_doc else 0

    # Get all sales and receipts for this customer up to the date
    sales_sum = list(dbs.db.sales.aggregate([
        {"$match": {"Name": customer_name, "date": {"$lte": up_to_date_str}}},
        {"$group": {"_id": None, "total": {"$sum": "$Amount"}}}
    ]))
    receipts_sum = list(dbs.db.receipts.aggregate([
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
        sales_sum_prev = list(dbs.db.sales.aggregate([
            {"$match": {"Name": customer_name, "date": {"$lte": prev_date}}},
            {"$group": {"_id": None, "total": {"$sum": "$Amount"}}}
        ]))
        receipts_sum_prev = list(dbs.db.receipts.aggregate([
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
    if dbs.MONGO_AVAILABLE:
        init_map = {d.get("customer"): float(d.get("initial_balance", 0) or 0)
                    for d in dbs.db.running_balance.find({}, {"_id": 0})}
        sales_map = {d["_id"]: float(d["total"] or 0) for d in dbs.db.sales.aggregate([
            {"$match": {"date": {"$lte": up_to_date_str},
                        "Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$Name", "total": {"$sum": "$Amount"}}}])}
        rcpt_map = {d["_id"]: float(d["total"] or 0) for d in dbs.db.receipts.aggregate([
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
    if dbs.MONGO_AVAILABLE:
        s = list(dbs.db.sales.aggregate([
            {"$match": {"Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$date", "sales": {"$sum": "$Amount"}}}]))
        r = list(dbs.db.receipts.aggregate([
            {"$match": {"Schedule": {"$nin": list(EXCLUDE_AREAS)},
                        "Name": {"$nin": list(EXCLUDE_CUSTOMERS)}}},
            {"$group": {"_id": "$date", "receipts": {"$sum": "$Receipts"}}}]))
        init_total = sum(float(d.get("initial_balance", 0) or 0)
                         for d in dbs.db.running_balance.find({}, {"_id": 0}))
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

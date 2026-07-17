"""Per-date persistence: MongoDB collections + per-session cache."""
import pandas as pd
import streamlit as st

from ..config import EXCLUDE_AREAS, EXCLUDE_CUSTOMERS
from . import database as dbs


def init_session_store():
    if "store" not in st.session_state:
        st.session_state.store = {}

def save_data(date_str, sdf, rdf):
    if dbs.MONGO_AVAILABLE:
        dbs.db.sales.delete_many({"date": date_str})
        s = sdf.copy(); s["date"] = date_str
        if not s.empty:
            dbs.db.sales.insert_many(s.to_dict("records"))
        # Only touch receipts collection if rdf has actual rows
        if not rdf.empty:
            dbs.db.receipts.delete_many({"date": date_str})
            r = rdf.copy(); r["date"] = date_str
            dbs.db.receipts.insert_many(r.to_dict("records"))
        # Upsert master customers list (all rows are already external — excluded at parse time)
        cust_external = rdf
        for _, row in cust_external.iterrows():
            dbs.db.customers.update_one(
                {"name": row['Name']},
                {"$set": {"name": row['Name'], "area": row['Schedule']},
                 "$setOnInsert": {"created_date": date_str}},
                upsert=True
            )
        # Upsert master areas list
        for area in cust_external['Schedule'].dropna().unique():
            dbs.db.areas.update_one(
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
            dbs.db.vegetables.update_one(
                {"name": item_name},
                {"$set": {"name": item_name},
                 "$setOnInsert": {"first_seen": date_str}},
                upsert=True
            )
            dbs.db.veg_prices.update_one(
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
        if (_existing_r is None or _existing_r.empty) and dbs.MONGO_AVAILABLE:
            _r_docs = list(dbs.db.receipts.find({"date": date_str}, {"_id": 0}))
            if _r_docs:
                _existing_r = pd.DataFrame(_r_docs)
        if _existing_r is not None and not _existing_r.empty:
            rdf = _existing_r
    st.session_state.store[date_str] = {"sales": sdf, "receipts": rdf}

def load_data(date_str):
    if date_str in st.session_state.store:
        d = st.session_state.store[date_str]
        return d["sales"], d["receipts"]
    if dbs.MONGO_AVAILABLE:
        s = list(dbs.db.sales.find({"date": date_str}, {"_id": 0}))
        r = list(dbs.db.receipts.find({"date": date_str}, {"_id": 0}))
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
    if dbs.MONGO_AVAILABLE:
        dates |= set(dbs.db.sales.distinct("date"))
        dates |= set(dbs.db.receipts.distinct("date"))   # collection-only days count too
    return sorted(dates, reverse=True)

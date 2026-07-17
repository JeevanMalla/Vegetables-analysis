"""MongoDB connection (one per server process) and business settings."""
import os
import streamlit as st

from ..config import DEFAULT_MONTHLY_EXPENSE

db = None
MONGO_AVAILABLE = False

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

def connect():
    """(Re)establish the shared connection. Call once per rerun, before set_page_config-dependent UI."""
    global db, MONGO_AVAILABLE
    try:
        db = _get_db()
        MONGO_AVAILABLE = True
    except Exception:
        db = None
        MONGO_AVAILABLE = False
    return MONGO_AVAILABLE

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

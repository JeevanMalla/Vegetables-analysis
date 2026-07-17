"""
SVC Vegetables Business Dashboard  v3.0
========================================
Thin entry point — all logic lives in src/:
  src/config.py         business constants
  src/services/         database, parsing, storage, analytics, billing, printing
  src/ui/               theme, auth, sidebar, tabs/ (one module per tab)
Run: streamlit run app.py
"""
import streamlit as st
from datetime import date, datetime

st.set_page_config(page_title="SVC Vegetables · Dashboard", page_icon="🥬",
                   layout="wide", initial_sidebar_state="expanded")

from src.services import database as dbs          # noqa: E402
dbs.connect()

from src.ui.auth import require_login             # noqa: E402
require_login()

from src.ui.theme import inject_css               # noqa: E402
inject_css()

from src.services.storage import init_session_store, load_data   # noqa: E402
from src.services.analytics import analyze_day                    # noqa: E402
from src.ui import sidebar                                        # noqa: E402
from src.ui.tabs import (overview, today, reports, bills, running, unpaid,   # noqa: E402
                         vegetables, bad_debts, profit, rewards, ledger)

init_session_store()
all_dates = sidebar.render()

# ── Load the active day ───────────────────────────────────────────
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
    if not dbs.MONGO_AVAILABLE:
        st.error("⚠️ Database not reachable right now — check your internet / MongoDB Atlas and reload the page. "
                 "You can still upload today's files to work in this session.")
    st.info("👈  Upload today's files from the sidebar and click **Save & Analyze**.")
    st.stop()

a = analyze_day(sales, receipts)

ctx = dict(a=a, sales=sales, receipts=receipts, active_date=active_date,
           all_dates=all_dates, LATEST_DATE=LATEST_DATE)

# ── Tabs ──────────────────────────────────────────────────────────
_tab_modules = [
    ("📌 Overview", overview), ("📊 Today", today), ("📑 Reports", reports),
    ("🖨️ Print Bills", bills), ("📈 Running Balance", running),
    ("📋 Unpaid Tracker", unpaid), ("🥦 Vegetables", vegetables),
    ("⚠️ Bad Debts", bad_debts), ("💰 Profit", profit),
    ("🏆 Rewards", rewards), ("📒 Ledger", ledger),
]
for _tab, (_, _mod) in zip(st.tabs([t for t, _ in _tab_modules]), _tab_modules):
    with _tab:
        _mod.render(ctx)

st.divider()
st.caption(f"SVC Vegetables v3.0 · Visakhapatnam · "
           f"{'MongoDB' if dbs.MONGO_AVAILABLE else 'Session'} · Margin 5% · "
           f"Excludes internal areas & accounts")

"""Sidebar: uploads, settings, history. Returns the list of available dates."""
from .common import *  # noqa: F401,F403


def render():
    with st.sidebar:
        st.markdown("## 🥬 SVC Vegetables")
        st.caption("Visakhapatnam · 5% margin")
        if dbs.MONGO_AVAILABLE:
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
                    if dbs.MONGO_AVAILABLE:
                        all_custs_in_range |= set(dbs.db.sales.distinct("Name", {"date": {"$gte": from_date_str, "$lte": to_date_str}}))
                        all_custs_in_range |= set(dbs.db.receipts.distinct("Name", {"date": {"$gte": from_date_str, "$lte": to_date_str}}))

                    if not all_custs_in_range:
                        st.warning("No data found in selected date range.")
                    else:
                        # Build running balance for each customer
                        crb_rows = []
                        # Get all dates in range
                        sorted_dates = sorted([d for d in all_avail_dates if from_date_str <= d <= to_date_str])

                        for cust in sorted(all_custs_in_range):
                            if dbs.MONGO_AVAILABLE:
                                # Get daily breakdown
                                sales_by_date = {d: 0 for d in sorted_dates}
                                receipts_by_date = {d: 0 for d in sorted_dates}

                                s_docs = list(dbs.db.sales.find({"Name": cust, "date": {"$gte": from_date_str, "$lte": to_date_str}}, {"_id": 0, "date": 1, "Amount": 1}))
                                r_docs = list(dbs.db.receipts.find({"Name": cust, "date": {"$gte": from_date_str, "$lte": to_date_str}}, {"_id": 0, "date": 1, "Receipts": 1}))

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
    return all_dates

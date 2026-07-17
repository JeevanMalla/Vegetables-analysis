"""Reports tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    monthly_expense = get_monthly_expense()

    if not dbs.MONGO_AVAILABLE:
        st.warning("Reports need MongoDB. Session-only mode has limited history.")

    # ── ONE-TIME SETUP: INITIAL RUNNING BALANCES (BULK) ──────────
    with st.expander("🏦 Initial Running Balances — one-time setup (balance before 8 May)"):
        st.caption("Enter each customer's outstanding balance as it stood before the first upload (8 May). "
                   "The app carries it forward automatically: Running Balance = Initial + Sales − Receipts.")
        if dbs.MONGO_AVAILABLE:
            _cust_docs = list(dbs.db.customers.find({}, {"_id": 0, "name": 1, "area": 1}))
            _init_map = {d.get("customer"): float(d.get("initial_balance", 0) or 0)
                         for d in dbs.db.running_balance.find({}, {"_id": 0})}
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
                            dbs.db.running_balance.update_one(
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
            _qs_known = sorted(set(dbs.db.areas.distinct("name")) - EXCLUDE_AREAS) if dbs.MONGO_AVAILABLE else []
            qs_areas = st.multiselect("Area filter", _qs_known, default=_qs_known,
                                      key="qs_areas") if _qs_known else []
        with q4:
            qs_name = st.text_input("Search name", key="qs_name")
        qs_hide_zero = st.checkbox("Hide customers with no activity and zero balance",
                                   value=True, key="qs_zero")

        rep_date_str = rep_date.strftime("%Y-%m-%d")

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
        if dbs.MONGO_AVAILABLE:
            for _doc in dbs.db.customers.find({}, {"_id": 0, "name": 1, "area": 1}):
                _qs_area_map.setdefault(_doc.get("name"), _doc.get("area", ""))

        # Running Balance = OVERALL tracked figure up to & incl. the report day
        _rb_now = get_running_balances_bulk(rep_date_str)
        _rb_map = dict(zip(_rb_now['Name'], _rb_now['running_balance'])) if not _rb_now.empty else {}

        # Closing Balance = OB + day sales − day receipts, computed from the actual
        # sales list (the receipts file's own Balance column can lag the sales data).
        # OB source: today's receipts file; fallback = previous day's closing Balance.
        _ob_map = {}
        if _qday_r is not None and not _qday_r.empty and 'OB' in _qday_r.columns:
            _ob_map = dict(zip(_qday_r['Name'],
                               pd.to_numeric(_qday_r['OB'], errors='coerce').fillna(0)))
        _prev_cb_map = {}
        if not _ob_map:
            _prior = [d for d in get_all_dates() if d < rep_date_str]
            if _prior:
                _, _prev_r = load_data(max(_prior))
                if _prev_r is not None and not _prev_r.empty and 'Balance' in _prev_r.columns:
                    _prev_cb_map = dict(zip(_prev_r['Name'],
                                            pd.to_numeric(_prev_r['Balance'], errors='coerce').fillna(0)))

        _qnames = ((set(_p_sales_map) | set(_day_sales_map) | set(_day_rcpt_map) | set(_rb_map))
                   - EXCLUDE_CUSTOMERS)
        qdf = pd.DataFrame([{
            "Area": str(_qs_area_map.get(n, "") or ""),
            "Name": n,
            "Period_Sales": float(_p_sales_map.get(n, 0)),
            "Running_Balance": float(_rb_map.get(n, 0)),
            "Day_Sales": float(_day_sales_map.get(n, 0)),
            "Day_Receipts": float(_day_rcpt_map.get(n, 0)),
            "Overall_Balance": (float(_ob_map.get(n, _prev_cb_map.get(n, 0)))
                                + float(_day_sales_map.get(n, 0))
                                - float(_day_rcpt_map.get(n, 0))),
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
                                   'Running Balance (overall)', 'Day Sales', 'Day Receipts',
                                   'Closing Balance']
                st.dataframe(_q_show, use_container_width=True, hide_index=True, height=360)
                st.caption(f"**{len(qdf)} customers** · Period Sales {inr(qdf['Period_Sales'].sum())} · "
                           f"Day Sales {inr(qdf['Day_Sales'].sum())} · Day Receipts {inr(qdf['Day_Receipts'].sum())} · "
                           f"Closing Balance {inr(qdf['Overall_Balance'].sum())} · "
                           f"Running Balance {inr(qdf['Running_Balance'].sum())}")

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

        _known_areas = sorted(set(dbs.db.areas.distinct("name")) - EXCLUDE_AREAS) if dbs.MONGO_AVAILABLE else []
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
    if not dbs.MONGO_AVAILABLE:
        st.info("MongoDB required for account analysis.")
    else:
        _excl_acct = set(dbs.db.receipts.distinct("Name", {"Schedule": {"$in": list(EXCLUDE_AREAS)}}))
        _acct_names = sorted((set(dbs.db.sales.distinct("Name")) | set(dbs.db.receipts.distinct("Name")))
                             - EXCLUDE_CUSTOMERS - _excl_acct)
        if not _acct_names:
            st.info("No customers yet.")
        else:
            acct = st.selectbox("Select Account", _acct_names, key="acct_sel")
            _sd = list(dbs.db.sales.aggregate([
                {"$match": {"Name": acct}},
                {"$group": {"_id": "$date", "sales": {"$sum": "$Amount"}}}]))
            _rd = list(dbs.db.receipts.aggregate([
                {"$match": {"Name": acct}},
                {"$group": {"_id": "$date", "receipts": {"$sum": "$Receipts"}}}]))
            _init_doc = dbs.db.running_balance.find_one({"customer": acct})
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

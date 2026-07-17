"""Overview tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

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

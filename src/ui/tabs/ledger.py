"""Ledger tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

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
    if dbs.MONGO_AVAILABLE:
        all_custs |= set(dbs.db.sales.distinct("Name"))
        all_custs |= set(dbs.db.receipts.distinct("Name"))
        all_custs -= set(dbs.db.receipts.distinct("Name", {"Schedule": {"$in": list(EXCLUDE_AREAS)}}))
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
        if dbs.MONGO_AVAILABLE:
            s_rows = list(dbs.db.sales.find({"Name": chosen_cust}, {"_id": 0}))
            r_rows = list(dbs.db.receipts.find({"Name": chosen_cust}, {"_id": 0}))
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

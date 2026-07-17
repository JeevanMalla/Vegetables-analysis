"""Running tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

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

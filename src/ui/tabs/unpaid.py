"""Unpaid tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">📋 UNPAID TRACKER — HOW MUCH WAS NOT GIVEN IN THE SELECTED WEEK</div>', unsafe_allow_html=True)
    st.caption("Pick any week to see who still owes money from that week. Use this every day to follow up and collect.")

    all_dates_pw = get_all_dates()
    if not all_dates_pw:
        st.info("No data uploaded yet.")
    else:
        pw1, pw2, pw3 = st.columns([2, 2, 3])
        with pw1:
            # Default: last 7 days of available data
            pw_from = st.date_input("Week Start", value=LATEST_DATE-timedelta(days=6), key="pw_from")
        with pw2:
            pw_to   = st.date_input("Week End",   value=LATEST_DATE, key="pw_to")
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

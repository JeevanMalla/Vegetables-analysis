"""Vegetables tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">🥦 VEGETABLE PRICE TRACKER & ANALYTICS</div>', unsafe_allow_html=True)
    st.caption("Track how prices move day-to-day, which vegetables drive the most revenue, and volume sold per item.")

    with st.expander("🌿 Telugu Names — shown on printed bills; edit or add for new vegetables"):
        if dbs.MONGO_AVAILABLE:
            _vdocs = list(dbs.db.vegetables.find({}, {"_id": 0, "name": 1, "telugu_name": 1, "description": 1}))
            if _vdocs:
                _vdf = pd.DataFrame(_vdocs)
                for _c in ["telugu_name", "description"]:
                    if _c not in _vdf.columns:
                        _vdf[_c] = ""
                _vdf = (_vdf[["name", "telugu_name", "description"]].fillna("")
                        .sort_values("name").reset_index(drop=True))
                _vedit = st.data_editor(_vdf, hide_index=True, use_container_width=True,
                                        height=350, disabled=["name"], key="veg_telugu_editor",
                                        column_config={
                                            "name": "Vegetable (English)",
                                            "telugu_name": "Telugu Name",
                                            "description": "Description"})
                if st.button("💾 Save Telugu Names", use_container_width=True, key="veg_telugu_save"):
                    for _, _vrow in _vedit.iterrows():
                        dbs.db.vegetables.update_one(
                            {"name": _vrow["name"]},
                            {"$set": {"telugu_name": str(_vrow["telugu_name"]).strip(),
                                      "description": str(_vrow["description"]).strip()}})
                    st.success(f"✅ Saved {len(_vedit)} vegetables — bills will use the new names immediately.")
            else:
                st.info("No vegetables yet — upload sales first.")
        else:
            st.info("MongoDB required to store Telugu names.")

    all_dates_veg = get_all_dates()
    if not all_dates_veg:
        st.info("No data uploaded yet.")
    else:
        vf1, vf2 = st.columns([2, 2])
        with vf1:
            veg_from = st.date_input("From", value=LATEST_DATE-timedelta(days=30), key="vf")
        with vf2:
            veg_to   = st.date_input("To",   value=LATEST_DATE, key="vt")

        va = build_veg_analytics(all_dates_veg, veg_from, veg_to)

        if va is None:
            st.warning("No sales data found for that date range.")
        else:
            summary  = va['summary']
            daily    = va['daily']
            grand_total = va['grand_total']
            n_days   = len(va['dates_used'])
            n_items  = len(summary)

            # ── KPIs ──
            top_item  = summary.iloc[0]
            total_kgs = summary['total_kgs'].sum()
            v1, v2, v3, v4 = st.columns(4)
            for col, args in zip([v1,v2,v3,v4],[
                ("green",  "Total Revenue (period)", inr(grand_total),
                 f"{n_days} day(s) · {n_items} vegetables"),
                ("yellow", "Total Volume Sold",      f"{total_kgs:,.0f} Kgs",
                 f"Across all vegetables"),
                ("purple", "Top Vegetable",          top_item['Item'],
                 f"{inr(top_item['total_amount'])} · {top_item['revenue_pct']:.1f}% of sales"),
                ("green",  "Avg Daily Revenue",      inr(grand_total / max(n_days, 1)),
                 f"Per day average"),
            ]):
                with col: st.markdown(kpi(*args), unsafe_allow_html=True)

            # ── REVENUE CONTRIBUTION ──
            st.markdown('<div class="sec">REVENUE CONTRIBUTION BY VEGETABLE</div>', unsafe_allow_html=True)
            rc1, rc2 = st.columns([3, 2])
            with rc1:
                fig_contrib = px.bar(
                    summary.head(20), x='total_amount', y='Item', orientation='h',
                    color='revenue_pct',
                    color_continuous_scale=[(0,'#2c5364'),(0.4,'#ffd93d'),(1,'#6bcb77')],
                    text='revenue_pct',
                    title="Top 20 Vegetables by Revenue",
                    labels={'total_amount':'Revenue (₹)', 'Item':'', 'revenue_pct':'% of Sales'}
                )
                fig_contrib.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                fig_contrib.update_layout(**ct(), height=460, coloraxis_showscale=False)
                fig_contrib.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_contrib, use_container_width=True)
            with rc2:
                fig_pie = px.pie(
                    summary.head(10), names='Item', values='total_amount', hole=0.5,
                    title="Revenue Share — Top 10",
                    color_discrete_sequence=px.colors.qualitative.Bold
                )
                fig_pie.update_layout(**ct(), height=280, showlegend=True,
                                      legend=dict(font_size=9))
                fig_pie.update_traces(textinfo='percent', textfont_size=10)
                st.plotly_chart(fig_pie, use_container_width=True)

                # Volume share
                fig_vol_pie = px.pie(
                    summary.head(10), names='Item', values='total_kgs', hole=0.5,
                    title="Volume Share (Kgs) — Top 10",
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                fig_vol_pie.update_layout(**ct(), height=220, showlegend=False)
                fig_vol_pie.update_traces(textinfo='label+percent', textfont_size=9)
                st.plotly_chart(fig_vol_pie, use_container_width=True)

            # ── PRICE TREND OVER TIME ──
            st.markdown('<div class="sec">PRICE TREND — RATE PER KG OVER TIME</div>', unsafe_allow_html=True)
            _tel_map = get_veg_telugu_map()
            _tel_label = lambda x: f"{x} · {_tel_map[x]}" if _tel_map.get(x) else x
            all_items = sorted(summary['Item'].tolist())
            default_items = summary.head(6)['Item'].tolist()
            sel_items = st.multiselect(
                "Select vegetables to compare prices",
                all_items, default=default_items, key="veg_sel",
                format_func=_tel_label
            )
            if sel_items:
                price_df = daily[daily['Item'].isin(sel_items)]
                fig_price = px.line(
                    price_df, x='date_str', y='avg_rate', color='Item',
                    markers=True,
                    title="Average Rate (₹/Kg) — Day by Day",
                    labels={'date_str':'Date', 'avg_rate':'Rate (₹/Kg)', 'Item':'Vegetable'}
                )
                fig_price.update_layout(**ct(), height=360)
                fig_price.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                fig_price.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_price, use_container_width=True)

                # Volume (Kgs) over time
                fig_vol = px.bar(
                    price_df, x='date_str', y='total_kgs', color='Item',
                    barmode='group',
                    title="Volume Sold (Kgs) — Day by Day",
                    labels={'date_str':'Date', 'total_kgs':'Kgs Sold', 'Item':'Vegetable'}
                )
                fig_vol.update_layout(**ct(), height=280)
                fig_vol.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                st.plotly_chart(fig_vol, use_container_width=True)

            # ── SUMMARY TABLE ──
            st.markdown('<div class="sec">VEGETABLE SUMMARY TABLE</div>', unsafe_allow_html=True)
            st_sum = summary.copy()
            st_sum['avg_rate']    = st_sum['avg_rate'].apply(lambda x: f"₹{x:.2f}/kg")
            st_sum['min_rate']    = st_sum['min_rate'].apply(lambda x: f"₹{x:.2f}")
            st_sum['max_rate']    = st_sum['max_rate'].apply(lambda x: f"₹{x:.2f}")
            st_sum['total_amount']= st_sum['total_amount'].apply(inr)
            st_sum['total_kgs']   = st_sum['total_kgs'].apply(lambda x: f"{x:,.1f}")
            st_sum['revenue_pct'] = st_sum['revenue_pct'].apply(lambda x: f"{x:.1f}%")
            st_sum['avg_daily_kgs']= st_sum['avg_daily_kgs'].apply(lambda x: f"{x:,.1f}")
            st_sum.insert(1, 'Telugu', st_sum['Item'].map(_tel_map).fillna(''))
            st_sum.columns = [
                'Vegetable','Telugu','Days Sold','Total Kgs','Total Bags','Revenue','Avg Rate',
                'Min Rate','Max Rate','Transactions','Revenue %','Avg Daily Kgs','Unique Customers'
            ]
            st.dataframe(st_sum, use_container_width=True, hide_index=True, height=380)

            # ── DEEP DIVE: SINGLE ITEM ──
            st.markdown('<div class="sec">DEEP DIVE — SINGLE VEGETABLE</div>', unsafe_allow_html=True)
            dive_item = st.selectbox("Pick a vegetable to deep dive", all_items, key="veg_dive",
                                     format_func=_tel_label)
            if dive_item:
                item_daily = daily[daily['Item'] == dive_item].copy()
                item_raw   = va['raw'][va['raw']['Item'] == dive_item].copy()

                d1, d2, d3, d4 = st.columns(4)
                item_s = summary[summary['Item'] == dive_item].iloc[0]
                for col, args in zip([d1, d2, d3, d4],[
                    ("green",  "Total Revenue",   inr(item_s['total_amount']),
                     f"{item_s['revenue_pct']:.1f}% of all veg sales"),
                    ("yellow", "Total Volume",    f"{item_s['total_kgs']:,.1f} Kgs",
                     f"{int(item_s['total_bags'])} bags"),
                    ("purple", "Avg Rate",        f"₹{item_s['avg_rate']:.2f}/kg",
                     f"Min ₹{item_s['min_rate']:.2f} · Max ₹{item_s['max_rate']:.2f}"),
                    ("green",  "Unique Customers",str(int(item_s['unique_customers'])),
                     f"across {int(item_s['days_sold'])} day(s)"),
                ]):
                    with col: st.markdown(kpi(*args), unsafe_allow_html=True)

                dd1, dd2 = st.columns(2)
                with dd1:
                    fig_dd_rate = px.line(
                        item_daily, x='date_str', y=['avg_rate','min_rate','max_rate'],
                        markers=True,
                        title=f"{dive_item} — Rate Range (₹/Kg)",
                        labels={'date_str':'Date','value':'Rate (₹/Kg)','variable':''}
                    )
                    fig_dd_rate.update_layout(**ct(), height=280)
                    fig_dd_rate.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                    fig_dd_rate.update_yaxes(gridcolor='rgba(255,255,255,.05)')
                    st.plotly_chart(fig_dd_rate, use_container_width=True)
                with dd2:
                    fig_dd_vol = px.bar(
                        item_daily, x='date_str', y='total_kgs',
                        color='total_amount',
                        color_continuous_scale='Teal',
                        title=f"{dive_item} — Kgs Sold (bar colour = revenue)",
                        labels={'date_str':'Date','total_kgs':'Kgs Sold','total_amount':'Revenue (₹)'}
                    )
                    fig_dd_vol.update_layout(**ct(), height=280, coloraxis_showscale=False)
                    fig_dd_vol.update_xaxes(gridcolor='rgba(255,255,255,.05)', tickangle=-30)
                    st.plotly_chart(fig_dd_vol, use_container_width=True)

                # Who buys this vegetable the most?
                st.markdown(f'<div class="sec">WHO BUYS {dive_item.upper()} THE MOST?</div>', unsafe_allow_html=True)
                cust_buy = item_raw.groupby('Name').agg(
                    total_kgs=('Kgs','sum'),
                    total_amount=('Amount','sum'),
                    avg_rate=('Rate','mean'),
                    times_purchased=('Amount','count'),
                ).reset_index().sort_values('total_amount', ascending=False).head(20)
                fig_cust_buy = px.bar(
                    cust_buy, x='total_amount', y='Name', orientation='h',
                    color='total_kgs',
                    color_continuous_scale='Teal',
                    title=f"Top Buyers of {dive_item}",
                    labels={'total_amount':'Revenue (₹)','Name':'','total_kgs':'Kgs'}
                )
                fig_cust_buy.update_layout(**ct(), height=420, coloraxis_showscale=True,
                                           coloraxis_colorbar=dict(title='Kgs'))
                fig_cust_buy.update_xaxes(gridcolor='rgba(255,255,255,.05)')
                st.plotly_chart(fig_cust_buy, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# TAB 5 — BAD DEBTS & LOSS
# ─────────────────────────────────────────────────────────────

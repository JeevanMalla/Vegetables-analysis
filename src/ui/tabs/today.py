"""Today tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">TODAY\'S SNAPSHOT</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5 = st.columns(5)
    for col, args in zip([c1,c2,c3,c4,c5],[
        ("green","Today Sales", inr(a['total_sales']), f"{len(sales)} lines"),
        ("green","Gross Profit 5%", inr(a['profit_potential']), "On today's dispatch"),
        ("yellow","Cash Collected", inr(a['total_receipts']), f"{a['total_receipts']/max(a['total_sales'],1)*100:.1f}% of sales"),
        ("red","Total Outstanding", inr(a['total_balance']), "All customers"),
        ("red","Profit At Risk", inr(a['profit_potential']-a['profit_realized']), "Uncollected margin"),
    ]):
        with col: st.markdown(kpi(*args), unsafe_allow_html=True)

    st.markdown('<div class="sec">WHERE IS MONEY STUCK?</div>', unsafe_allow_html=True)
    ca, cb = st.columns([3,2])
    with ca:
        top20 = a['customers'].nlargest(20,'Balance')
        fig = px.bar(top20, x='Balance', y='Name', orientation='h',
                     color='Balance', color_continuous_scale=["#ffd93d","#ff6b6b","#c0392b"],
                     title="Top 20 Customers — Outstanding Balance",
                     labels={'Balance':'₹','Name':''})
        fig.update_layout(**ct(), height=420, coloraxis_showscale=False,
                          yaxis=dict(tickfont=dict(size=10)))
        fig.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fig, use_container_width=True)
    with cb:
        fig2 = px.pie(a['area'], names='Schedule', values='Balance', hole=.55,
                      title="Outstanding by Area",
                      color_discrete_sequence=px.colors.sequential.Teal)
        fig2.update_layout(**ct(), height=240, showlegend=True, legend=dict(font_size=10))
        st.plotly_chart(fig2, use_container_width=True)
        ad = a['area'][['Schedule','Receipts','Balance','Collection_Eff']].copy()
        ad.columns=['Area','Collected','Outstanding','Coll %']
        ad['Collected']   = ad['Collected'].apply(inr)
        ad['Outstanding'] = ad['Outstanding'].apply(inr)
        ad['Coll %']      = ad['Coll %'].apply(lambda x: f"{x}%")
        st.dataframe(ad, use_container_width=True, hide_index=True)

    st.markdown('<div class="sec">CUSTOMER HEALTH</div>', unsafe_allow_html=True)
    disp = a['customers'][['Schedule','Name','OB','Sales','Receipts','Balance','status','collection_rate']].copy()

    # Calculate Running Balance for each customer (2 bulk queries, not 4 per row)
    if dbs.MONGO_AVAILABLE and active_date:
        _prev_day = (datetime.strptime(active_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        _rb_curr = get_running_balances_bulk(active_date)
        _rb_prev = get_running_balances_bulk(_prev_day)
        _curr_map = dict(zip(_rb_curr['Name'], _rb_curr['running_balance']))
        _prev_map = dict(zip(_rb_prev['Name'], _rb_prev['running_balance']))
        disp = disp.reset_index(drop=True)
        disp['Prev_Running_Balance'] = disp['Name'].map(_prev_map).fillna(0)
        disp['Curr_Running_Balance'] = disp['Name'].map(_curr_map).fillna(0)
    else:
        disp['Prev_Running_Balance'] = 0
        disp['Curr_Running_Balance'] = disp['Balance']

    disp.columns = ['Area','Customer','Opening','Today Sales','Collected','Balance','Status','Pay %','Prev Running Balance','Curr Running Balance']
    for c in ['Opening','Today Sales','Collected','Balance','Prev Running Balance','Curr Running Balance']:
        disp[c] = disp[c].apply(inr)
    disp['Pay %'] = disp['Pay %'].apply(lambda x: f"{x}%")
    disp['Status'] = disp['Status'].astype(str)  # guard against float dtype when receipts empty
    t1,t2,t3,t4 = st.tabs([f"All ({len(disp)})","🔴 Not Paid","🟡 Partial","🟢 Good"])
    with t1: st.dataframe(disp, use_container_width=True, hide_index=True, height=300)
    with t2: st.dataframe(disp[disp['Status'].str.contains('No Payment|Low', na=False)], use_container_width=True, hide_index=True, height=300)
    with t3: st.dataframe(disp[disp['Status'].str.contains('Partial', na=False)], use_container_width=True, hide_index=True, height=300)
    with t4: st.dataframe(disp[disp['Status'].str.contains('Good|Cleared', na=False)], use_container_width=True, hide_index=True, height=300)

    st.markdown('<div class="sec">SALES BREAKDOWN</div>', unsafe_allow_html=True)
    s1,s2 = st.columns(2)
    with s1:
        fi = px.bar(a['sales_by_item'].reset_index(), x='Amount', y='Item', orientation='h',
                    color='Amount', color_continuous_scale='Teal', title='Revenue by Item',
                    labels={'Amount':'₹','Item':''})
        fi.update_layout(**ct(), height=300, coloraxis_showscale=False)
        fi.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fi, use_container_width=True)
    with s2:
        fc = px.bar(a['sales_by_cust'].head(15).reset_index(), x='Amount', y='Name', orientation='h',
                    color='Amount', color_continuous_scale='Purp', title="Top 15 Customers by Purchase",
                    labels={'Amount':'₹','Name':''})
        fc.update_layout(**ct(), height=300, coloraxis_showscale=False)
        fc.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fc, use_container_width=True)


# ─────────────────────────────────────────────────────────────
# TAB — REPORTS (Day/Period Summary · Credits Increasing · Account Analysis)
# ─────────────────────────────────────────────────────────────

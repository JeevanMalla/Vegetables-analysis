"""Rewards tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">🏆 CUSTOMER REWARDS & RANKINGS</div>', unsafe_allow_html=True)
    st.caption("Based on profit realized (collections × 5%) — your truly valuable customers")

    rb_all_rew = build_running_balance(get_all_dates())
    if rb_all_rew:
        rew = rb_all_rew['cust_grp']
        p_col = 'Cumulative_Profit_Realized'; s_col = 'Period_Sales'
        r_col = 'Period_Receipts'; b_col = 'Running_Balance'; rate_col = 'Collection_Rate'
        pp_col = 'Cumulative_Profit_Potential'
    else:
        rew = a['customers'].copy()
        rew['Cumulative_Profit_Realized']  = rew['profit_realized']
        rew['Cumulative_Profit_Potential'] = rew['profit_potential']
        rew['Period_Sales']     = rew['Sales']
        rew['Period_Receipts']  = rew['Receipts']
        rew['Running_Balance']  = rew['Balance']
        rew['Collection_Rate']  = rew['collection_rate']
        rew['Area']             = rew['Schedule']
        rew['Days_Active']      = 1
        p_col='Cumulative_Profit_Realized'; s_col='Period_Sales'
        r_col='Period_Receipts'; b_col='Running_Balance'; rate_col='Collection_Rate'
        pp_col='Cumulative_Profit_Potential'

    rew = rew[~rew['Area'].isin(EXCLUDE_AREAS)].sort_values(p_col, ascending=False)

    # Medal cards
    medals = ["🥇","🥈","🥉"]
    top3_cols = st.columns(3)
    for i, (col, (_, row)) in enumerate(zip(top3_cols, rew.head(3).iterrows())):
        with col:
            st.markdown(f"""
<div class="reward-card">
  <div class="rank">{medals[i]}</div>
  <div class="name">{row['Name']}</div>
  <div style="font-size:11px;opacity:.6;margin-bottom:8px;">{row['Area']}</div>
  <div class="amt">{inr(row[p_col])}</div>
  <div style="font-size:11px;opacity:.5;margin-top:6px;">profit contributed · {float(row[rate_col]):.1f}% collection rate</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec">TOP 20 — MOST PROFITABLE CUSTOMERS</div>', unsafe_allow_html=True)
    top20r = rew.head(20)
    fig_rew = px.bar(top20r, x=p_col, y='Name', orientation='h',
                     color=rate_col,
                     color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'gold')],
                     range_color=[0,100],
                     title="Profit Contributed (colour = collection rate)",
                     labels={p_col:'Profit Earned (₹)','Name':''})
    fig_rew.update_layout(**ct(), height=540, coloraxis_colorbar=dict(title='Coll %'))
    fig_rew.update_xaxes(gridcolor='rgba(255,255,255,.05)')
    st.plotly_chart(fig_rew, use_container_width=True)

    st.markdown('<div class="sec">🏅 BEST AREAS</div>', unsafe_allow_html=True)
    ar = a['area'].sort_values('Profit_Realized', ascending=False)
    fig_ar = px.bar(ar, x='Schedule', y=['Profit_Potential','Profit_Realized'],
                    barmode='group',
                    color_discrete_map={'Profit_Potential':'rgba(0,212,170,.3)','Profit_Realized':'#00d4aa'},
                    title="Area Profit: Potential vs Realized",
                    labels={'value':'₹','Schedule':'Area'})
    fig_ar.update_layout(**ct(), height=300)
    fig_ar.update_yaxes(gridcolor='rgba(255,255,255,.05)')
    st.plotly_chart(fig_ar, use_container_width=True)

    st.markdown('<div class="sec">🔴 BOTTOM 10 — LOSS MAKERS (PROFIT YOU NEVER GOT)</div>', unsafe_allow_html=True)
    rew['Profit_Gap'] = rew[pp_col] - rew[p_col]
    bot10 = rew.nlargest(10,'Profit_Gap')
    fig_bot = px.bar(bot10, x='Profit_Gap', y='Name', orientation='h',
                     color='Profit_Gap', color_continuous_scale=["#ff9a3c","#ff6b6b","#c0392b"],
                     title="Profit Gap — Customers who buy but don't pay",
                     labels={'Profit_Gap':'Uncollected Profit (₹)','Name':''})
    fig_bot.update_layout(**ct(), height=380, coloraxis_showscale=False)
    fig_bot.update_xaxes(gridcolor='rgba(255,255,255,.05)')
    st.plotly_chart(fig_bot, use_container_width=True)

    st.markdown('<div class="sec">FULL CUSTOMER RANKINGS</div>', unsafe_allow_html=True)
    rank = rew.copy().reset_index(drop=True)
    rank.index += 1
    rank['Profit_Gap'] = rank[pp_col] - rank[p_col]
    cols_r = ['Area','Name', s_col, r_col, b_col, p_col, 'Profit_Gap', rate_col]
    rank = rank[[c for c in cols_r if c in rank.columns]]
    for c in [s_col, r_col, b_col, p_col, 'Profit_Gap']:
        if c in rank.columns:
            rank[c] = rank[c].apply(inr)
    if rate_col in rank.columns:
        rank[rate_col] = rank[rate_col].apply(lambda x: f"{float(x):.1f}%")
    rank.columns = ['Area','Customer','Total Sales','Total Collected','Balance','Profit Earned','Profit Gap','Coll %'][:len(rank.columns)]
    st.dataframe(rank, use_container_width=True, height=420)

# ─────────────────────────────────────────────────────────────
# TAB 8 — LEDGER
# ─────────────────────────────────────────────────────────────

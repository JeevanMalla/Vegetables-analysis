"""Profit tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">PROFIT ANALYSIS</div>', unsafe_allow_html=True)
    realized_pct = a['profit_realized'] / max(a['profit_potential'],1) * 100
    c1,c2,c3,c4 = st.columns(4)
    for col, args in zip([c1,c2,c3,c4],[
        ("green","Profit Potential", inr(a['profit_potential']), f"5% on {inr(a['total_sales'])}"),
        ("green" if realized_pct>70 else "yellow","Realized Profit", inr(a['profit_realized']), f"{realized_pct:.1f}% of potential"),
        ("red","Profit Gap", inr(a['profit_potential']-a['profit_realized']), "From uncollected credit"),
        ("purple","Collection Needed","→ Same-day", "To maximize margin"),
    ]):
        with col: st.markdown(kpi(*args), unsafe_allow_html=True)

    p1,p2 = st.columns(2)
    with p1:
        fig_pp = go.Figure()
        fig_pp.add_trace(go.Bar(name='Potential', x=a['area']['Schedule'],
                                y=a['area']['Profit_Potential'], marker_color='rgba(0,212,170,.3)'))
        fig_pp.add_trace(go.Bar(name='Realized', x=a['area']['Schedule'],
                                y=a['area']['Profit_Realized'], marker_color='#00d4aa'))
        fig_pp.update_layout(**ct(), height=320, title="Potential vs Realized Profit by Area",
                             barmode='overlay', legend=dict(font_size=11))
        fig_pp.update_yaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fig_pp, use_container_width=True)
    with p2:
        fig_pr = px.bar(a['area'].sort_values('Profit_Loss_Pct'),
                        x='Schedule', y='Profit_Loss_Pct', color='Profit_Loss_Pct', text='Profit_Loss_Pct',
                        color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'#6bcb77')],
                        range_color=[0,100], title="Profit Realization % by Area",
                        labels={'Profit_Loss_Pct':'%','Schedule':'Area'})
        fig_pr.update_traces(texttemplate='%{text:.0f}%', textposition='outside')
        fig_pr.update_layout(**ct(), height=320, coloraxis_showscale=False)
        st.plotly_chart(fig_pr, use_container_width=True)

    st.markdown('<div class="sec">CUSTOMER PROFIT TABLE — SORTED BY PROFIT GAP</div>', unsafe_allow_html=True)
    cp = a['customers'][['Schedule','Name','Sales','Receipts','profit_potential','profit_realized','collection_rate']].copy()
    cp['Profit Gap'] = cp['profit_potential'] - cp['profit_realized']
    cp = cp.sort_values('Profit Gap', ascending=False)
    for c in ['Sales','Receipts','profit_potential','profit_realized','Profit Gap']:
        cp[c] = cp[c].apply(inr)
    cp['collection_rate'] = cp['collection_rate'].apply(lambda x: f"{x}%")
    cp.columns = ['Area','Customer','Sales','Collected','Profit Potential','Profit Earned','Coll %','Profit Gap']
    st.dataframe(cp, use_container_width=True, hide_index=True, height=360)

    st.markdown('<div class="sec">HOW TO MAXIMIZE PROFIT</div>', unsafe_allow_html=True)
    area_sorted = a['area'].sort_values('Collection_Eff')
    if len(area_sorted) >= 1:
        worst = area_sorted.iloc[0]
        best  = area_sorted.iloc[-1]
        st.markdown(f"""
| Insight | Action |
|---|---|
| 🔴 **{worst['Schedule']}** collects only {worst['Collection_Eff']:.1f}% | Prioritize evening collection there first |
| 🟢 **{best['Schedule']}** collects {best['Collection_Eff']:.1f}% | Model for other areas — what's working? |
| Every ₹1L collected same-day | Saves you ₹5,000 in risk (your 5% margin secured) |
| Stop supply to Critical debtors | Redirect stock to good-paying customers |
| Enforce daily credit limits | Cap each customer at max 7-day outstanding |
| ₹ per day uncollected = bad debt risk | After 30 days, recovery probability drops sharply |
""")
    else:
        st.info("Upload receipts for this date to see profit insights.")


# ─────────────────────────────────────────────────────────────
# TAB 5 — REWARDS
# ─────────────────────────────────────────────────────────────

"""Bad Debts tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">BAD DEBT IDENTIFICATION & LOSS ANALYSIS</div>', unsafe_allow_html=True)

    rb_all = build_running_balance(get_all_dates())
    if rb_all:
        rc = rb_all['cust_grp']
        s_col = 'Period_Sales'; r_col = 'Period_Receipts'; b_col = 'Running_Balance'; rate_col = 'Collection_Rate'
    else:
        rc = a['customers'].copy()
        rc = rc.rename(columns={'Sales':'Period_Sales','Receipts':'Period_Receipts',
                                 'Balance':'Running_Balance','collection_rate':'Collection_Rate','Schedule':'Area'})
        s_col='Period_Sales'; r_col='Period_Receipts'; b_col='Running_Balance'; rate_col='Collection_Rate'

    def debt_tier(r):
        bal, rate = r[b_col], r[rate_col]
        if bal > 500000 and rate < 20: return "🔴 Critical"
        if bal > 200000 and rate < 30: return "🟠 High Risk"
        if bal > 100000 and rate < 50: return "🟡 Watch"
        if rate == 0 and bal > 50000:  return "🟡 Watch"
        return ""

    rc['Tier'] = rc.apply(debt_tier, axis=1)
    bad = rc[rc['Tier'] != ""].sort_values(b_col, ascending=False)

    crit = bad[bad['Tier']=="🔴 Critical"]
    high = bad[bad['Tier']=="🟠 High Risk"]
    wtch = bad[bad['Tier']=="🟡 Watch"]

    c1,c2,c3 = st.columns(3)
    with c1: st.markdown(kpi("red","Critical Accounts",str(len(crit)),inr(crit[b_col].sum())+" at stake"), unsafe_allow_html=True)
    with c2: st.markdown(kpi("yellow","High Risk",str(len(high)),inr(high[b_col].sum())+" at stake"), unsafe_allow_html=True)
    with c3: st.markdown(kpi("yellow","Watch List",str(len(wtch)),inr(wtch[b_col].sum())+" at stake"), unsafe_allow_html=True)

    if not bad.empty:
        st.markdown('<div class="sec">BAD DEBT MAP</div>', unsafe_allow_html=True)
        fig_bd = px.scatter(bad.reset_index(), x=s_col, y=b_col, size=b_col,
                            color='Tier',
                            color_discrete_map={"🔴 Critical":"#ff6b6b","🟠 High Risk":"#ff9a3c","🟡 Watch":"#ffd93d"},
                            hover_name='Name',
                            title="Bad Debt Map — bubble size = outstanding balance",
                            labels={s_col:'Total Sales (₹)', b_col:'Outstanding (₹)'})
        fig_bd.update_layout(**ct(), height=400)
        fig_bd.update_xaxes(gridcolor='rgba(255,255,255,.05)')
        fig_bd.update_yaxes(gridcolor='rgba(255,255,255,.05)')
        st.plotly_chart(fig_bd, use_container_width=True)

        st.markdown('<div class="sec">ACTION LIST</div>', unsafe_allow_html=True)
        bd_show = bad[['Tier','Area','Name',s_col,r_col,b_col,rate_col]].copy()
        bd_show.columns = ['Risk','Area','Customer','Total Sales','Collected','Outstanding','Coll %']
        for c in ['Total Sales','Collected','Outstanding']:
            bd_show[c] = bd_show[c].apply(inr)
        bd_show['Coll %']  = bd_show['Coll %'].apply(lambda x: f"{float(x):.1f}%")
        bd_show['Action']  = bd_show['Risk'].apply(lambda x:
            "🚨 STOP SUPPLY · Send legal notice" if "Critical" in x else
            ("⛔ Reduce credit · Collect first" if "High" in x else "📞 Call this week"))
        st.dataframe(bd_show, use_container_width=True, hide_index=True)

        total_at_risk = bad[b_col].sum()
        st.error(f"💸 **Estimated Profit at Risk = {inr(total_at_risk * MARGIN_PCT)}** "
                 f"(5% on {inr(total_at_risk)} outstanding in bad/watch accounts)")
    else:
        st.success("✅ No bad debt accounts with current data. Upload more days for better signals.")

    st.markdown('<div class="sec">COLLECTION EFFICIENCY BY AREA (TODAY)</div>', unsafe_allow_html=True)
    ae = a['area'].sort_values('Collection_Eff')
    fig_ae = px.bar(ae, x='Schedule', y='Collection_Eff', color='Collection_Eff', text='Collection_Eff',
                    color_continuous_scale=[(0,'#ff6b6b'),(.5,'#ffd93d'),(1,'#6bcb77')],
                    range_color=[0,100], title="Lower = more money slipping away",
                    labels={'Collection_Eff':'Collection %','Schedule':'Area'})
    fig_ae.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
    fig_ae.update_layout(**ct(), height=300, coloraxis_showscale=False)
    st.plotly_chart(fig_ae, use_container_width=True)

    st.markdown('<div class="sec">ZERO PAYMENT CUSTOMERS TODAY</div>', unsafe_allow_html=True)
    zero_pay = a['customers'][(a['customers']['Receipts']==0) & (a['customers']['Sales']>0)].copy()
    zero_pay = zero_pay[['Schedule','Name','OB','Sales','Balance']].copy()
    zero_pay.columns = ['Area','Customer','Opening Balance','Today Sales','Outstanding']
    for c in ['Opening Balance','Today Sales','Outstanding']:
        zero_pay[c] = zero_pay[c].apply(inr)
    st.dataframe(zero_pay.sort_values('Outstanding', ascending=False), use_container_width=True, hide_index=True)
    st.caption(f"{len(zero_pay)} customers bought today but paid ₹0 this evening. Total sales from them: {inr(a['customers'][(a['customers']['Receipts']==0) & (a['customers']['Sales']>0)]['Sales'].sum())}")


# ─────────────────────────────────────────────────────────────
# TAB 4 — PROFIT ANALYSIS
# ─────────────────────────────────────────────────────────────

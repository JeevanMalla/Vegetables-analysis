"""Global CSS and small display helpers."""
import streamlit as st


def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');
    html,body,[class*="css"]{ font-family:'DM Sans',sans-serif; }
    .kpi{background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);border-radius:14px;padding:18px 20px;margin:4px 0;border-left:4px solid #00d4aa;color:white;}
    .kpi.red{border-left-color:#ff6b6b;}.kpi.yellow{border-left-color:#ffd93d;}.kpi.green{border-left-color:#6bcb77;}.kpi.purple{border-left-color:#c084fc;}
    .kpi .lbl{font-size:10px;text-transform:uppercase;letter-spacing:1.8px;opacity:.65;}
    .kpi .val{font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;margin-top:3px;}
    .kpi .sub{font-size:11px;opacity:.55;margin-top:2px;}
    .sec{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:2.5px;color:#00d4aa;margin:24px 0 10px;padding-bottom:5px;border-bottom:1px solid rgba(0,212,170,.18);}
    .reward-card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid gold;border-radius:12px;padding:16px 20px;text-align:center;color:white;}
    .reward-card .rank{font-size:32px;}.reward-card .name{font-size:15px;font-weight:700;margin:6px 0 2px;}
    .reward-card .amt{font-family:'JetBrains Mono',monospace;font-size:20px;color:gold;}
    div[data-testid="stMetric"]{background:#0f172a;border-radius:8px;padding:12px 16px;}
    div[data-testid="stMetricValue"]{color:white;}
    </style>
    """, unsafe_allow_html=True)


def inr(n):
    try: return f"₹{float(n):,.0f}"
    except: return "₹0"

def ct():
    return dict(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(15,32,39,.85)',
                font_color='#e2e8f0', margin=dict(l=4,r=4,t=40,b=4))

def kpi(cls, lbl, val, sub):
    return f'<div class="kpi {cls}"><div class="lbl">{lbl}</div><div class="val">{val}</div><div class="sub">{sub}</div></div>'

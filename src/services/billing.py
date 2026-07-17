"""80mm thermal bill and quick-summary PDF generation (fpdf2 + Telugu shaping)."""
import os
from datetime import datetime, timedelta

import pandas as pd

from ..config import EXCLUDE_AREAS, EXCLUDE_CUSTOMERS, TELUGU_FONT_PATH
from . import database as dbs
from .storage import load_data, get_all_dates
from .analytics import get_running_balances_bulk

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except Exception:
    FPDF_AVAILABLE = False

def _amt(n):
    try:
        return f"{float(n):,.0f}"
    except Exception:
        return "0"

_LATIN_MAP = str.maketrans({'—': '-', '–': '-', '→': '>', '₹': 'Rs', '‘': "'", '’': "'",
                            '“': '"', '”': '"', '…': '...'})

def get_veg_telugu_map():
    """{english_name: telugu_name} from dbs.db.vegetables (empty strings dropped)."""
    if not dbs.MONGO_AVAILABLE:
        return {}
    return {d["name"]: d["telugu_name"] for d in
            dbs.db.vegetables.find({"telugu_name": {"$exists": True, "$ne": ""}},
                               {"_id": 0, "name": 1, "telugu_name": 1})}

def _latin(t):
    """Core PDF fonts are latin-1 only — translate common unicode punctuation, replace the rest."""
    return str(t).translate(_LATIN_MAP).encode('latin-1', 'replace').decode('latin-1')

def build_bills_pdf(date_str, area=None, customer=None):
    """
    One 80mm-wide bill page per customer who has sales on date_str.
    Returns (pdf_bytes, n_bills) or (None, 0).
    """
    if not FPDF_AVAILABLE:
        return None, 0
    sdf, rdf = load_data(date_str)
    if sdf is None or sdf.empty:
        return None, 0
    sdf = sdf[~sdf['Name'].isin(EXCLUDE_CUSTOMERS)].copy()
    for c in ['Bags','Kgs','Rate','Amount']:
        sdf[c] = pd.to_numeric(sdf[c], errors='coerce').fillna(0)

    # Area per customer: today's receipts file first, master list as fallback
    area_map = {}
    if dbs.MONGO_AVAILABLE:
        for doc in dbs.db.customers.find({}, {"_id": 0, "name": 1, "area": 1}):
            area_map[doc.get("name")] = doc.get("area", "")
    if rdf is not None and not rdf.empty:
        area_map.update(dict(zip(rdf['Name'], rdf['Schedule'])))

    # Running balance track (prev running bal): initial + Σ(sales − receipts) up to yesterday
    prev_cal = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    rb_prev = get_running_balances_bulk(prev_cal)
    run_prev_map = dict(zip(rb_prev['Name'], rb_prev['running_balance'])) if not rb_prev.empty else {}

    # Opening balance = today's Excel OB column (ledger figure, kept separate from running balance)
    ob_map = {}
    if rdf is not None and not rdf.empty and 'OB' in rdf.columns:
        ob_map = dict(zip(rdf['Name'], pd.to_numeric(rdf['OB'], errors='coerce').fillna(0)))

    # Previous data date: cash received + closing Balance (OB fallback when today's
    # receipts file isn't uploaded yet, e.g. printing bills in the morning)
    prev_cash_map, prev_close_map = {}, {}
    prior_dates = [d for d in get_all_dates() if d < date_str]
    if prior_dates:
        _, prev_rdf = load_data(max(prior_dates))
        if prev_rdf is not None and not prev_rdf.empty:
            prev_cash_map = dict(zip(prev_rdf['Name'],
                                     pd.to_numeric(prev_rdf['Receipts'], errors='coerce').fillna(0)))
            if 'Balance' in prev_rdf.columns:
                prev_close_map = dict(zip(prev_rdf['Name'],
                                          pd.to_numeric(prev_rdf['Balance'], errors='coerce').fillna(0)))

    custs = sorted(sdf['Name'].unique(), key=lambda n: (str(area_map.get(n, "")), str(n)))
    if customer:
        custs = [c for c in custs if c == customer]
    elif area:
        custs = [c for c in custs if area_map.get(c, "") == area]
    if not custs:
        return None, 0

    disp_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    pdf = FPDF(unit="mm", format=(80, 200))
    pdf.set_auto_page_break(False)
    pdf.set_margins(4, 4, 4)
    LH  = 4.0                      # line height (mm) — sized for readable thermal print
    SEP = "-" * 42

    # Telugu item names: needs the Noto font + uharfbuzz text shaping
    telugu_map = get_veg_telugu_map()
    telugu_ok = False
    if telugu_map and os.path.exists(TELUGU_FONT_PATH):
        try:
            pdf.add_font("NotoTelugu", "", TELUGU_FONT_PATH)
            pdf.set_text_shaping(True)
            telugu_ok = True
        except Exception:
            telugu_ok = False
    ITEM_W = 33                    # mm for the item-name cell; numbers take the rest

    def line(txt, bold=False, size=9, align='L'):
        pdf.set_font("Courier", "B" if bold else "", size)
        pdf.cell(0, LH, _latin(txt), align=align, new_x="LMARGIN", new_y="NEXT")

    def money_line(label, value, bold=False):
        line(f"{label:<19}: {_amt(value):>16}", bold=bold)   # 37 chars ≈ 70.5mm at 9pt

    for name in custs:
        rows = sdf[sdf['Name'] == name]
        opening     = float(ob_map.get(name, prev_close_map.get(name, 0)))
        run_prev    = float(run_prev_map.get(name, 0))
        prev_cash   = float(prev_cash_map.get(name, 0))
        today_sales = float(rows['Amount'].sum())
        # Bill is handed over in the evening BEFORE cash is collected — no receipts deducted
        closing     = opening + today_sales
        running     = run_prev + today_sales
        cust_area   = str(area_map.get(name, "") or "")

        n_lines = 3 + 1 + 2 + 1 + 1 + len(rows) + 1 + 3 + 1 + 2   # header→footer
        page_h  = 8 + n_lines * LH + 8
        pdf.add_page(format=(80, max(page_h, 60)))

        line("SVC VEGETABLES", bold=True, size=11, align='C')
        line(str(name)[:30], bold=True, size=12, align='C')
        line(f"{cust_area[:22]}  {disp_date}".strip(), size=9, align='C')
        line(SEP, size=8)
        money_line("PREV DAY CASH PAID", prev_cash)
        money_line("OPENING BALANCE", opening, bold=True)
        line(SEP, size=8)
        # Header + item rows as two cells (item name | numbers) so columns stay
        # aligned even when the item cell switches to the Telugu font
        pdf.set_font("Courier", "B", 8)
        pdf.cell(ITEM_W, LH, "ITEM", align='L')
        pdf.cell(0, LH, f"{'BAG':>3}{'KGS':>6}{'RATE':>5}{'AMOUNT':>9}",
                 align='R', new_x="LMARGIN", new_y="NEXT")
        for _, r in rows.iterrows():
            b = float(r['Bags']); k = float(r['Kgs'])
            bags_s = f"{int(b)}" if b > 0 else "-"
            kgs_s  = f"{k:,.1f}" if k > 0 else "-"
            item_en = str(r['Item'])
            nums = f"{bags_s:>3}{kgs_s:>6}{_amt(r['Rate']):>5}{_amt(r['Amount']):>9}"
            tel = str(telugu_map.get(item_en, "") or "")
            if telugu_ok and tel:
                # Core fonts can't hold Telugu glyphs — compose the cell from
                # a Courier part (English + parens) and a Noto Telugu part
                en_part = f"{item_en[:10]}("
                pdf.set_font("Courier", "", 8)
                w_latin = pdf.get_string_width(en_part) + pdf.get_string_width(")")
                pdf.set_font("NotoTelugu", "", 8)
                while tel and w_latin + pdf.get_string_width(tel) > ITEM_W - 1:
                    tel = tel[:-1]
            if telugu_ok and tel:
                x0 = pdf.get_x()
                pdf.set_font("Courier", "", 8)
                pdf.cell(pdf.get_string_width(en_part) + 0.3, LH, _latin(en_part))
                pdf.set_font("NotoTelugu", "", 8)
                pdf.cell(pdf.get_string_width(tel) + 0.3, LH, tel)
                pdf.set_font("Courier", "", 8)
                pdf.cell(2, LH, ")")
                pdf.set_x(x0 + ITEM_W)
            else:
                pdf.set_font("Courier", "", 8)
                pdf.cell(ITEM_W, LH, _latin(item_en[:18]), align='L')
            pdf.set_font("Courier", "", 8)
            pdf.cell(0, LH, nums, align='R', new_x="LMARGIN", new_y="NEXT")
        line(SEP, size=8)
        money_line("TODAY SALES TOTAL", today_sales)
        money_line("CLOSING BALANCE", closing, bold=True)
        money_line("RUNNING BALANCE", running, bold=True)
        line(SEP, size=8)
        line("* Rate mostly per 10 kg", size=8)
        line("Thank you!", size=9, align='C')

    return bytes(pdf.output()), len(custs)


def build_summary_pdf(df, title_lines, fmt="a4"):
    """
    Quick-summary table PDF. df columns:
    [Area, Name, Period_Sales, Running_Balance, Day_Sales, Day_Receipts, Overall_Balance]
    fmt = "a4" (bordered table, repeats header per page) or "thermal" (80mm strip, one cut at end).
    """
    if not FPDF_AVAILABLE or df is None or df.empty:
        return None
    num_cols = ['Period_Sales', 'Running_Balance', 'Day_Sales', 'Day_Receipts', 'Overall_Balance']
    totals = {k: float(df[k].sum()) for k in num_cols}

    if fmt == "thermal":
        # Pages capped at 250mm — many thermal drivers reject longer pages,
        # and the auto-cutter separates pages anyway.
        LH = 3.4
        PAGE_H = 250
        MAX_Y = PAGE_H - 8

        def _camt(v):
            """Compact: 4,50,000 → '4.5L' so 7-char columns stay readable at 7pt."""
            v = float(v)
            return f"{v/100000:.1f}L" if abs(v) >= 100000 else f"{v:,.0f}"

        pdf = FPDF(unit="mm", format=(80, PAGE_H))
        pdf.set_auto_page_break(False)
        pdf.set_margins(3, 4, 3)
        sep = "-" * 48

        def tline(t, bold=False, size=7, align='L'):
            pdf.set_font("Courier", "B" if bold else "", size)
            pdf.cell(0, LH, _latin(t), align=align, new_x="LMARGIN", new_y="NEXT")

        def col_header():
            tline(sep)
            tline(f"{'NAME':<10} {'P.SALE':>7} {'R.BAL':>7} {'D.SAL':>6} {'RCPT':>6} {'BAL':>7}",
                  bold=True)

        pdf.add_page()
        for i, tl in enumerate(title_lines):
            tline(tl, bold=(i == 0), size=9 if i == 0 else 7, align='C')
        col_header()
        for _, r in df.iterrows():
            if pdf.get_y() + LH > MAX_Y:
                pdf.add_page()
                col_header()
            tline(f"{str(r['Name'])[:10]:<10} {_camt(r['Period_Sales']):>7} "
                  f"{_camt(r['Running_Balance']):>7} {_camt(r['Day_Sales']):>6} "
                  f"{_camt(r['Day_Receipts']):>6} {_camt(r['Overall_Balance']):>7}")
        if pdf.get_y() + 7 * LH > MAX_Y:
            pdf.add_page()
        tline(sep)
        tline(f"TOTALS ({len(df)} customers)", bold=True, size=8)
        for lbl, key in [("PERIOD SALES", 'Period_Sales'), ("RUNNING BALANCE", 'Running_Balance'),
                         ("DAY SALES", 'Day_Sales'), ("DAY RECEIPTS", 'Day_Receipts'),
                         ("OVERALL BALANCE", 'Overall_Balance')]:
            tline(f"{lbl:<16}: {_amt(totals[key]):>15}", bold=True, size=8)
        tline(sep)
        return bytes(pdf.output())

    # A4
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(8, 10, 8)
    pdf.add_page()
    for i, tl in enumerate(title_lines):
        pdf.set_font("Courier", "B" if i == 0 else "", 13 if i == 0 else 9)
        pdf.cell(0, 5.5, _latin(tl), align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    widths  = [26, 48, 24, 24, 24, 24, 24]
    headers = ["AREA", "CUSTOMER", "PERIOD SALE", "RUN. BAL", "DAY SALE", "RECEIPTS", "BALANCE"]
    aligns  = ['L', 'L', 'R', 'R', 'R', 'R', 'R']

    def header_row():
        pdf.set_font("Courier", "B", 7.5)
        pdf.set_fill_color(230, 230, 230)
        for w, hh in zip(widths, headers):
            pdf.cell(w, 5.5, hh, border=1, align='C', fill=True)
        pdf.ln()

    header_row()
    pdf.set_font("Courier", "", 7.5)
    for _, r in df.iterrows():
        if pdf.get_y() > 277:
            pdf.add_page()
            header_row()
            pdf.set_font("Courier", "", 7.5)
        vals = [str(r['Area'])[:15], str(r['Name'])[:27],
                _amt(r['Period_Sales']), _amt(r['Running_Balance']),
                _amt(r['Day_Sales']), _amt(r['Day_Receipts']), _amt(r['Overall_Balance'])]
        for w, v, al in zip(widths, vals, aligns):
            pdf.cell(w, 5, _latin(v), border=1, align=al)
        pdf.ln()
    if pdf.get_y() > 277:
        pdf.add_page()
        header_row()
    pdf.set_font("Courier", "B", 7.5)
    tvals = ["", "TOTAL", _amt(totals['Period_Sales']), _amt(totals['Running_Balance']),
             _amt(totals['Day_Sales']), _amt(totals['Day_Receipts']), _amt(totals['Overall_Balance'])]
    for w, v, al in zip(widths, tvals, aligns):
        pdf.cell(w, 5.5, v, border=1, align=al)
    pdf.ln()
    return bytes(pdf.output())

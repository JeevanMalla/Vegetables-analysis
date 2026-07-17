# SVC Vegetables — Business Intelligence Dashboard
### Project Summary

---

## 🧭 What This Is

A daily business operations dashboard built for a **vegetable wholesale business in Visakhapatnam**.  
Morning: goods are dispatched on credit. Evening: cash is collected from customers.  
This app tracks the full cycle — what went out, what came back, and what is stuck.

---

## 🏗️ Tech Stack

| Layer | Technology |
|---|---|
| Dashboard | Python · Streamlit |
| Charts | Plotly Express + Plotly Graph Objects |
| Data Input | Microsoft Excel (.xlsx) — 2 files per day |
| Database | MongoDB Atlas (cloud) with TLS |
| Fallback | In-session storage if MongoDB is offline |
| Fonts | DM Sans · JetBrains Mono (Google Fonts) |

---

## 📂 MongoDB Collections

Four dedicated collections store every piece of business data:

| Collection | What It Stores |
|---|---|
| `sales_list` | Every sale line item per day (item, customer, bags, kgs, rate, amount) |
| `receipt_list` | Every customer's daily receipt record (OB, sales, receipts, closing balance) |
| `customer_list` | Master customer directory — upserted on every upload, never duplicated |
| `area_list` | Master area directory — the 6 active business routes |

**Date-based upsert** — uploading the same date twice overwrites, never duplicates.

---

## 📥 Daily Input Files

Two Excel files are uploaded each day:

### 1. Sales File — `DAY_XX.xlsx`
Records every item sold that morning.

| Column | Description |
|---|---|
| Customer Name | Buyer |
| Item Name | Vegetable (TMC, C.T, Mulaga, Cabbage…) |
| Bags / Kgs | Quantity |
| Rate | Price per unit |
| Amount | Total sale value |
| Cooly | Labour cost |

### 2. Receipts File — `29th_exel_sheet.xlsx`
Customer-wise ledger from the evening collection round.

| Column | Description |
|---|---|
| Area (Schedule) | Route / delivery zone |
| Customer Name | Buyer |
| Opening Balance (OB) | Amount owed at start of day |
| Receipts | Cash collected this evening |
| Sales | Credit given today |
| Closing Balance | OB + Sales − Receipts = still owed |

---

## 🗺️ Business Areas Tracked

Six active delivery routes are analysed:

1. MARKET INDIA BATCH
2. R&B
3. RING ROAD + BD + MRH
4. OUTER
5. HOTELS
6. BANDOLU

> **Excluded from all analysis:** KANCHILI · SENDER · SVC STAFF  
> (internal accounts — not customer credit)

---

## 📊 Dashboard Tabs

### Tab 1 — 📊 Today
Single-day view of business health.

- **5 KPI cards** — Sales, Gross Profit, Cash Collected, Total Outstanding, Profit at Risk
- **Area Summary table** — customers, sales, collected, outstanding, collection % per area
- **Top 20 stuck customers** — horizontal bar chart
- **Outstanding by Area** — donut chart + collection efficiency bar
- **Customer Health table** — filterable by payment status (No Payment / Partial / Good / Cleared)
- **Sales breakdown** — by item and by customer (top 15)
- **Raw transactions** — expandable full sales log

---

### Tab 2 — 📈 Running Balance
Multi-day analysis across a chosen date range.

**Formula:**
```
Running Balance = Opening Balance (first day) + Σ Sales − Σ Receipts
```

- **Date range filter** (From → To)
- **Area filter** (select one or more routes)
- **Period KPIs** — Total Sales, Collected, Running Balance, Net Credit, Bad Debt count
- **Area-wise running balance** — bar chart coloured by collection rate
- **Sales vs Collected** — overlay bar by area
- **Day-by-day trend** — line chart of balance + daily collections bar
- **Customer-wise drill-down** — select an area, see every customer's running balance
- **Top 15 balance accumulators** — who is piling up the most debt

---

### Tab 3 — ⚠️ Bad Debts
Identifies customers who are becoming a financial risk.

**3-tier risk classification:**

| Tier | Criteria | Action |
|---|---|---|
| 🔴 Critical | Balance > ₹5L AND collection < 20% | Stop supply · Legal notice |
| 🟠 High Risk | Balance > ₹2L AND collection < 30% | Freeze credit · Collect first |
| 🟡 Watch | Balance > ₹1L AND collection < 50% | Call today · Get commitment |

- **Bad Debt Map** — scatter/bubble chart (bubble size = balance)
- **Action List table** — one row per risky customer with recommended action
- **Profit at risk** — total outstanding × 5% = margin you may never see
- **Zero payment today** — customers who bought but paid ₹0 this evening
- **Collection efficiency bar** by area

---

### Tab 4 — 💰 Profit Analysis
Tracks where your 5% margin is being realized vs lost.

- **Potential vs Realized profit** — area-wise overlay bar
- **Profit realization %** — area-wise colour-coded bar
- **Customer profit gap table** — sorted by largest uncollected margin
- **8-point action plan** — specific steps to maximize daily profit

**Key insight:** Your margin is 5% of sales. Every rupee not collected same-day is profit deferred — and potentially lost forever if the customer becomes a bad debt.

---

### Tab 5 — 🏆 Rewards & Rankings
Identifies your best and worst customer relationships.

- **🥇 🥈 🥉 Medal cards** — top 3 customers by profit contributed
- **Top 20 most profitable** — bar chart coloured by collection rate
- **Bottom 10 loss makers** — customers with largest profit gap
- **Area performance** — which route generates the most realized profit
- **Full customer ranking table** — all customers sorted by profit earned

---

## 💡 Key Business Metrics

| Metric | Formula |
|---|---|
| Gross Profit Potential | Total Sales × 5% |
| Profit Realized | min(Receipts, Sales) × 5% |
| Profit Gap | Potential − Realized |
| Running Balance | OB + Σ Sales − Σ Receipts |
| Collection Rate | Receipts ÷ Sales × 100 |
| Net Credit Extended | Total Sales − Total Receipts |

---

## 🚀 How to Run

```bash
# 1. Install dependencies
pip install streamlit pandas openpyxl plotly pymongo

# 2. Set MongoDB connection string
export MONGO_URI="mongodb+srv://user:password@cluster.mongodb.net/"

# 3. Launch
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

---

## 📋 Daily Workflow

```
Morning → Goods dispatched on credit
         ↓
         Upload DAY_XX.xlsx (sales file)

Evening → Cash collected from customers
         ↓
         Upload receipts file
         ↓
         Select date → Click "Save & Analyze"
         ↓
         Dashboard updates all 5 tabs
         ↓
         Check Bad Debts tab → make collection calls
         ↓
         Next morning repeat
```

---

## ⚙️ Business Rules

- **Margin:** 5% on all sales
- **Excluded areas:** Kanchili, Sender, SVC Staff (internal — not customer credit)
- **Bad debt threshold:** Balance > ₹2 Lakh with < 30% collection rate
- **Date upsert:** Uploading the same date overwrites previous data
- **MongoDB fallback:** If Atlas is unreachable, data is stored in browser session

---

## 📁 File Structure (v3 — modular)

```
svc_veggies/
├── app.py                     ← Thin Streamlit entry point (auth, wiring)
├── src/
│   ├── config.py              ← Business constants (margin, excluded areas/customers)
│   ├── services/
│   │   ├── database.py        ← MongoDB connection + business settings
│   │   ├── parsing.py         ← Excel parsing & uploaded-file type detection
│   │   ├── storage.py         ← Save/load per-date data (Mongo + session cache)
│   │   ├── analytics.py       ← Running balances, day analysis, period aggregations
│   │   ├── billing.py         ← 80mm thermal bill & summary PDFs (Telugu support)
│   │   └── printing.py        ← Direct ESC/POS (USB/LAN) + shop print-job queue
│   └── ui/
│       ├── theme.py           ← CSS + KPI/chart helpers
│       ├── auth.py            ← Password gate
│       ├── sidebar.py         ← Uploads, settings, history
│       ├── common.py          ← Shared import surface for UI modules
│       └── tabs/              ← One module per dashboard tab
├── agent/
│   ├── print_agent.py         ← Shop-PC print agent (built to .exe by CI)
│   └── requirements_agent.txt
├── fonts/                     ← Noto Sans Telugu (bill printing)
├── .github/workflows/         ← Builds SVCPrintAgent 64-bit & 32-bit EXEs
└── requirements.txt
```

---

*Built for SVC Vegetables · Visakhapatnam · Version 2.0*

"""Excel parsing and uploaded-file type detection."""
import re

import pandas as pd

from ..config import EXCLUDE_AREAS, EXCLUDE_CUSTOMERS

def _clean_sales_df(df):
    """Shared cleaning logic for both single-day and multi-day sales DataFrames."""
    df.columns = ['idx','Date','Name','Sno','Item','Bags','Kgs','Rate','Amount','Cooly']
    df['Date'] = df['Date'].ffill()
    df = df[df['Name'].notna() & (df['Name'].astype(str).str.strip() != '')]
    df = df[df['Name'].astype(str).str.strip() != 'Name']
    df = df[df['Sno'].notna()]  # subtotal rows have no Sno
    df['Name'] = df['Name'].astype(str).str.strip()
    df['Item'] = df['Item'].astype(str).str.strip()
    # Drop excluded customers from sales too
    df = df[~df['Name'].isin(EXCLUDE_CUSTOMERS)]
    for c in ['Bags','Kgs','Rate','Amount','Cooly']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df[['Date','Name','Item','Bags','Kgs','Rate','Amount','Cooly']]

def _clean_receipts_df(df):
    """Shared cleaning logic for both single-day and multi-day receipts DataFrames."""
    df.columns = ['idx','Schedule','Name','OB','Receipts','Balance','Sales','Total']
    df['Schedule'] = df['Schedule'].ffill()
    df = df[df['Name'].notna() & (df['Name'].astype(str).str.strip() != '')]
    df = df[df['Name'].astype(str).str.strip() != 'Name']
    df = df[df['Schedule'].astype(str).str.strip() != 'Total']
    df['Name']     = df['Name'].astype(str).str.strip()
    df['Schedule'] = df['Schedule'].astype(str).str.strip()
    # Drop excluded areas and excluded individual customers entirely at parse time
    df = df[~df['Schedule'].isin(EXCLUDE_AREAS)]
    df = df[~df['Name'].isin(EXCLUDE_CUSTOMERS)]
    for c in ['OB','Receipts','Balance','Sales','Total']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    df['is_internal'] = False  # everything remaining is external/valid
    return df[['Schedule','Name','OB','Receipts','Balance','Sales','Total','is_internal']]

def parse_sales(file):
    """Single-day or multi-day sales file — same format, header row 3 (0-indexed)."""
    df = pd.read_excel(file, header=3)
    return _clean_sales_df(df)

def parse_receipts(file):
    """Single-day or period receipts file — header row 3 (0-indexed)."""
    df = pd.read_excel(file, header=3)
    return _clean_receipts_df(df)

def parse_bulk_sales(file):
    """
    Multi-day sales file: returns dict of {date_str -> DataFrame}.
    Date column has real dates only on first row of each date group; rest are NaN (ffill).
    """
    df = pd.read_excel(file, header=3)
    df = _clean_sales_df(df)
    df['_date_raw'] = df['Date'].astype(str).str.strip()
    by_date = {}
    for raw_d, grp in df.groupby('_date_raw'):
        try:
            # Parse formats like '06-05-26' or '2026-05-06'
            parsed = pd.to_datetime(raw_d, dayfirst=True)
            date_key = parsed.strftime('%Y-%m-%d')
        except Exception:
            continue
        day_df = grp.drop(columns=['_date_raw']).reset_index(drop=True)
        by_date[date_key] = day_df
    return by_date

def parse_bulk_receipts(file):
    """
    Period receipts file: single aggregated summary for the whole period.
    Returns the cleaned DataFrame (no date column).
    """
    df = pd.read_excel(file, header=3)
    return _clean_receipts_df(df)


def detect_file_meta(file):
    """
    Read the title rows of an exported xlsx to find its type and date range.
    Titles look like: 'Customer Status for 18-05-26 to 18-05-26'
                      'Sales List for 30-04-26 to 30-04-26'
    Returns (kind, from_date, to_date) with dates as 'YYYY-MM-DD',
    kind in {'receipts', 'sales', None}.
    """
    try:
        head = pd.read_excel(file, header=None, nrows=3)
        title = " ".join(str(x) for x in head.values.ravel() if pd.notna(x))
    except Exception:
        return None, None, None
    m = re.search(r"(Customer Status|Sales List)\s*for\s*"
                  r"(\d{1,2}-\d{1,2}-\d{2,4})\s*to\s*(\d{1,2}-\d{1,2}-\d{2,4})",
                  title, re.I)
    if not m:
        return None, None, None
    kind = 'receipts' if 'customer' in m.group(1).lower() else 'sales'
    try:
        d_from = pd.to_datetime(m.group(2), dayfirst=True).strftime("%Y-%m-%d")
        d_to   = pd.to_datetime(m.group(3), dayfirst=True).strftime("%Y-%m-%d")
        return kind, d_from, d_to
    except Exception:
        return kind, None, None

"""Shared import surface for UI modules — one place that wires services to tabs."""
import os
import re
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime, timedelta

from ..config import (MARGIN_PCT, EXCLUDE_AREAS, EXCLUDE_CUSTOMERS,
                      DEFAULT_MONTHLY_EXPENSE, TELUGU_FONT_PATH)
from ..services import database as dbs
from ..services.database import (get_monthly_expense, set_monthly_expense,
                                 get_printer_ip, set_printer_ip,
                                 get_printer_usb, set_printer_usb)
from ..services.parsing import (parse_sales, parse_receipts, parse_bulk_sales,
                                parse_bulk_receipts, detect_file_meta)
from ..services.storage import save_data, load_data, get_all_dates, init_session_store
from ..services.analytics import (get_customer_running_balance, get_running_balances_bulk,
                                  build_outstanding_series, analyze_day,
                                  build_running_balance, build_veg_analytics)
from ..services.billing import (FPDF_AVAILABLE, build_bills_pdf, build_summary_pdf,
                                get_veg_telugu_map, _amt, _latin)
from ..services.printing import (ESCPOS_AVAILABLE, detect_usb_printers,
                                 pdf_to_thermal_images, print_images_escpos,
                                 print_images_escpos_usb, queue_print_job)
from .theme import inr, ct, kpi

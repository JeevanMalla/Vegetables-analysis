"""Business constants and shared paths."""
import os

MARGIN_PCT    = 0.05
# Areas whose data is never shown in any dashboard
# CHITS / EXPENSES / PATTY hold internal ledger entries (COOLY, STAFF EXPENSE,
# SWAMY CHIT, …) — not customer credit
EXCLUDE_AREAS = {"KANCHILI", "SENDER", "SVC STAFF", "HOTELS",
                 "CHITS", "EXPENSES", "PATTY"}
# Individual customers excluded regardless of which area they appear under
EXCLUDE_CUSTOMERS = {"PTC", "SVC", "SVC BABU", "SVC BHASKAR", "SVC PARMESH",
                     "SVC PER", "SVC RAJU", "SVC SANTOSH", "SVC SUDHA",
                     "AUROBINDO", "JEEVAN", "PMAS", "DAMAGE",
                     "BANK OF BARODA", "IDBI 5135", "SBI FORT BRANCH"}

DEFAULT_MONTHLY_EXPENSE = 300000

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TELUGU_FONT_PATH = os.path.join(_ROOT, "fonts", "NotoSansTelugu-Regular.ttf")

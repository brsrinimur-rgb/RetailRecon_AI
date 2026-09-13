"""
REGRESSION_V61_MISSING_D365_FOLLOWUP_MULTISHEET_FIX.py

Context: this uploaded file ("MULTI_SHEET_FIX") adds a genuinely useful
new capability on top of V60 -- raw POS provider workbooks (e.g.
UNITED_LUXURY exports) are often multi-sheet (typically Details_mada and
Details_CC), and the previous _read_raw_provider() only ever read the
workbook's first/default sheet, silently missing Card Number / Transaction
Time whenever the real transaction rows lived on a later sheet. This
rewrite scans every sheet, detects each sheet's own transaction header,
skips cover/summary sheets, and combines every usable sheet before
matching. Verified working against a synthetic 3-sheet workbook (cover +
Details_mada + Details_CC): both data sheets are found and both queue rows
get enriched correctly.

But this same upload also REGRESSED a bug that V60 had already fixed:
Terminal ID was built with plain `.fillna("").astype(str).str.strip()`
again instead of `.map(_clean_code)`, so it went back to showing the
spurious ".0" suffix ("55610703.0" instead of "55610703") -- reproduced
against the real uploaded reconciliation report (Reconciliation_latest.xlsx).
Same bug, third occurrence for this exact field. Fixed by routing it
through _clean_code() again, the same way Store Code already is.

This test covers: the Terminal ID cleanup (regression re-fix), the date
fix and Store Code cleanup (carried over correctly from V60, re-checked
here so they can't silently regress again either), and the new
multi-sheet raw-provider-file reading/enrichment feature.

Uses a synthetic report built in RetailRecon's real export shape (title
row, "Generated..." row, blank row, header row -- matching
report_export.py's own startrow=3 convention) so it doesn't depend on any
uploaded file being present in this environment.
"""
import io
import re
import csv
from pathlib import Path
from typing import Optional
import pandas as pd

src = open("20_Missing_D365_Follow_Up.py").read()
start = src.index("MASTER_PATH = Path(")
cut = src.index('st.title("📨 Missing D365 Follow-Up")')
ns = {"re": re, "io": io, "csv": csv, "Path": Path, "pd": pd, "Optional": Optional}
exec(compile(src[start:cut], "page20_v61_logic", "exec"), ns)

_load_missing_d365_from_report = ns["_load_missing_d365_from_report"]
_build_email = ns["_build_email"]
_clean_code = ns["_clean_code"]
_report_date = ns["_report_date"]
_read_raw_provider = ns["_read_raw_provider"]
_enrich_card_and_time = ns["_enrich_card_and_time"]


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")


def _make_report_bytes(exceptions_df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        exceptions_df.to_excel(w, sheet_name="Exceptions", index=False, startrow=3)
        ws = w.sheets["Exceptions"]
        ws["A1"] = "Exceptions"
        ws["A2"] = f"Generated 13-Sep-2026 20:23 | {len(exceptions_df)} exception row(s)"
    buf.seek(0)
    buf.name = "report.xlsx"
    return buf


# --- 1. date fix + Store Code + Terminal ID cleanup (must not regress again) ---
exceptions = pd.DataFrame([
    {"Store Code": 615, "Auth Code": "016934", "POS Tender": "MADA", "POS Total": 12665.00,
     "Terminal ID": 55610703, "POS Date": 46266.0, "Status": "Missing D365"},
    {"Store Code": 601, "Auth Code": "999999", "POS Tender": "VISA", "POS Total": 500.00,
     "Terminal ID": 55610700, "POS Date": 46267.0, "Status": "Missing POS"},  # must be excluded
])
report = _make_report_bytes(exceptions)
q = _load_missing_d365_from_report(report)

_assert(len(q) == 1, f"only the 1 real 'Missing D365' row survives, got {len(q)}")
_assert(q["Store Code"].iloc[0] == "615", "Store Code correctly cleaned (no spurious .0)")
_assert(q["Terminal ID"].iloc[0] == "55610703",
        f"Terminal ID correctly cleaned (no spurious .0 -- this upload had regressed it a THIRD time; "
        f"reproduced live against Reconciliation_latest.xlsx before this fix), got {q['Terminal ID'].iloc[0]!r}")

dt = q["Transaction Date"].iloc[0]
_assert(pd.Timestamp(dt).year == 2026, f"Transaction Date resolves to 2026, not a 1970 artifact, got {dt}")
_assert(pd.Timestamp(dt).date() == pd.Timestamp("2026-09-01").date(), f"Excel serial 46266 -> 2026-09-01, got {dt}")

subject, body = _build_email(q)
_assert("1970" not in body, "the generated email body contains no 1970 garbage date")
_assert("01-Sep-2026" in body, "the generated email body shows the real date")

# --- 2. _report_date unit behavior -----------------------------------------
_assert(_report_date(None) is None, "_report_date(None) is None, not a crash")
_assert(_report_date("") is None, "_report_date('') is None")
_assert(pd.Timestamp(_report_date(46269.0)).date() == pd.Timestamp("2026-09-04").date(),
        "_report_date correctly converts another serial (46269 -> 2026-09-04)")

# --- 3. NEW: multi-sheet raw provider file reading -------------------------
multi_buf = io.BytesIO()
with pd.ExcelWriter(multi_buf, engine="openpyxl") as w:
    pd.DataFrame([{"Summary": "Cover page, no transaction data here"}]).to_excel(
        w, sheet_name="Cover", index=False
    )
    pd.DataFrame([
        {"Auth Code": "16934", "Transaction Amount": 12665.00, "Card Number": "428671XXXXXX1060",
         "Transaction Time": "15:22:23", "Terminal ID": "55610703"},
    ]).to_excel(w, sheet_name="Details_mada", index=False)
    pd.DataFrame([
        {"Auth Code": "012140", "Transaction Amount": 999.99, "Card Number": "555555XXXXXX9999",
         "Transaction Time": "09:10:00", "Terminal ID": "55610714"},
    ]).to_excel(w, sheet_name="Details_CC", index=False)
multi_buf.seek(0)
multi_buf.name = "provider_multisheet.xlsx"

combined = _read_raw_provider(multi_buf)
_assert(not combined.empty, "multi-sheet provider file produces a non-empty combined frame")
_assert(set(combined["_RAW_SHEET"].unique()) == {"Details_mada", "Details_CC"},
        f"both real transaction sheets are read and the Cover sheet is skipped, got {sorted(combined['_RAW_SHEET'].unique())}")
_assert(len(combined) == 2, f"exactly 2 transaction rows combined across both sheets, got {len(combined)}")

# --- 4. NEW: enrichment finds matches on EITHER sheet of the same file -----
two_row_queue = pd.DataFrame([
    {"Store Code": "615", "Authorization Code": "016934", "Value of Sales": 12665.00,
     "Terminal ID": "55610703", "Source": ""},
    {"Store Code": "640", "Authorization Code": "012140", "Value of Sales": 999.99,
     "Terminal ID": "55610714", "Source": ""},
])
multi_buf.seek(0)
enriched, n = _enrich_card_and_time(two_row_queue, [multi_buf])
_assert(n == 2, f"both rows enriched, one from each sheet of the same workbook, got {n}")
_assert(enriched["Card Number"].iloc[0] == "428671XXXXXX1060", "row matched against Details_mada sheet")
_assert(enriched["Card Number"].iloc[1] == "555555XXXXXX9999", "row matched against Details_CC sheet")

# --- 5. enrichment still refuses to guess when amount doesn't line up -----
raw_no_match = pd.DataFrame([
    {"Auth Code": "16934", "Transaction Amount": 999.00,  # wrong amount
     "Card Number": "000000XXXXXX0000", "Transaction Time": "00:00:00"},
])
raw_buf2 = io.BytesIO()
raw_no_match.to_excel(raw_buf2, index=False)
raw_buf2.seek(0)
raw_buf2.name = "provider_report_no_match.xlsx"
_, n2 = _enrich_card_and_time(q, [raw_buf2])
_assert(n2 == 0, "no match is made when the amount doesn't line up -- it never guesses")

print("\nREGRESSION V61 MISSING D365 FOLLOWUP MULTISHEET FIX PASS")

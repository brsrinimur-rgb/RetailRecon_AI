"""
REGRESSION_V60_MISSING_D365_FOLLOWUP_V3_DATE_FIX.py

Context: after V59 fixed the blank-CSV bug in "Missing D365 Follow-Up"
(pages/20_Missing_D365_Follow_Up.py), the page was independently rewritten
from scratch (v3) with real improvements: a stricter 3-column header-row
detector, cleaner Store Code normalization, and a genuinely useful new
feature -- enriching Card Number / Transaction Time from uploaded raw POS
provider files, matched by normalized Auth Code + exact Amount (+ Terminal
ID as a tiebreaker), never guessing when multiple files disagree.

But the rewrite did not carry over V59's Excel-serial-date fix: "Transaction
Date" was set directly from the report's raw "POS Date" value (a bare
Excel serial number like 46266.0), which _build_email()'s
pd.to_datetime() then silently misreads as a Unix timestamp -- producing
"01-Jan-1970" in the actual follow-up email text instead of the real 2026
date, with no error to flag it. Same bug class as V59, reintroduced by the
rewrite.

Fixed by adding _report_date() (interprets the number against Excel's real
epoch, 1899-12-30) and applying it when building "Transaction Date". This
test covers that fix plus a functional check of the new raw-file
enrichment feature and the other pieces already independently confirmed
correct.

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
exec(compile(src[start:cut], "page20_v3_fixed_logic", "exec"), ns)

_load_missing_d365_from_report = ns["_load_missing_d365_from_report"]
_build_email = ns["_build_email"]
_clean_code = ns["_clean_code"]
_report_date = ns["_report_date"]
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


# --- 1. the reintroduced 1970-date bug, now fixed -------------------------
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

dt = q["Transaction Date"].iloc[0]
_assert(pd.Timestamp(dt).year == 2026, f"Transaction Date resolves to 2026, not a 1970 artifact, got {dt}")
_assert(pd.Timestamp(dt).date() == pd.Timestamp("2026-09-01").date(), f"Excel serial 46266 -> 2026-09-01, got {dt}")

subject, body = _build_email(q)
_assert("1970" not in body, "the generated email body contains no 1970 garbage date (was reintroduced by the v3 rewrite)")
_assert("01-Sep-2026" in body, "the generated email body shows the real date")

# --- 2. _report_date unit behavior -----------------------------------------
_assert(_report_date(None) is None, "_report_date(None) is None, not a crash")
_assert(_report_date("") is None, "_report_date('') is None")
_assert(pd.Timestamp(_report_date(46269.0)).date() == pd.Timestamp("2026-09-04").date(),
        "_report_date correctly converts another serial (46269 -> 2026-09-04)")

# --- 3. raw-provider-file enrichment (new v3 feature) works ----------------
raw = pd.DataFrame([
    {"Store": "615", "Auth Code": "16934", "Transaction Amount": 12665.00,
     "Card Number": "428671XXXXXX1060", "Transaction Time": "15:22:23", "Terminal ID": "55610703"},
])
raw_buf = io.BytesIO()
raw.to_excel(raw_buf, index=False)
raw_buf.seek(0)
raw_buf.name = "provider_report.xlsx"

enriched, n = _enrich_card_and_time(q, [raw_buf])
_assert(n == 1, f"exactly 1 row enriched from the raw provider file, got {n}")
_assert(enriched["Card Number"].iloc[0] == "428671XXXXXX1060", "Card Number correctly enriched via normalized Auth Code + exact Amount match")
_assert(enriched["Transaction Time"].iloc[0] == "15:22:23", "Transaction Time correctly enriched")

# Enrichment must not fabricate a match when auth+amount don't line up.
raw_no_match = pd.DataFrame([
    {"Store": "615", "Auth Code": "16934", "Transaction Amount": 999.00,  # wrong amount
     "Card Number": "000000XXXXXX0000", "Transaction Time": "00:00:00"},
])
raw_buf2 = io.BytesIO()
raw_no_match.to_excel(raw_buf2, index=False)
raw_buf2.seek(0)
raw_buf2.name = "provider_report_2.xlsx"
_, n2 = _enrich_card_and_time(q, [raw_buf2])
_assert(n2 == 0, "no match is made when the amount doesn't line up -- it never guesses")

print("\nREGRESSION V60 MISSING D365 FOLLOWUP V3 DATE FIX PASS")

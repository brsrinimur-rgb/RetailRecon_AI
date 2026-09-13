"""
REGRESSION_V63_MISSING_D365_FOLLOWUP_TIMEFIX_TERMINALID_REFIX.py

Context: this upload ("TIME_FIX") independently rewrote the transaction-time
formatter as _format_transaction_time(), replacing V62's _format_raw_time().
It is a solid rewrite -- it handles the same real cases (HHMMSS integers
like 131911, Excel time-of-day fractions, already-clean "HH:MM:SS" strings,
blank/NaN) and additionally applies the formatter in _build_email() itself,
so even a Transaction Time value that reached the queue unformatted from
some other path still renders correctly in the actual email text. Verified
correct against the exact real HHMMSS case (131911 -> "13:19:11") and a
battery of edge cases (5-digit values, Excel fractions, already-clean
strings, invalid/out-of-range values left unchanged rather than guessed at).

But this upload ALSO regressed Terminal ID's ".0" cleanup -- back to plain
`.fillna("").astype(str).str.strip()` instead of `.map(_clean_code)`. This
is the FOURTH time this exact single field has regressed across separate
uploads of this page (previously in the "MULTI_SHEET_FIX" upload, and
before that caught live in production via your own screenshot). Reproduced
against your real Reconciliation_latest.xlsx: Terminal ID came back as
"55610703.0" again. Fixed the same way as every time before -- routing it
through _clean_code().

This test locks down both: the new time-formatting logic (so its quality
is preserved) and Terminal ID cleanup (so this exact field can't silently
revert a fifth time without a test catching it), plus re-checks every
other fix carried over from V59-V62 (date, Store Code, multi-sheet raw-file
reading, "never guess on a wrong amount").
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
exec(compile(src[start:cut], "page20_v63_logic", "exec"), ns)

_load_missing_d365_from_report = ns["_load_missing_d365_from_report"]
_build_email = ns["_build_email"]
_clean_code = ns["_clean_code"]
_report_date = ns["_report_date"]
_format_transaction_time = ns["_format_transaction_time"]
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


# --- 1. Terminal ID regressed a 4th time -- re-fixed and re-checked --------
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
        f"Terminal ID correctly cleaned (no spurious .0 -- this is the FOURTH time this exact "
        f"field has regressed; reproduced live against Reconciliation_latest.xlsx before this fix), "
        f"got {q['Terminal ID'].iloc[0]!r}")

dt = q["Transaction Date"].iloc[0]
_assert(pd.Timestamp(dt).date() == pd.Timestamp("2026-09-01").date(), f"Excel serial 46266 -> 2026-09-01, got {dt}")

subject, body = _build_email(q)
_assert("1970" not in body, "the generated email body contains no 1970 garbage date")
_assert("01-Sep-2026" in body, "the generated email body shows the real date")

# --- 2. _format_transaction_time (this upload's new rewrite) unit checks ---
_assert(_format_transaction_time(131911.0) == "13:19:11", "HHMMSS float -> HH:MM:SS (the exact real case from your CSV)")
_assert(_format_transaction_time("131911.0") == "13:19:11", "HHMMSS as string -> HH:MM:SS")
_assert(_format_transaction_time(91503) == "09:15:03", "5-digit HHMMSS (leading hour digit implicit) -> HH:MM:SS")
_assert(_format_transaction_time(0.5) == "12:00:00", "Excel time-of-day fraction 0.5 -> 12:00:00")
_assert(_format_transaction_time("13:19:11") == "13:19:11", "an already-clean time string passes through unchanged")
_assert(_format_transaction_time(None) == "", "_format_transaction_time(None) is '', not a crash")
_assert(_format_transaction_time("") == "", "_format_transaction_time('') is ''")
_assert(_format_transaction_time(float("nan")) == "", "_format_transaction_time(NaN) is ''")
_assert(_format_transaction_time(999999) == "999999",
        "an invalid/out-of-range value (99:99:99) is left as-is rather than guessed at")

# --- 3. real-shape enrichment: HHMMSS from a raw provider file ends up correct in the queue ---
qrow = pd.DataFrame([
    {"Store Code": "615", "Authorization Code": "016934", "Value of Sales": 12665.00,
     "Terminal ID": "55610703", "Source": "raw.xlsx"},
])
raw = pd.DataFrame([
    {"Auth Code": "16934", "Transaction Amount": 12665.00, "Card Number": "428671XXXXXX1060",
     "Transaction Time": 131911, "Terminal ID": "55610703"},
])
raw_buf = io.BytesIO()
raw.to_excel(raw_buf, index=False)
raw_buf.seek(0)
raw_buf.name = "raw.xlsx"
enriched, n = _enrich_card_and_time(qrow, [raw_buf])
_assert(n == 1, f"1 row enriched, got {n}")
_assert(enriched["Transaction Time"].iloc[0] == "13:19:11",
        f"raw HHMMSS integer 131911 correctly becomes '13:19:11', got {enriched['Transaction Time'].iloc[0]!r}")
_assert(float(enriched["Value of Sales"].iloc[0]) == 12665.00, "Value of Sales stays untouched")

subj2, body2 = _build_email(enriched)
_assert("13:19:11" in body2, "the formatted time also shows correctly in the generated email body")

# --- 4. multi-sheet raw provider file reading (V61) still works -----------
multi_buf = io.BytesIO()
with pd.ExcelWriter(multi_buf, engine="openpyxl") as w:
    pd.DataFrame([{"Summary": "Cover page, no transaction data here"}]).to_excel(
        w, sheet_name="Cover", index=False
    )
    pd.DataFrame([
        {"Auth Code": "16934", "Transaction Amount": 12665.00, "Card Number": "428671XXXXXX1060",
         "Transaction Time": 131911, "Terminal ID": "55610703"},
    ]).to_excel(w, sheet_name="Details_mada", index=False)
    pd.DataFrame([
        {"Auth Code": "012140", "Transaction Amount": 999.99, "Card Number": "555555XXXXXX9999",
         "Transaction Time": 91000, "Terminal ID": "55610714"},
    ]).to_excel(w, sheet_name="Details_CC", index=False)
multi_buf.seek(0)
multi_buf.name = "provider_multisheet.xlsx"

combined = _read_raw_provider(multi_buf)
_assert(set(combined["_RAW_SHEET"].unique()) == {"Details_mada", "Details_CC"},
        "both real transaction sheets are read and the Cover sheet is skipped")

# --- 5. enrichment still refuses to guess when amount doesn't line up -----
raw_no_match = pd.DataFrame([
    {"Auth Code": "16934", "Transaction Amount": 999.00,  # wrong amount
     "Card Number": "000000XXXXXX0000", "Transaction Time": 0},
])
raw_buf2 = io.BytesIO()
raw_no_match.to_excel(raw_buf2, index=False)
raw_buf2.seek(0)
raw_buf2.name = "provider_report_no_match.xlsx"
_, n2 = _enrich_card_and_time(q, [raw_buf2])
_assert(n2 == 0, "no match is made when the amount doesn't line up -- it never guesses")

print("\nREGRESSION V63 MISSING D365 FOLLOWUP TIMEFIX TERMINALID REFIX PASS")

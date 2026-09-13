"""
REGRESSION_V59_MISSING_D365_FOLLOWUP_REPORT_PARSE.py

Real reported bug (2026-09-13): uploading a real RetailRecon reconciliation
report into the "Missing D365 Follow-Up" page (20) and downloading its CSV
produced 195 rows that were completely blank (only "Value of Sales"=0.0 and
"Follow-Up Status" populated) -- no Store Code, no amounts, nothing.

Root cause, confirmed against the user's real uploaded report
("RetailReconAI_Reconciliation - 2026-09-13T195311.652.xlsx"):

  1. RetailRecon's exported reports (report_export.py) write a title row and
     a "Generated ... | N row(s)" row before the real header -- the header
     is NOT row 0. `load_queue_from_report()` read the sheet with
     `pd.read_excel(file, sheet_name=sheet)` (default header=0), so pandas
     used the title text as the column header and every real column name
     ("Store Code", "Status", "Auth Code", ...) never existed -- they show
     up as "Unnamed: N" instead, with the real header text buried as a data
     value further down. That silently no-ops the `if "Status" in
     df.columns` filter (so it doesn't filter to Missing D365 at all -- it
     lets every exception row through regardless of status), and every
     `r.get("Store Code", "")` etc. below returns blank/zero for every row.

  2. Even with the header fixed, Store Code and Terminal ID come back as
     float64 (615.0) from the Excel read. A naive str() turns 615 into
     "615.0", which then fails to match the plain-string "615" Store Code
     in the Store Email Master CSV -- every row's To/CC email would come
     back blank even after fixing bug #1.

  3. Also even with the header fixed, "POS Date" comes through as a raw
     Excel serial number (e.g. 46266.0), not a real date. build_email()
     downstream calls pd.to_datetime() on whatever "Transaction Date" is;
     pd.to_datetime(46266.0) is misread as a Unix timestamp in
     nanoseconds -- a garbage 1970-something date, not the real 2026 date,
     with no error raised to flag it.

Fixed by: _read_report_sheet_with_real_header() (scans for the real header
row instead of assuming row 0), _clean_id() (strips a spurious ".0" off
whole-number floats), and _report_date() (interprets a bare numeric POS
Date against Excel's actual epoch, 1899-12-30, instead of Unix epoch).

This test builds a small synthetic report in RetailRecon's REAL export
shape (title row, "Generated..." row, blank row, header row, data --
matching report_export.py's own `startrow=3` convention) so it doesn't
depend on any uploaded file being present in this environment.
"""
import io
import re
from pathlib import Path
import pandas as pd

src = open("pages/20_Missing_D365_Follow_Up.py").read()
start = src.index("MASTER_PATH = Path(")
cut = src.index('st.title("📨 Missing D365 Follow-Up")')
ns = {"re": re, "Path": Path, "pd": pd}
exec(compile(src[start:cut], "page20_logic", "exec"), ns)

load_queue_from_report = ns["load_queue_from_report"]
build_email = ns["build_email"]
_clean_id = ns["_clean_id"]
_report_date = ns["_report_date"]


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")


def _make_report_bytes(exceptions_df):
    """Mirror report_export.py: title row, 'Generated...' row, blank row,
    then the real header + data at startrow=3."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        exceptions_df.to_excel(w, sheet_name="Exceptions", index=False, startrow=3)
        ws = w.sheets["Exceptions"]
        ws["A1"] = "Exceptions"
        ws["A2"] = f"Generated 13-Sep-2026 16:52 | {len(exceptions_df)} exception row(s)"
    buf.seek(0)
    return buf


# --- 1. header-row bug: real header is 3 rows down, not row 0 ------------
exceptions = pd.DataFrame([
    {"Store Code": 615, "Auth Code": "016934", "POS Tender": "MADA", "POS Total": 12665.00,
     "Terminal ID": 55610703, "POS Date": 46266.0, "Status": "Missing D365"},
    {"Store Code": 640, "Auth Code": "012140", "POS Tender": "MADA", "POS Total": 2490.00,
     "Terminal ID": 55610714, "POS Date": 46266.0, "Status": "Missing D365"},
    {"Store Code": 601, "Auth Code": "999999", "POS Tender": "VISA", "POS Total": 500.00,
     "Terminal ID": 55610700, "POS Date": 46267.0, "Status": "Missing POS"},  # must be excluded
])
report = _make_report_bytes(exceptions)
q = load_queue_from_report(report)

_assert(len(q) == 2, f"only the 2 real 'Missing D365' rows survive (not the 'Missing POS' row or a blank-everything result), got {len(q)}")
_assert(set(q["Store Code"]) == {"615", "640"}, f"Store Code values are correct, got {set(q['Store Code'])}")
_assert(q["Value of Sales"].sum() == 15155.00, f"amounts are correctly extracted (not 0.0), got {q['Value of Sales'].sum()}")
_assert(all(str(a) in {"016934", "012140"} for a in q["Authorization Code"]), "Auth Codes correctly extracted")

# --- 2. Store Code / Terminal ID float-suffix bug -------------------------
_assert(_clean_id(615.0) == "615", f"_clean_id strips the spurious .0, got {_clean_id(615.0)!r}")
_assert(_clean_id("615") == "615", "_clean_id leaves an already-clean string alone")
_assert(_clean_id(None) == "", "_clean_id handles None")
_assert(all(not s.endswith(".0") for s in q["Store Code"]), "no Store Code in the real parse ends with a spurious '.0'")
_assert(all(not s.endswith(".0") for s in q["Terminal ID"]), "no Terminal ID in the real parse ends with a spurious '.0'")

# This is the actual merge the page performs against the Store Email Master --
# prove it now succeeds instead of silently matching nothing.
master = pd.DataFrame([{"Store Code": "615", "Store Name": "Tag Heuer - Riyadh Park", "To Email": "x@y.com", "CC Email": ""}])
merged = q.merge(master, how="left", on="Store Code", suffixes=("", "_M"))
_assert(merged.loc[merged["Store Code"] == "615", "To Email"].iloc[0] == "x@y.com",
        "Store Code now actually matches the Store Email Master (was silently failing before the fix)")

# --- 3. Excel-serial "POS Date" must not become a 1970 garbage date ------
dt615 = q.loc[q["Store Code"] == "615", "Transaction Date"].iloc[0]
_assert(pd.Timestamp(dt615).year == 2026, f"Transaction Date resolves to the real 2026 date, not a 1970 Unix-epoch artifact, got {dt615}")
_assert(pd.Timestamp(dt615).date() == pd.Timestamp("2026-09-01").date(), f"Excel serial 46266 -> 2026-09-01, got {dt615}")

subject, body = build_email(q[q["Store Code"] == "615"])
_assert("1970" not in body, "the generated email body contains no 1970 garbage date")
_assert("01-Sep-2026" in body, "the generated email body shows the real date")
_assert("Total SAR: 12,665.00" in body, "the generated email body totals correctly")

# --- 4. empty/garbage upload doesn't crash --------------------------------
empty_report = _make_report_bytes(pd.DataFrame(columns=["Store Code", "Status"]))
_assert(load_queue_from_report(empty_report).empty, "an upload with zero exception rows returns an empty queue, not an error")
_assert(load_queue_from_report(None).empty, "a None file returns an empty queue")

print("\nREGRESSION V59 MISSING D365 FOLLOWUP REPORT PARSE PASS")

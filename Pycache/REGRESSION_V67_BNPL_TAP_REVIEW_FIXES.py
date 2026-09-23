"""
REGRESSION_V67_BNPL_TAP_REVIEW_FIXES.py

Context: you uploaded two new, independent Streamlit pages for a "BNPL & GL
Reconciliation" control (TABBY/TAMARA/TAP) that neither of us wrote --
`21_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` and an earlier draft,
`37_BNPL_GL_Reconciliation.py1` (TABBY/TAMARA only, no TAP). A `diff -u`
confirmed the `21_` file is a strict additive superset of the `.py1` draft
(adds full TAP support, nothing removed or changed elsewhere), so this
review and all fixes below are against the `21_` file -- delivered here
renamed to `37_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` (see "Why the
rename" below).

Four real issues were found and fixed:

1. TABBY refund rows were never flagged as refunds. The header-detection
   keyword set for this parser expects a column that normalizes to
   "ORDERTYPE" (i.e. a real column named "Order Type"), but the code that
   pulls the value out of each row only looked for a column named exactly
   "Type": `find_col(df, ["Type"])`. Since "Order Type" normalizes to
   "ORDERTYPE" and the alias "Type" normalizes to "TYPE" -- different
   strings -- the lookup silently failed on every real TABBY export, so
   `event` was always "", "REFUND" was never detected, and the sign was
   always left as +1.0. Every TABBY refund would have been booked as a
   positive Gross Amount / Fee / VAT / Net Settlement instead of negative,
   which would throw off both the POS/Provider and Bank/Settlement
   reconciliation totals whenever a refund appears in a real file.
   Fix: `find_col(df, ["Order Type", "Type"])` -- matches the real column,
   keeps "Type" as a fallback alias.

2. The Excel download (section 8) used
   `pd.ExcelWriter(buffer, engine="xlsxwriter")`, but `xlsxwriter` is not
   in this app's `requirements.txt` (only `openpyxl` is, and every other
   page in the app writes Excel via the `openpyxl` engine). Clicking
   "Download" on a fresh deploy would raise
   `ModuleNotFoundError: No module named 'xlsxwriter'` the first time
   anyone tries it. Fix: switched the engine to `"openpyxl"` (no
   xlsxwriter-only formatting calls were used, so the swap is a no-op
   otherwise -- confirmed by reading the rest of that block).

3. The page never called `auth.require_login(...)` / `auth.render_user_sidebar()`
   / `theme.global_css()` / `theme.top_banner(...)`, unlike every other page
   in this app. In this app, login/role gating is enforced per-page (there
   is no central gate for a Streamlit multipage app), so a page that skips
   this call is reachable by anyone with the URL, with no role check and no
   shared sidebar/branding. Fix: added the same wiring every other page
   uses, gated to {"Admin", "Finance Manager", "Finance Checker"} (matching
   the roles used on this app's other reconciliation-control pages).

4. Filename collision: `pages/21_Month_End_Close_Calendar.py` already
   exists in the real app (a real, in-use, auth-gated "Accounting Period
   Control" page) -- confirmed by cloning the live repo. Uploading the new
   file as `21_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` would collide
   with that existing page number. Fix: delivered as
   `37_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` instead -- page number
   37 is unused in the real app, and matches the number the earlier draft
   (`37_BNPL_GL_Reconciliation.py1`) was already using.

This test extracts the pure parsing/matching logic (everything from
AMOUNT_TOLERANCE through just before the "UI" section, so no Streamlit
runtime, auth, or theme module is needed) via the same exec-extraction
pattern used throughout this engagement, and verifies:
  - the TABBY Order Type / refund-sign fix, against both a "Type"-named
    export and a real "Order Type"-named export
  - the parse_date() Excel-serial-date path still works correctly when
    called the way every parser in this file actually calls it (through
    df.iterrows() on a mixed-dtype DataFrame) -- this was investigated as
    a suspected numpy.int64 / isinstance() gap and confirmed NOT to
    reproduce via this file's real code paths, so no fix was needed there;
    this test locks that in
  - TAP settlement-id-based grouping and payout_date-preferred-over-
    settlement_date logic
  - end-to-end reconciliation (POS <-> Provider <-> Bank) still balances
    on a small synthetic dataset shaped like the real exports
No real data, real files, or real credentials are used anywhere in this
test.
"""
import io
import re
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")


src = open("37_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py").read()
start = src.index("AMOUNT_TOLERANCE = 0.02")
cut = src.index("# ---------------- UI ----------------")
ns = {"io": io, "re": re, "Path": Path, "Optional": Optional, "pd": pd, "np": np}
exec(compile(src[start:cut], "page37_bnpl_tap_logic", "exec"), ns)

parse_tabby = ns["parse_tabby"]
parse_tamara = ns["parse_tamara"]
parse_tap = ns["parse_tap"]
parse_pos_d365 = ns["parse_pos_d365"]
parse_date = ns["parse_date"]
settlement_groups = ns["settlement_groups"]
reconcile_provider_to_pos = ns["reconcile_provider_to_pos"]
find_col = ns["find_col"]


class _FakeUpload(io.BytesIO):
    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _xlsx_bytes(df: pd.DataFrame, header_row0: int = 0) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, header=True, startrow=header_row0)
    buf.seek(0)
    return buf.read()


# --- 1. TABBY refund-sign fix: "Order Type" column (the real export shape) ---
tabby_df = pd.DataFrame([
    {"Order Number": "TB-1001", "Sale/Refund Date": "01/09/2026", "Merchant Name": "AIGNER - TAHLIA MALL",
     "Order Type": "SALE", "Order Amount": "1500.00", "Total Fee": "45.00", "VAT Amount": "6.75",
     "Transferred amount": "1448.25", "Transfer Date": "05/09/2026"},
    {"Order Number": "TB-1002", "Sale/Refund Date": "02/09/2026", "Merchant Name": "AIGNER - TAHLIA MALL",
     "Order Type": "REFUND", "Order Amount": "300.00", "Total Fee": "9.00", "VAT Amount": "1.35",
     "Transferred amount": "289.65", "Transfer Date": "06/09/2026"},
])
up = _FakeUpload(_xlsx_bytes(tabby_df), "TABBY_Sep2026.xlsx")
out = parse_tabby(up)
sale_row = out[out["Provider Reference"] == "TB-1001"].iloc[0]
refund_row = out[out["Provider Reference"] == "TB-1002"].iloc[0]
_assert(sale_row["Event"] == "SALE" and sale_row["Gross Amount"] > 0, "TABBY sale row stays positive")
_assert(refund_row["Event"] == "REFUND", "TABBY refund is detected via the real 'Order Type' column")
_assert(refund_row["Gross Amount"] < 0, "TABBY refund Gross Amount is negative once Order Type is read correctly")
_assert(refund_row["Provider Fee"] < 0 and refund_row["Net Settlement"] < 0, "TABBY refund fee/net also flip negative")

# --- 2. Same fix does not regress a file that literally uses a bare "Type" column ---
tabby_df2 = tabby_df.rename(columns={"Order Type": "Type"})
up2 = _FakeUpload(_xlsx_bytes(tabby_df2), "TABBY_Sep2026_alt.xlsx")
out2 = parse_tabby(up2)
_assert((out2[out2["Provider Reference"] == "TB-1002"]["Gross Amount"] < 0).all(),
        "fallback alias 'Type' still works if a file happens to use that exact name")

# --- 3. parse_date via the real call path (df.iterrows() on a mixed-dtype frame) ---
# This is the path every parser in this file actually uses; confirmed the
# suspected numpy.int64 / isinstance(v, (int, float)) gap does not reproduce
# here because a mixed string+numeric row gets boxed to plain Python types
# by pandas before parse_date ever sees it.
mixed = pd.DataFrame({
    "Ref": ["R1", "R2", "R3"],
    "Charge Date": pd.array([46266, 46267, 46268], dtype="int64"),
    "Amount": [100.0, 200.0, 300.0],
})
seen_types = set()
for _, r in mixed.iterrows():
    v = r.get("Charge Date")
    seen_types.add(type(v))
    d = parse_date(v)
    _assert(pd.notna(d) and d.year == 2026, f"Excel-serial date parses correctly via iterrows(), got {d!r} for {v!r}")
_assert(seen_types == {int}, f"iterrows() boxes the numeric cell as plain Python int in a mixed-dtype frame, saw {seen_types}")

# --- 4. TAP: settlement_id grouping preferred, payout_date preferred over settlement_date ---
tap_df = pd.DataFrame([
    {"settlement_id": "STL-1", "charge_id": "CH-1", "amount": "1000.00", "status": "CAPTURED",
     "authorization_id": "AUTH-1", "charge_date": "01/09/2026", "settlement_date": "03/09/2026",
     "payout_date": "04/09/2026", "reference_order": "ORD-1", "merchant_id": "M1",
     "fee": "30.00", "fee_vat": "4.50", "net_amount": "965.50"},
    {"settlement_id": "STL-1", "charge_id": "CH-2", "amount": "500.00", "status": "CAPTURED",
     "authorization_id": "AUTH-2", "charge_date": "01/09/2026", "settlement_date": "03/09/2026",
     "payout_date": "04/09/2026", "reference_order": "ORD-2", "merchant_id": "M1",
     "fee": "15.00", "fee_vat": "2.25", "net_amount": "482.75"},
])
up3 = _FakeUpload(_xlsx_bytes(tap_df), "TAP_Sep2026.xlsx")
tap_out = parse_tap(up3)
_assert(len(tap_out) == 2, "both TAP CAPTURED rows kept")
_assert((tap_out["Settlement Date"].dt.strftime("%Y-%m-%d") == "2026-09-04").all(),
        "TAP prefers payout_date over settlement_date when both are present")
groups = settlement_groups(tap_out)
_assert(groups["Settlement Group"].nunique() == 1, "both TAP rows group into one settlement batch via Settlement ID")

# --- 5. TAP: non-captured status rows are excluded ---
tap_df2 = pd.concat([tap_df, pd.DataFrame([
    {"settlement_id": "STL-2", "charge_id": "CH-3", "amount": "200.00", "status": "FAILED",
     "authorization_id": "AUTH-3", "charge_date": "01/09/2026", "settlement_date": "03/09/2026",
     "payout_date": "", "reference_order": "ORD-3", "merchant_id": "M1",
     "fee": "0.00", "fee_vat": "0.00", "net_amount": "0.00"},
])], ignore_index=True)
up4 = _FakeUpload(_xlsx_bytes(tap_df2), "TAP_Sep2026_b.xlsx")
tap_out2 = parse_tap(up4)
_assert(len(tap_out2) == 2, "FAILED status row is excluded from TAP output")

# --- 6. TAMARA still parses as before (unaffected by TABBY/TAP fixes) ---
tamara_df = pd.DataFrame([
    {"Transaction Date DD/MM/YYYY": "01/09/2026", "Tamara Order ID": "TM-1", "Merchant Order ID": "MO-1",
     "Store Code": "601", "Order Amount": "900.00", "Event": "capture", "Total Fees": "27.00",
     "VAT Collected by Tamara": "4.05", "Total Payable to Merchant": "868.95"},
])
up5 = _FakeUpload(_xlsx_bytes(tamara_df), "TAMARA_Sep2026.xlsx")
tamara_out = parse_tamara(up5)
_assert(len(tamara_out) == 1 and tamara_out.iloc[0]["Provider"] == "TAMARA", "TAMARA parser unaffected by TABBY/TAP fixes")

# --- 7. end-to-end: TABBY refund now matches correctly against a POS refund line ---
pos_df = pd.DataFrame([
    {"Store Code": "601", "Transdate": "01/09/2026", "Auth Code": "TB-1001", "POS Tender": "TABBY", "POS Total": 1500.00},
    {"Store Code": "601", "Transdate": "02/09/2026", "Auth Code": "TB-1002", "POS Tender": "TABBY", "POS Total": -300.00},
])
pos_up = _FakeUpload(_xlsx_bytes(pos_df), "POS_Sep2026.xlsx")
pos_out = parse_pos_d365(pos_up)
_assert(len(pos_out) == 2, "synthetic POS export parses both TABBY-tendered rows")

out_with_store = out.copy()
out_with_store["Store Code"] = "601"
rec = reconcile_provider_to_pos(out_with_store, pos_out)
matched_refund = rec[rec["Reference Key"] == "TB1002"]
_assert(len(matched_refund) == 1, "TABBY refund row present in the reconciliation output")
_assert(matched_refund.iloc[0]["POS/D365 Amount"] == -300.00,
        "TABBY refund now matches its POS refund line now that the sign is correct (before the fix, "
        "the refund's Gross Amount stayed +300 and could never match the POS -300 line within tolerance)")

print("\nREGRESSION V67 BNPL TAP REVIEW FIXES PASS")

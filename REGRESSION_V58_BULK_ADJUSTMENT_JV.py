"""
REGRESSION_V58_BULK_ADJUSTMENT_JV.py

New feature (2026-09-13): "Late Transaction Adjustment JV" page (28) gained a
bulk-upload path so Finance can create many adjustment JVs at once from a
file instead of retyping each one into the single-row form -- the real
trigger being a batch of "Missing D365" reconciliation exceptions that
needed adjustment JVs raised for all 32 of them at once.

New logic lives in logic/adjustment_bulk_extension.py (pure, no Streamlit),
imported by pages/28_Late_Transaction_Adjustment_JV.py. This test exercises
the logic module directly with real-shaped data (the same 61-column
"Missing D365" exceptions shape actually used) plus the simple manual
template, without needing a Streamlit runtime.

Covers:
  1. Simple manual template (Store/Provider/Amount/Reason) passes through
     with provider normalization.
  2. Real reconciliation-exceptions shape (Store Code/Auth Code/POS Tender/
     Net Amount/Terminal ID/Status/Remarks) is auto-normalized and gets an
     auto-built Reason when no Reason column exists.
  3. Provider normalization: MADA/VISA/MASTER/MASTERCARD collapse to CARD;
     AMEX/TABBY/TAMARA/TAP pass through unchanged; an unrecognized provider
     is kept visible (not silently dropped) rather than defaulted away.
  4. Missing/blank Store or Amount doesn't crash the preview builder -- it
     produces a row the page's own submit-time validation will then skip
     (mirrors the single-row form's existing "Store, amount and reason are
     required" rule), and an explicit "Reason" column always wins over the
     auto-built one.
  5. Empty upload returns an empty, correctly-shaped preview instead of
     raising.
"""
import pandas as pd
from logic import adjustment_bulk_extension as bulk_adj


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")


# --- 1. simple manual template -------------------------------------------
simple = pd.DataFrame([
    {"Store": "601", "Provider": "AMEX", "Amount": "150.00", "Reason": "Late file arrival"},
    {"Store": "624", "Provider": "MADA", "Amount": "279", "Reason": "Late file arrival"},
])
p1 = bulk_adj.build_bulk_preview(simple)
_assert(list(p1.columns) == bulk_adj.PREVIEW_COLUMNS, "preview has the expected 5 columns in order")
_assert(p1.iloc[0]["Store"] == "601" and p1.iloc[0]["Provider"] == "AMEX" and p1.iloc[0]["Amount"] == 150.0,
        "simple template row 1 normalized correctly")
_assert(p1.iloc[1]["Provider"] == "CARD", "MADA collapses to CARD in the simple template too")
_assert(bool(p1.iloc[0]["Include"]) is True, "rows default to Include=True for review")

# --- 2. real "Missing D365" exceptions shape (actual 32-row batch shape) -
real = pd.DataFrame([
    {
        "Store Code": "615", "Auth Code": "016934", "POS Tender": "MADA",
        "Net Amount": "12665", "Terminal ID": "55610703", "Status": "Missing D365",
        "Remarks": "Valid mapped provider transaction found but no matching D365 Store Tender transaction.",
    },
    {
        "Store Code": "629", "Auth Code": "005373", "POS Tender": "MASTER",
        "Net Amount": "20000", "Terminal ID": "55610709", "Status": "Missing D365",
        "Remarks": "Valid mapped provider transaction found but no matching D365 Store Tender transaction.",
    },
    {
        "Store Code": "652", "Auth Code": "216733", "POS Tender": "AMEX",
        "Net Amount": "200", "Terminal ID": "55610701", "Status": "Missing D365",
        "Remarks": "Valid mapped provider transaction found but no matching D365 Store Tender transaction.",
    },
])
p2 = bulk_adj.build_bulk_preview(real)
_assert(len(p2) == 3, "all 3 real-shaped rows produced a preview row")
_assert(p2.iloc[0]["Store"] == "615" and p2.iloc[0]["Provider"] == "CARD" and p2.iloc[0]["Amount"] == 12665.0,
        "row 1 (MADA) normalizes store/provider/amount from the exceptions export shape")
_assert(p2.iloc[1]["Provider"] == "CARD", "MASTER (as used in the real export) collapses to CARD")
_assert(p2.iloc[2]["Provider"] == "AMEX", "AMEX passes through unchanged")
_assert("Auth Code 016934" in p2.iloc[0]["Reason"] and "Terminal 55610703" in p2.iloc[0]["Reason"],
        "auto-built Reason includes Auth Code and Terminal ID when no Reason column exists")
_assert("Missing D365" in p2.iloc[0]["Reason"], "auto-built Reason includes the Status")

# --- 3. provider normalization matrix -------------------------------------
for raw, expected in [
    ("MADA", "CARD"), ("VISA", "CARD"), ("VISACARD", "CARD"), ("MASTER", "CARD"),
    ("MASTERCARD", "CARD"), ("mada", "CARD"),
    ("AMEX", "AMEX"), ("TABBY", "TABBY"), ("TAMARA", "TAMARA"), ("TAP", "TAP"),
]:
    got = bulk_adj.norm_provider_bulk(raw)
    _assert(got == expected, f"provider {raw!r} normalizes to {expected}, got {got}")

unknown = bulk_adj.norm_provider_bulk("FLOOSS")
_assert(unknown == "FLOOSS", f"unrecognized provider FLOOSS is kept visible, not silently defaulted, got {unknown}")

# --- 4. missing/blank fields don't crash the builder ----------------------
messy = pd.DataFrame([
    {"Store Code": "", "POS Tender": "MADA", "Net Amount": "not-a-number"},
    {"Store Code": "601", "Provider": "AMEX", "Amount": "50", "Reason": "Explicit reason wins"},
])
p3 = bulk_adj.build_bulk_preview(messy)
_assert(len(p3) == 2, "messy input still produces one preview row per input row")
_assert(p3.iloc[0]["Store"] == "" and p3.iloc[0]["Amount"] == 0.0,
        "blank store and non-numeric amount degrade to '' / 0.0 instead of raising")
_assert(p3.iloc[1]["Reason"] == "Explicit reason wins", "an explicit Reason column always wins over auto-build")

# --- 5. empty upload -------------------------------------------------------
empty = bulk_adj.build_bulk_preview(pd.DataFrame())
_assert(empty.empty and list(empty.columns) == bulk_adj.PREVIEW_COLUMNS,
        "empty upload returns an empty, correctly-shaped preview")

print("\nREGRESSION V58 BULK ADJUSTMENT JV PASS")

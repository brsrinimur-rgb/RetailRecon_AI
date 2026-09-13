"""
adjustment_bulk_extension.py

V58 addition: turns an uploaded file of late/missing transactions into
ready-to-review rows for bulk adjustment JV creation on the "Late
Transaction Adjustment JV" page, instead of retyping each one by hand into
the single-row form.

Pure data-shaping logic only -- no Streamlit, no DB writes. The page decides
what to do with the returned preview DataFrame (show it, let Finance edit
it, then call db.append_adjustment per included row).

Accepts two kinds of upload shapes and normalizes both to the same four
columns the adjustments table needs (Store, Provider, Amount, Reason):

1. A simple manual template: columns named (case-sensitive as shown)
   "Store"/"Store Code", "Provider"/"Payment Type", "Amount", and
   optionally "Reason".
2. The app's own reconciliation-exception export shape: "Store Code",
   "Auth Code", "POS Tender" (or "Payment Type"/"D365 Tender"),
   "Net Amount" (or "POS Total"/"Value of Sales"/"D365 Total"),
   "Terminal ID", "Status", "Remarks" -- Reason is auto-built from
   whichever of these are present when no explicit "Reason" column exists.
"""
from __future__ import annotations

import pandas as pd

VALID_PROVIDERS = ["CARD", "AMEX", "TABBY", "TAMARA", "TAP"]

_CARD_ALIASES = {"MADA", "VISA", "MASTER", "MASTERCARD", "VISACARD", "P", "P1", "VC", "MC"}

_STORE_COLS = ["Store", "Store Code", "StoreCode"]
_PROVIDER_COLS = ["Provider", "Payment Type", "POS Tender", "D365 Tender"]
_AMOUNT_COLS = ["Amount", "Net Amount", "POS Total", "Value of Sales", "D365 Total"]
_REASON_COLS = ["Reason"]

PREVIEW_COLUMNS = ["Include", "Store", "Provider", "Amount", "Reason"]


def norm_provider_bulk(v) -> str:
    """Collapse a raw payment-type/provider value onto this page's 5 buckets.

    CARD absorbs MADA/VISA/MASTERCARD (mirrors the CC grouping already used
    on the JV Creation page). AMEX/TABBY/TAMARA/TAP pass through unchanged.
    Anything unrecognized is kept as its own uppercased value so Finance can
    see and fix it in the preview grid rather than have it silently dropped.
    """
    s = str(v or "").strip().upper()
    if s in _CARD_ALIASES:
        return "CARD"
    if s in VALID_PROVIDERS:
        return s
    return s or "CARD"


def _first_present(row: pd.Series, names: list[str]):
    for n in names:
        if n in row.index:
            val = row[n]
            if pd.notna(val) and str(val).strip() != "":
                return val
    return None


def to_amount(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _auto_reason(row: pd.Series) -> str:
    auth_code = _first_present(row, ["Auth Code"])
    terminal = _first_present(row, ["Terminal ID"])
    status = _first_present(row, ["Status"])
    remarks = _first_present(row, ["Remarks"])
    bits = []
    if status:
        bits.append(str(status))
    if auth_code:
        bits.append(f"Auth Code {auth_code}")
    if terminal:
        bits.append(f"Terminal {terminal}")
    if remarks:
        bits.append(str(remarks))
    return " - ".join(bits) if bits else "Bulk adjustment upload"


def build_bulk_preview(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize an uploaded file into Store/Provider/Amount/Reason rows.

    Never raises on a malformed/missing field per-row -- blank Store,
    Amount 0.0, or a generic Reason simply fall through to the caller's own
    "Store, amount and reason are required" validation at submit time,
    exactly like the existing single-row form already enforces.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=PREVIEW_COLUMNS)

    rows = []
    for _, r in raw.iterrows():
        store = _first_present(r, _STORE_COLS)
        provider_raw = _first_present(r, _PROVIDER_COLS)
        amount = _first_present(r, _AMOUNT_COLS)
        reason = _first_present(r, _REASON_COLS)
        if reason is None:
            reason = _auto_reason(r)

        rows.append({
            "Include": True,
            "Store": "" if store is None else str(store).strip(),
            "Provider": norm_provider_bulk(provider_raw),
            "Amount": to_amount(amount),
            "Reason": str(reason).strip(),
        })
    return pd.DataFrame(rows, columns=PREVIEW_COLUMNS)

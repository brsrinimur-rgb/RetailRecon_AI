"""
Additive pre-processing layer for named POS/statement formats that
core.classify()/core.normalize_pos() do not always identify correctly.

V45 TAP GATEWAY FIX (2026-09-07)
--------------------------------
Confirmed production rule for TAP charge exports:
  * The uploaded TAP charge statement is a TAP gateway source.
  * Store Code is always 613 for this online TAP gateway source.
  * payment_scheme (MADA/VISA/MASTERCARD) is card-scheme detail only.
  * payment_method (APPLE_PAY/VISA/etc.) is audit detail only.
  * Neither payment_scheme nor payment_method may reclassify the provider.
  * Provider/POS Payment must remain TAP.

This is deliberately implemented in the additive adapter layer.  core.py is
not changed, and the Store + Date + Amount reconciliation key is untouched.

Existing named formats kept unchanged:
  ADCB_CHAIN_DAILY
  NBK_MERCHANT_STATEMENT
  ANB_HIVE_POS
"""

from __future__ import annotations
import pandas as pd
import core


def _sig(columns):
    """Set of ccol-normalized column names, for signature matching."""
    return {core.ccol(c) for c in columns}


def detect_named_format(df):
    """
    Detect supported raw formats from specific multi-column signatures.
    Signatures are intentionally strict so existing formats do not
    false-positive.
    """
    cols = _sig(df.columns)

    # TAP Gateway charge export.  These fields are distinctive to TAP's
    # transaction-level charge file used by United Luxury online Store 613.
    # IMPORTANT: payment_scheme is NOT the provider.  It remains card-scheme
    # audit detail only.
    if {
        "CHARGE_ID", "SETTLEMENT_ID", "REFERENCE_ORDER", "PAYMENT_SCHEME",
        "PAYMENT_METHOD", "MERCHANT_ID", "POST_AMOUNT", "NET_AMOUNT"
    } <= cols:
        return "TAP_GATEWAY_CHARGE"

    if {"AUTHORIZATION", "SALES", "CARD", "TERMINAL", "NET"} <= cols:
        return "ADCB_CHAIN_DAILY"

    if {"AUTHCODE", "TRANS_DATE", "POST_DATE", "TERMINAL_ID"} <= cols:
        return "NBK_MERCHANT_STATEMENT"

    if {"TR_ARF", "AMOUNT", "SCHEME", "LOCALDATE", "BASE_0"} <= cols:
        return "ANB_HIVE_POS"

    return None


# Raw column (ccol-normalized) -> target column name. Target names are
# strings already understood by core.normalize_pos().
_RENAME_MAPS = {
    "ADCB_CHAIN_DAILY": {
        "AUTHORIZATION": "Auth Code",
        "SALES": "Amount",
        "CARD": "Card",
        "TERMINAL": "Terminal",
        "COMMISSION": "Commission",
        "VAT_ON": "VAT",
        "NET": "Net",
        "TRAN": "Transaction Date",
    },
    "NBK_MERCHANT_STATEMENT": {
        "AUTHCODE": "Auth Code",
        "AMOUNT": "Amount",
        "CARD_TYPE": "Card Type",
        "TRANS_DATE": "Transaction Date",
        "POST_DATE": "Posting Date",
        "TERMINAL_ID": "Terminal ID",
        "MSC": "Commission",
        "NET_AMT": "Net Amount",
        "STORE": "Store",
    },
    "ANB_HIVE_POS": {
        "BASE_0": "Terminal ID",
    },
    "TAP_GATEWAY_CHARGE": {
        # Keep TAP's native fields intact as much as possible.  These aliases
        # only help core normalize the financial/date/reference fields.
        "AMOUNT": "Amount",
        "CHARGE_DATE": "Transaction Date",
        "POST_DATE": "Posting Date",
        "REFERENCE_ORDER": "Provider Reference",
        "AUTHORIZATION_ID": "Auth Code",
        "MERCHANT_ID": "Merchant ID",
        "FEE": "Commission",
        "FEE_VAT": "VAT",
        "NET_AMOUNT": "Net Amount",
    },
}

_RETURN_STATUS_VALUES = {"RETURN", "RETURNED", "REFUND", "REFUNDED"}
_STATUS_COLUMN_CANDIDATES = ["STATUS", "TRANSACTION_STATUS", "TRANSACTION_TYPE", "TRAN_TYPE", "TYPE"]


def _rename_for_core(df, fmt):
    ren = {}
    for c in df.columns:
        target = _RENAME_MAPS.get(fmt, {}).get(core.ccol(c))
        if target:
            ren[c] = target
    return df.rename(columns=ren)


def _reversal_amounts(raw_df):
    """Return amount marker for NBK return/refund rows."""
    cols = {core.ccol(c): c for c in raw_df.columns}
    status_col = next((cols[k] for k in _STATUS_COLUMN_CANDIDATES if k in cols), None)
    amt_col = cols.get("AMOUNT")
    if status_col is None or amt_col is None:
        return pd.Series(0.0, index=raw_df.index)
    is_return = raw_df[status_col].astype(str).str.strip().str.upper().isin(_RETURN_STATUS_VALUES)
    rev = raw_df[amt_col].where(is_return, 0.0)
    return pd.to_numeric(rev, errors="coerce").fillna(0.0)


def _tap_scheme_by_row(raw_df):
    """Position-indexed TAP card scheme for audit/reference only."""
    cols = {core.ccol(c): c for c in raw_df.columns}
    scheme_col = cols.get("PAYMENT_SCHEME")
    if scheme_col is None:
        return pd.Series("", index=raw_df.index, dtype=object)
    return raw_df[scheme_col].fillna("").astype(str).str.strip().str.upper()


def normalize_named_pos(df, fmt, source="POS", forced_payment=None):
    """
    Normalize a detected format using core.normalize_pos(), then apply only
    format-specific additive controls.
    """
    df = df.reset_index(drop=True)
    renamed = _rename_for_core(df, fmt)

    if fmt == "TAP_GATEWAY_CHARGE":
        # Critical business rule: source identity wins over card scheme.
        out = core.normalize_pos(renamed, source=source, forced_payment="TAP")
    else:
        out = core.normalize_pos(renamed, source=source, forced_payment=forced_payment)

    if out is None or out.empty:
        if out is not None:
            out = out.copy()
            out["Reversal Amount"] = pd.Series(dtype=float)
            if fmt == "TAP_GATEWAY_CHARGE":
                out["Card Scheme"] = pd.Series(dtype=object)
        return out

    out = out.copy()

    if fmt == "NBK_MERCHANT_STATEMENT":
        rev_by_row = _reversal_amounts(df)
        out["Reversal Amount"] = out["POS Row"].map(lambda r: rev_by_row.get(r - 1, 0.0))
    else:
        out["Reversal Amount"] = 0.0

    if fmt == "TAP_GATEWAY_CHARGE":
        # Store 613 is the confirmed online TAP Gateway location.
        # Force provider/payment identity AFTER core normalization so raw
        # payment_scheme values can never overwrite TAP.
        out["POS Store"] = "613"
        out["Provider"] = "TAP"
        out["POS Payment"] = "TAP"

        # Preserve MADA/VISA/MASTERCARD as audit-only information.
        scheme_by_row = _tap_scheme_by_row(df)
        if "POS Row" in out.columns:
            out["Card Scheme"] = out["POS Row"].map(lambda r: scheme_by_row.get(r - 1, ""))
        else:
            out["Card Scheme"] = ""

    return out


def normalize_pos_universal(df, source="POS", forced_payment=None):
    """
    Detect a named format and route it through the additive adapter.
    All other formats continue through core.normalize_pos() unchanged.
    Returns (normalized_dataframe, detected_format_or_None).
    """
    fmt = detect_named_format(df)
    if fmt:
        return normalize_named_pos(df, fmt, source, forced_payment), fmt
    return core.normalize_pos(df, source=source, forced_payment=forced_payment), None

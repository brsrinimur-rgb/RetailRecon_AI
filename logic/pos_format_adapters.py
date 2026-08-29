"""
logic/pos_format_adapters.py

Additive pre-processing layer for the named bank POS/statement formats from
the "Universal POS Import" guide (2026-08-27) that core.classify()/
core.normalize_pos()'s own column-name finders don't recognize verbatim:
ADCB_CHAIN_DAILY, NBK_MERCHANT_STATEMENT, ANB_HIVE_POS.

WHY A WRAPPER INSTEAD OF EDITING core.py's SYNONYM LISTS DIRECTLY:
core.py already uses shared per-field synonym lists (Auth, Amount, Date,
Terminal, Commission, VAT, Net...) across every provider it supports, and
that pattern would normally suggest just appending new synonyms to those
lists. But V32_Real_Codebase_Upload_Audit_Findings.md found the real GitHub
repo already has newer core.py changes (V40-V44) that were never sent back
into this session -- meaning any local copy of core.py here could be stale
relative to production. Directly editing and re-delivering a full core.py
risks silently reverting fixes this session can't see.

This module avoids that risk entirely: it detects a named format from its
RAW (pre-normalization) column signature, RENAMES those raw columns onto
synonym strings core.normalize_pos() ALREADY recognizes (verified directly
against the running core.py in this session), and then calls
core.normalize_pos() completely unchanged. Zero lines of core.py are
touched. Every previously-supported format's detection/parsing path is
identical to today, since detect_named_format() only ever returns non-None
for these three new, specific signatures.

The one genuinely NEW field this adds -- "Reversal Amount" for
NBK_MERCHANT_STATEMENT's preserved RETURN rows -- is computed independently
from core.normalize_pos()'s own row-construction and merged back on by the
"POS Row" position it already stamps, again without touching core.py.

FORMATS COVERED (per the guide):
  ADCB_CHAIN_DAILY
    AUTHORIZATION -> Auth Code; SALES -> Gross; CARD -> Payment;
    TERMINAL -> TID; COMMISSION -> fee; VAT ON -> VAT; NET -> Net;
    TRAN -> one date field used for both transaction and posting date
    (this format doesn't split the two -- only Transaction Date is mapped;
    Posting Date is left blank, same as any other format that only
    supplies one date).

  NBK_MERCHANT_STATEMENT
    AUTHCODE -> Auth Code; AMOUNT -> Gross; CARD TYPE -> Payment;
    TRANS DATE -> transaction date; POST DATE -> posting date;
    TERMINAL ID -> TID; MSC -> commission; NET AMT -> net; Store -> store
    code. RETURN rows: core.normalize_pos() never drops "RETURN" status
    (only CANCEL/CANCELLED/FAILED/FAIL/VOID/VOIDED/EXPIRED) -- the row
    already survives untouched. This module only ADDS the "Reversal
    Amount" marker column (the row's own Amount where a status column
    reads RETURN/RETURNED/REFUND/REFUNDED, else 0.0) so a return is
    visibly flagged, not just silently present.
    KNOWN LIMITATION: no real NBK sample file was available to confirm the
    exact literal header name of its status/return-type column. This
    module checks a short list of common candidates (STATUS,
    TRANSACTION_STATUS, TRANSACTION_TYPE, TRAN_TYPE, TYPE); if the real
    file uses a different header, Reversal Amount safely defaults to 0.0
    for every row (no crash, no wrong flag) rather than guessing -- worth
    confirming against a real sample file.

  ANB_HIVE_POS
    tr_arf/amount/scheme/localdate/posting_date already match
    core.normalize_pos()'s existing synonym lists verbatim -- no rename
    needed for those. base_0 -> Terminal ID is the one real gap.
    total_amount -> Net: deliberately NOT renamed. core's Amount finder
    checks the literal "amount" column before it ever considers
    "total_amount", so Gross correctly binds to "amount" and Net's finder
    then correctly binds the only remaining candidate, "total_amount" --
    verified by direct test, no collision when both columns are present
    (which the guide's spec confirms they are for this format). No 6-digit
    approval code in this format -- tr_arf is used as the Auth/Reference
    key; if D365's own Auth Code isn't the same value as tr_arf, those
    rows legitimately stay unmatched. This module does not invent an
    approval code to force a match.
"""

from __future__ import annotations
import pandas as pd
import core


def _sig(columns):
    """Set of ccol-normalized column names, for signature matching."""
    return {core.ccol(c) for c in columns}


def detect_named_format(df):
    """
    Returns "ADCB_CHAIN_DAILY", "NBK_MERCHANT_STATEMENT", "ANB_HIVE_POS",
    or None. Runs on the RAW (un-normalized) dataframe -- signatures are
    deliberately specific multi-column combinations so this never
    false-positives against an already-supported format.
    """
    cols = _sig(df.columns)

    if {"AUTHORIZATION", "SALES", "CARD", "TERMINAL", "NET"} <= cols:
        return "ADCB_CHAIN_DAILY"

    if {"AUTHCODE", "TRANS_DATE", "POST_DATE", "TERMINAL_ID"} <= cols:
        return "NBK_MERCHANT_STATEMENT"

    if {"TR_ARF", "AMOUNT", "SCHEME", "LOCALDATE", "BASE_0"} <= cols:
        return "ANB_HIVE_POS"

    return None


# Raw column (ccol-normalized) -> target column name. Target names are
# literal strings already present in core.normalize_pos()'s own synonym
# lists (checked directly against core.py), so core.normalize_pos() reads
# them exactly as it does any already-supported format.
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
        # tr_arf / amount / scheme / localdate / posting_date already match
        # core.py's existing synonym lists verbatim -- no rename needed.
        # total_amount is deliberately left alone too -- see module
        # docstring.
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
    """
    Position-indexed (0..n-1, matching raw_df's own row order) Series of
    Reversal Amount: the row's own Amount value where a status column
    marks it a return, else 0.0. This lines up with core.normalize_pos()'s
    "POS Row" = i+1 numbering on the SAME input dataframe, so it can be
    joined back on afterwards without touching core.py's row-construction.
    """
    cols = {core.ccol(c): c for c in raw_df.columns}
    status_col = next((cols[k] for k in _STATUS_COLUMN_CANDIDATES if k in cols), None)
    amt_col = cols.get("AMOUNT")
    if status_col is None or amt_col is None:
        return pd.Series(0.0, index=raw_df.index)
    is_return = raw_df[status_col].astype(str).str.strip().str.upper().isin(_RETURN_STATUS_VALUES)
    rev = raw_df[amt_col].where(is_return, 0.0)
    return pd.to_numeric(rev, errors="coerce").fillna(0.0)


def normalize_named_pos(df, fmt, source="POS", forced_payment=None):
    """
    df: RAW dataframe (as read from the upload, before core.norm_cols()).
    fmt: one of detect_named_format()'s non-None return values.
    Returns the same output schema as core.normalize_pos(), plus a
    "Reversal Amount" column (0.0 for every row except NBK RETURN rows).
    """
    df = df.reset_index(drop=True)
    renamed = _rename_for_core(df, fmt)
    out = core.normalize_pos(renamed, source=source, forced_payment=forced_payment)
    if out is None or out.empty:
        if out is not None:
            out = out.copy()
            out["Reversal Amount"] = pd.Series(dtype=float)
        return out

    out = out.copy()
    if fmt == "NBK_MERCHANT_STATEMENT":
        rev_by_row = _reversal_amounts(df)
        out["Reversal Amount"] = out["POS Row"].map(lambda r: rev_by_row.get(r - 1, 0.0))
    else:
        out["Reversal Amount"] = 0.0

    return out


def normalize_pos_universal(df, source="POS", forced_payment=None):
    """
    Convenience entry point: detects a named format and uses the
    rename-then-normalize path if matched; otherwise calls
    core.normalize_pos() completely unchanged -- today's behavior for
    every already-supported format is identical, since detect_named_format
    only returns non-None for the three new signatures above.

    Returns (normalized_dataframe, detected_format_or_None).
    """
    fmt = detect_named_format(df)
    if fmt:
        return normalize_named_pos(df, fmt, source, forced_payment), fmt
    return core.normalize_pos(df, source=source, forced_payment=forced_payment), None

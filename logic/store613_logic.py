
"""
Additive Store 613 bridge facade.

Existing Sales Order -> Sales Details -> Receipt/Auth bridge remains in core.py.
New Store 613 logic should extend this module without removing the proven bridge.
"""
from __future__ import annotations
import core

def normalize_sales_details(df, source="D365 Sales Details"):
    return core.normalize_sales_details(df, source)

def enrich_tender(tender, sales_details):
    return core.enrich_store613_from_sales_details(tender, sales_details)

def engine_health():
    return {
        "module":"store613_logic",
        "legacy_function":"core.enrich_store613_from_sales_details",
        "legacy_preserved":True,
        "bridge_key":"Store Code 613 + Sales Order",
        "extension_mode":"wrapper / additive",
    }
"""
Additive Store 613 bridge facade.

Existing Sales Order -> Sales Details -> Receipt/Auth bridge remains in core.py.
New Store 613 logic extends this module without removing the proven bridge.

Confirmed TAP Gateway evidence chain:
    TAP reference_order
        -> D365 Sales Details Receipt ID
        -> D365 Sales Order
        -> SUM(D365 Sales Details Net Amount) x 1.15
        -> TAP gross amount
        -> Store 613 + Sales Order
        -> D365 Store Tender amount

Important:
    - core.py remains unchanged.
    - Existing Store 613 enrichment remains unchanged.
    - Sales Details are item-level, so Net Amount is aggregated by
      Store Code + Receipt ID + Sales Order before TAP gross validation.
"""
from __future__ import annotations

import pandas as pd
import core

from tap_store613_matcher import (
    DEFAULT_AMOUNT_TOLERANCE,
    DEFAULT_PENDING_DAYS,
    match_tap_store613,
    match_tap_store613_dataframes,
)


def normalize_sales_details(df, source="D365 Sales Details"):
    """
    Preserve core.normalize_sales_details() and retain raw D365 Net Amount
    on each normalized Sales Details line.

    The raw line amount is mapped back through the existing "SalesDetails Row"
    audit identifier. No business-key guessing or positional re-keying is used.
    """
    out = core.normalize_sales_details(df, source)

    if out is None:
        return out

    out = out.copy()

    if "Net Amount" not in out.columns:
        out["Net Amount"] = pd.NA

    if df is None or getattr(df, "empty", True) or out.empty:
        return out

    d = core.norm_cols(df)

    net_col = core.find(
        d,
        [
            "net amount",
            "net. amount",
            "net_amount",
            "sales net amount",
            "net sales amount",
            "line net amount",
            "net",
        ],
    )

    if not net_col:
        return out

    net_by_source_row = {}
    for i, r in d.iterrows():
        net_by_source_row[i + 1] = core.amount(r.get(net_col))

    if "SalesDetails Row" in out.columns:
        out["Net Amount"] = out["SalesDetails Row"].map(net_by_source_row)

    return out


def aggregate_sales_details_for_tap(sales_details_df):
    """
    Convert item-level D365 Sales Details into one reconciliation evidence row
    per Store Code + Receipt ID + Sales Order.

    Confirmed Store 613 behavior:
        TAP reference_order matches D365 Receipt ID.
        TAP amount is compared to SUM(Net Amount) for that Receipt/Sales Order
        multiplied by 1.15.

    The source Sales Details DataFrame is not mutated.
    """
    if sales_details_df is None or sales_details_df.empty:
        return pd.DataFrame(
            columns=[
                "Store Code",
                "Receipt ID",
                "Sales Order",
                "Net Amount",
                "SalesDetails Line Count",
                "SalesDetails Source",
            ]
        )

    sd = sales_details_df.copy()

    for c in ("Store Code", "Receipt ID", "Sales Order"):
        if c not in sd.columns:
            sd[c] = ""
        sd[c] = sd[c].fillna("").astype(str).str.strip()

    if "Net Amount" not in sd.columns:
        sd["Net Amount"] = pd.NA
    sd["Net Amount"] = pd.to_numeric(sd["Net Amount"], errors="coerce")

    # A TAP order cannot be proven without a Receipt ID.
    sd = sd[sd["Receipt ID"].ne("")].copy()
    if sd.empty:
        return pd.DataFrame(
            columns=[
                "Store Code",
                "Receipt ID",
                "Sales Order",
                "Net Amount",
                "SalesDetails Line Count",
                "SalesDetails Source",
            ]
        )

    def _join_unique(series):
        vals = []
        for x in series.dropna():
            s = str(x).strip()
            if s and s not in vals:
                vals.append(s)
        return " | ".join(vals)

    agg_spec = {
        "Net Amount": ("Net Amount", "sum"),
        "SalesDetails Line Count": ("Receipt ID", "size"),
    }

    if "SalesDetails Source" in sd.columns:
        agg_spec["SalesDetails Source"] = ("SalesDetails Source", _join_unique)

    grouped = (
        sd.groupby(
            ["Store Code", "Receipt ID", "Sales Order"],
            dropna=False,
            as_index=False,
        )
        .agg(**agg_spec)
    )

    if "SalesDetails Source" not in grouped.columns:
        grouped["SalesDetails Source"] = ""

    grouped["Net Amount"] = pd.to_numeric(
        grouped["Net Amount"], errors="coerce"
    ).round(2)

    return grouped


def enrich_tender(tender, sales_details):
    """
    Preserve the existing Store 613 Sales Order -> Sales Details bridge.
    """
    return core.enrich_store613_from_sales_details(tender, sales_details)


def _decorate_tap_audit_with_sales_order(audit, aggregated_sales):
    """
    Add the Sales Order selected by the Receipt + aggregated Net Amount evidence.

    tap_store613_matcher intentionally remains unchanged. This facade adds the
    cross-source Sales Order needed for the final Store Tender bridge.
    """
    if audit is None or audit.empty:
        return audit

    out = audit.copy()
    out["D365 Sales Order"] = ""
    out["SalesDetails Line Count"] = pd.NA

    if aggregated_sales is None or aggregated_sales.empty:
        return out

    ag = aggregated_sales.copy()
    ag["_RID"] = ag["Receipt ID"].fillna("").astype(str).str.strip().str.upper()
    ag["_NET"] = pd.to_numeric(ag["Net Amount"], errors="coerce").round(2)

    for idx, row in out.iterrows():
        rid = str(row.get("D365 Receipt ID", "") or "").strip().upper()
        net = pd.to_numeric(
            pd.Series([row.get("D365 Net Amount")]), errors="coerce"
        ).iloc[0]

        if not rid:
            continue

        candidates = ag[ag["_RID"].eq(rid)].copy()

        if pd.notna(net):
            candidates = candidates[
                (candidates["_NET"] - float(net)).abs() <= 0.01
            ]

        if len(candidates) == 1:
            c = candidates.iloc[0]
            out.at[idx, "D365 Sales Order"] = str(
                c.get("Sales Order", "")
            ).strip()
            out.at[idx, "SalesDetails Line Count"] = c.get(
                "SalesDetails Line Count", pd.NA
            )

    return out


def match_tap_gateway(
    tap_df,
    sales_details_df,
    *,
    as_of_date=None,
    amount_tolerance=DEFAULT_AMOUNT_TOLERANCE,
    pending_days=DEFAULT_PENDING_DAYS,
):
    """
    Additive TAP Gateway matcher for Store 613 only.

    Sales Details are aggregated BEFORE the existing TAP matcher:
        Receipt ID + Sales Order -> SUM(Net Amount)

    Returned statuses remain:
        MATCHED_TAP_ORDER_GROSS
        REVIEW_TAP_AMOUNT
        PENDING_D365_POSTING
        MISSING_D365
        REVIEW_TAP_REFERENCE
        NOT_APPLICABLE

    Audit output additionally includes:
        D365 Sales Order
        SalesDetails Line Count
    """
    aggregated = aggregate_sales_details_for_tap(sales_details_df)

    audit = match_tap_store613_dataframes(
        tap_df,
        aggregated,
        as_of_date=as_of_date,
        amount_tolerance=amount_tolerance,
        pending_days=pending_days,
    )

    return _decorate_tap_audit_with_sales_order(audit, aggregated)


def match_tap_gateway_records(
    tap_rows,
    sales_detail_rows,
    *,
    as_of_date=None,
    amount_tolerance=DEFAULT_AMOUNT_TOLERANCE,
    pending_days=DEFAULT_PENDING_DAYS,
):
    """
    Non-pandas wrapper.

    For consistent item-level aggregation, records are converted through the
    DataFrame wrapper and returned again as dictionaries.
    """
    tap_df = pd.DataFrame(list(tap_rows or []))
    sales_df = pd.DataFrame(list(sales_detail_rows or []))

    out = match_tap_gateway(
        tap_df,
        sales_df,
        as_of_date=as_of_date,
        amount_tolerance=amount_tolerance,
        pending_days=pending_days,
    )
    return out.to_dict("records")


def engine_health():
    return {
        "module": "store613_logic",
        "legacy_function": "core.enrich_store613_from_sales_details",
        "legacy_preserved": True,
        "bridge_key": "Store Code 613 + Sales Order",
        "extension_mode": "wrapper / additive",
        "sales_details_net_amount_preserved": True,
        "sales_details_net_amount_aggregated": True,
        "tap_store613_enabled": True,
        "tap_match_key": "TAP reference_order -> D365 Receipt ID",
        "tap_amount_rule": "SUM(D365 Net Amount by Receipt/Sales Order) x 1.15",
        "tap_final_tender_bridge": "Store 613 + Sales Order",
        "tap_matcher_module": "tap_store613_matcher",
    }

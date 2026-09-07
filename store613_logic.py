"""
Additive Store 613 bridge facade.

Existing Sales Order -> Sales Details -> Receipt/Auth bridge remains in core.py.
New Store 613 logic extends this module without removing the proven bridge.

TAP Gateway evidence-backed rule:
    TAP reference_order -> D365 Sales Details Receipt ID
    TAP Amount ~= D365 Net Amount * 1.15
"""
from __future__ import annotations

import core

from tap_store613_matcher import (
    DEFAULT_AMOUNT_TOLERANCE,
    DEFAULT_PENDING_DAYS,
    match_tap_store613,
    match_tap_store613_dataframes,
)


def normalize_sales_details(df, source="D365 Sales Details"):
    """
    Preserve the existing Store 613 Sales Details normalization.
    """
    return core.normalize_sales_details(df, source)


def enrich_tender(tender, sales_details):
    """
    Preserve the existing Store 613 Sales Order -> Sales Details bridge.
    """
    return core.enrich_store613_from_sales_details(tender, sales_details)


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

    Confirmed evidence:
        TAP reference_order -> D365 Receipt ID
        Expected TAP gross = D365 Net Amount * 1.15

    This function does not mutate TAP or D365 inputs and does not replace the
    general RetailRecon matching engine.

    Returned statuses:
        MATCHED_TAP_ORDER_GROSS
        REVIEW_TAP_AMOUNT
        PENDING_D365_POSTING
        MISSING_D365
        REVIEW_TAP_REFERENCE
        NOT_APPLICABLE

    NOT_APPLICABLE rows must continue through the legacy/general matching flow.
    """
    return match_tap_store613_dataframes(
        tap_df,
        sales_details_df,
        as_of_date=as_of_date,
        amount_tolerance=amount_tolerance,
        pending_days=pending_days,
    )


def match_tap_gateway_records(
    tap_rows,
    sales_detail_rows,
    *,
    as_of_date=None,
    amount_tolerance=DEFAULT_AMOUNT_TOLERANCE,
    pending_days=DEFAULT_PENDING_DAYS,
):
    """
    Non-pandas wrapper for callers that already work with lists of dictionaries.
    """
    return match_tap_store613(
        tap_rows,
        sales_detail_rows,
        as_of_date=as_of_date,
        amount_tolerance=amount_tolerance,
        pending_days=pending_days,
    )


def engine_health():
    return {
        "module": "store613_logic",
        "legacy_function": "core.enrich_store613_from_sales_details",
        "legacy_preserved": True,
        "bridge_key": "Store Code 613 + Sales Order",
        "extension_mode": "wrapper / additive",
        "tap_store613_enabled": True,
        "tap_match_key": "TAP reference_order -> D365 Receipt ID",
        "tap_amount_rule": "D365 Net Amount x 1.15",
        "tap_matcher_module": "tap_store613_matcher",
    }

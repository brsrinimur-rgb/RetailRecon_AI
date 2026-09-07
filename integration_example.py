"""
Example only: wire the Store 613 TAP matcher into your existing flow
without replacing legacy matching logic.
"""

from tap_store613_matcher import match_tap_store613_dataframes


def apply_tap_store613_rule(tap_df, d365_sales_details_df, run_date):
    result_df = match_tap_store613_dataframes(
        tap_df,
        d365_sales_details_df,
        as_of_date=run_date,
        amount_tolerance=0.02,
        pending_days=2,
    )

    handled_statuses = {
        "MATCHED_TAP_ORDER_GROSS",
        "REVIEW_TAP_AMOUNT",
        "PENDING_D365_POSTING",
        "MISSING_D365",
        "REVIEW_TAP_REFERENCE",
    }

    handled = result_df[result_df["Status"].isin(handled_statuses)].copy()
    return handled

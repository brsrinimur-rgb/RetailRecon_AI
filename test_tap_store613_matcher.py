from datetime import date
from decimal import Decimal

from tap_store613_matcher import match_tap_store613


def test_clean_order_and_vat_gross_match():
    tap = [{
        "Store Code": "613",
        "reference_order": "SO6-1001",
        "Amount": 115.00,
        "Transaction Date": "2026-09-05",
    }]
    d365 = [{
        "Receipt ID": "SO6-1001",
        "Net Amount": 100.00,
    }]

    out = match_tap_store613(
        tap, d365, as_of_date=date(2026, 9, 7)
    )[0]

    assert out["Status"] == "MATCHED_TAP_ORDER_GROSS"
    assert out["Expected TAP Gross"] == 115.00
    assert out["Amount Difference"] == 0.00


def test_order_found_amount_difference_goes_to_review():
    tap = [{
        "Store Code": "613",
        "reference_order": "SO6-1002",
        "Amount": 120.00,
        "Transaction Date": "2026-09-05",
    }]
    d365 = [{
        "Receipt ID": "SO6-1002",
        "Net Amount": 100.00,
    }]

    out = match_tap_store613(
        tap, d365, as_of_date=date(2026, 9, 7)
    )[0]

    assert out["Status"] == "REVIEW_TAP_AMOUNT"
    assert out["Expected TAP Gross"] == 115.00
    assert out["Amount Difference"] == 5.00


def test_recent_order_missing_is_pending_posting():
    tap = [{
        "Store Code": "613",
        "reference_order": "SO6-1003",
        "Amount": 250.00,
        "Transaction Date": "2026-09-06",
    }]

    out = match_tap_store613(
        tap, [], as_of_date=date(2026, 9, 7), pending_days=2
    )[0]

    assert out["Status"] == "PENDING_D365_POSTING"


def test_old_missing_order_is_missing_d365():
    tap = [{
        "Store Code": "613",
        "reference_order": "SO6-1004",
        "Amount": 250.00,
        "Transaction Date": "2026-09-01",
    }]

    out = match_tap_store613(
        tap, [], as_of_date=date(2026, 9, 7), pending_days=2
    )[0]

    assert out["Status"] == "MISSING_D365"


def test_other_store_is_not_consumed_by_store613_rule():
    tap = [{
        "Store Code": "601",
        "reference_order": "SO6-1005",
        "Amount": 115.00,
        "Transaction Date": "2026-09-05",
    }]
    d365 = [{
        "Receipt ID": "SO6-1005",
        "Net Amount": 100.00,
    }]

    out = match_tap_store613(
        tap, d365, as_of_date=date(2026, 9, 7)
    )[0]

    assert out["Status"] == "NOT_APPLICABLE"


def test_rounding_to_two_decimals():
    tap = [{
        "Store Code": "613",
        "reference_order": "SO6-1006",
        "Amount": Decimal("113.84"),
        "Transaction Date": "2026-09-05",
    }]
    d365 = [{
        "Receipt ID": "SO6-1006",
        "Net Amount": Decimal("98.99"),
    }]

    out = match_tap_store613(
        tap, d365, as_of_date=date(2026, 9, 7)
    )[0]

    assert out["Expected TAP Gross"] == 113.84
    assert out["Status"] == "MATCHED_TAP_ORDER_GROSS"

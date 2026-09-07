"""
TAP Gateway Store 613 -> D365 Sales Details matching rule.

Evidence-backed rule:
    TAP reference_order -> D365 Receipt ID
    TAP Amount ~= D365 Net Amount * 1.15

This module is intentionally additive. It does not modify the general
RetailRecon POS matching engine.

Statuses:
    MATCHED_TAP_ORDER_GROSS
    REVIEW_TAP_AMOUNT
    PENDING_D365_POSTING
    MISSING_D365

Default pending window: 2 calendar days.
Default amount tolerance: SAR 0.02.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

VAT_RATE = Decimal("0.15")
VAT_MULTIPLIER = Decimal("1.15")
DEFAULT_AMOUNT_TOLERANCE = Decimal("0.02")
DEFAULT_PENDING_DAYS = 2
STORE_613 = "613"


@dataclass(frozen=True)
class Tap613MatchResult:
    status: str
    store_code: str
    tap_reference_order: str
    d365_receipt_id: str
    tap_amount: Optional[Decimal]
    d365_net_amount: Optional[Decimal]
    expected_tap_gross: Optional[Decimal]
    amount_difference: Optional[Decimal]
    tap_transaction_date: Optional[date]
    rule: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        def money(v: Optional[Decimal]):
            return None if v is None else float(v)

        return {
            "Status": self.status,
            "Store Code": self.store_code,
            "TAP Reference Order": self.tap_reference_order,
            "D365 Receipt ID": self.d365_receipt_id,
            "TAP Amount": money(self.tap_amount),
            "D365 Net Amount": money(self.d365_net_amount),
            "Expected TAP Gross": money(self.expected_tap_gross),
            "Amount Difference": money(self.amount_difference),
            "TAP Transaction Date": (
                self.tap_transaction_date.isoformat()
                if self.tap_transaction_date
                else None
            ),
            "Match Rule": self.rule,
            "Reason": self.reason,
        }


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def _normalise_key(value: Any) -> str:
    # Preserve meaningful letters/numbers but remove harmless surrounding spaces.
    return _clean_text(value).upper()


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = _clean_text(value).replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = _clean_text(value)
    if not text:
        return None

    # Common D365/TAP date formats.
    formats = (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%d-%b-%Y",
        "%d %b %Y",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _get(row: Mapping[str, Any], *names: str) -> Any:
    """
    Case-insensitive, whitespace-tolerant column lookup.
    """
    normalised = {
        str(k).strip().lower().replace("_", " "): v
        for k, v in row.items()
    }
    for name in names:
        key = name.strip().lower().replace("_", " ")
        if key in normalised:
            return normalised[key]
    return None


def _build_d365_receipt_index(
    d365_rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = {}
    for row in d365_rows:
        receipt = _normalise_key(
            _get(
                row,
                "Receipt ID",
                "Receipt Id",
                "Receipt",
                "Receipt Number",
            )
        )
        if receipt:
            index.setdefault(receipt, []).append(row)
    return index


def match_tap_store613(
    tap_rows: Iterable[Mapping[str, Any]],
    d365_sales_rows: Iterable[Mapping[str, Any]],
    *,
    as_of_date: Optional[date] = None,
    amount_tolerance: Decimal | float | str = DEFAULT_AMOUNT_TOLERANCE,
    pending_days: int = DEFAULT_PENDING_DAYS,
) -> list[dict[str, Any]]:
    """
    Match TAP Gateway Store 613 transactions against D365 Sales Details.

    TAP required evidence:
        store = 613
        reference_order
        amount

    D365 required evidence:
        Receipt ID
        Net Amount

    Clean match:
        reference_order == Receipt ID
        round(Net Amount * 1.15, 2) ~= TAP Amount

    Rows outside Store 613 are returned as NOT_APPLICABLE so callers can pass
    them onward to legacy matching logic unchanged.
    """

    tolerance = Decimal(str(amount_tolerance))
    today = as_of_date or date.today()
    d365_index = _build_d365_receipt_index(d365_sales_rows)
    results: list[dict[str, Any]] = []

    for tap in tap_rows:
        store = _clean_text(
            _get(tap, "Store Code", "Store", "store_code")
        )

        order = _normalise_key(
            _get(
                tap,
                "reference_order",
                "Reference Order",
                "Order No",
                "Order Number",
                "Order",
            )
        )

        tap_amount = _to_decimal(
            _get(
                tap,
                "Amount",
                "TAP Amount",
                "Transaction Amount",
                "Gross Amount",
            )
        )

        tap_date = _to_date(
            _get(
                tap,
                "Transaction Date",
                "Date",
                "Created At",
                "Creation Date",
                "Payment Date",
            )
        )

        if store != STORE_613:
            result = Tap613MatchResult(
                status="NOT_APPLICABLE",
                store_code=store,
                tap_reference_order=order,
                d365_receipt_id="",
                tap_amount=tap_amount,
                d365_net_amount=None,
                expected_tap_gross=None,
                amount_difference=None,
                tap_transaction_date=tap_date,
                rule="TAP Store 613 rule not applied",
                reason="Transaction is not Store 613.",
            )
            results.append(result.as_dict())
            continue

        if not order:
            result = Tap613MatchResult(
                status="REVIEW_TAP_REFERENCE",
                store_code=store,
                tap_reference_order="",
                d365_receipt_id="",
                tap_amount=tap_amount,
                d365_net_amount=None,
                expected_tap_gross=None,
                amount_difference=None,
                tap_transaction_date=tap_date,
                rule="TAP reference_order -> D365 Receipt ID",
                reason="TAP reference_order is blank.",
            )
            results.append(result.as_dict())
            continue

        candidates = d365_index.get(order, [])

        if not candidates:
            age_days = None
            if tap_date:
                age_days = (today - tap_date).days

            if age_days is not None and age_days <= pending_days:
                status = "PENDING_D365_POSTING"
                reason = (
                    f"Order {order} not yet found in D365; "
                    f"transaction age is {age_days} day(s), within "
                    f"the {pending_days}-day posting window."
                )
            else:
                status = "MISSING_D365"
                if age_days is None:
                    reason = (
                        f"Order {order} not found in D365 and transaction "
                        "date is unavailable for timing-window validation."
                    )
                else:
                    reason = (
                        f"Order {order} not found in D365 and is "
                        f"{age_days} day(s) old, outside the "
                        f"{pending_days}-day posting window."
                    )

            result = Tap613MatchResult(
                status=status,
                store_code=store,
                tap_reference_order=order,
                d365_receipt_id="",
                tap_amount=tap_amount,
                d365_net_amount=None,
                expected_tap_gross=None,
                amount_difference=None,
                tap_transaction_date=tap_date,
                rule="TAP reference_order -> D365 Receipt ID",
                reason=reason,
            )
            results.append(result.as_dict())
            continue

        # If duplicate D365 receipts exist, find the candidate whose VAT-adjusted
        # gross is closest to the TAP amount. Do not silently collapse evidence.
        best = None
        best_diff = None

        for candidate in candidates:
            net = _to_decimal(
                _get(
                    candidate,
                    "Net Amount",
                    "D365 Net Amount",
                    "NetAmount",
                    "Sales Net Amount",
                )
            )
            if net is None or tap_amount is None:
                diff = None
            else:
                expected = _money(net * VAT_MULTIPLIER)
                diff = abs(_money(tap_amount) - expected)

            rank = Decimal("999999999") if diff is None else diff
            if best is None or rank < best_diff:
                best = candidate
                best_diff = rank

        receipt = _normalise_key(
            _get(best, "Receipt ID", "Receipt Id", "Receipt", "Receipt Number")
        )
        net_amount = _to_decimal(
            _get(
                best,
                "Net Amount",
                "D365 Net Amount",
                "NetAmount",
                "Sales Net Amount",
            )
        )

        if tap_amount is None or net_amount is None:
            result = Tap613MatchResult(
                status="REVIEW_TAP_AMOUNT",
                store_code=store,
                tap_reference_order=order,
                d365_receipt_id=receipt,
                tap_amount=tap_amount,
                d365_net_amount=net_amount,
                expected_tap_gross=None,
                amount_difference=None,
                tap_transaction_date=tap_date,
                rule="Order match; gross = D365 Net Amount x 1.15",
                reason="Order matched, but one of the amount fields is missing/invalid.",
            )
            results.append(result.as_dict())
            continue

        expected_gross = _money(net_amount * VAT_MULTIPLIER)
        difference = abs(_money(tap_amount) - expected_gross)

        if difference <= tolerance:
            status = "MATCHED_TAP_ORDER_GROSS"
            reason = (
                "TAP reference_order matched D365 Receipt ID and "
                "TAP Amount matched D365 Net Amount + 15% VAT."
            )
        else:
            status = "REVIEW_TAP_AMOUNT"
            reason = (
                "Order matched, but TAP Amount differs from "
                "D365 Net Amount + 15% VAT."
            )

        result = Tap613MatchResult(
            status=status,
            store_code=store,
            tap_reference_order=order,
            d365_receipt_id=receipt,
            tap_amount=_money(tap_amount),
            d365_net_amount=_money(net_amount),
            expected_tap_gross=expected_gross,
            amount_difference=difference,
            tap_transaction_date=tap_date,
            rule="TAP reference_order -> D365 Receipt ID; D365 Net x 1.15",
            reason=reason,
        )
        results.append(result.as_dict())

    return results


def match_tap_store613_dataframes(
    tap_df,
    d365_sales_df,
    *,
    as_of_date=None,
    amount_tolerance=DEFAULT_AMOUNT_TOLERANCE,
    pending_days=DEFAULT_PENDING_DAYS,
):
    """
    Pandas convenience wrapper.

    Returns a new DataFrame; does not mutate either input DataFrame.
    """
    import pandas as pd

    tap_rows = tap_df.to_dict("records") if tap_df is not None else []
    d365_rows = (
        d365_sales_df.to_dict("records")
        if d365_sales_df is not None
        else []
    )

    return pd.DataFrame(
        match_tap_store613(
            tap_rows,
            d365_rows,
            as_of_date=as_of_date,
            amount_tolerance=amount_tolerance,
            pending_days=pending_days,
        )
    )

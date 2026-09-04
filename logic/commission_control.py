from __future__ import annotations

import numpy as np
import pandas as pd


ALIASES = {
    "MASTER": "MASTERCARD",
    "MASTER CARD": "MASTERCARD",
    "MC": "MASTERCARD",
    "VC": "VISA",
    "P": "MADA",
    "P1": "MADA",
    "AX": "AMEX",
    "GCCNET": "GCC NET",
    "GCC_NET": "GCC NET",
    "GCC-NET": "GCC NET",
}


def norm_payment(value):
    p = str(value or "").strip().upper()
    return ALIASES.get(p, p)


def prepare_rate_master(master: pd.DataFrame) -> pd.DataFrame:
    """Normalize the editable Commission Rate Master exactly once."""
    if master is None or master.empty:
        return pd.DataFrame(
            columns=[
                "Payment Type",
                "Commission Rate %",
                "VAT Rate %",
                "Validation Method",
                "Active",
            ]
        )

    out = master.copy()

    for c in [
        "Payment Type",
        "Commission Rate %",
        "VAT Rate %",
        "Validation Method",
        "Active",
    ]:
        if c not in out.columns:
            out[c] = np.nan

    out["Payment Type"] = out["Payment Type"].map(norm_payment)
    out["Active"] = out["Active"].astype(str).str.strip().str.upper()
    out = out[out["Active"].isin(["YES", "Y", "TRUE", "1"])].copy()

    out["Commission Rate %"] = pd.to_numeric(
        out["Commission Rate %"], errors="coerce"
    )
    out["VAT Rate %"] = pd.to_numeric(
        out["VAT Rate %"], errors="coerce"
    ).fillna(15.0)

    out["Validation Method"] = (
        out["Validation Method"]
        .fillna("RATE_NOT_CONFIGURED")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    return out


def validate_commission_transactions(
    transactions: pd.DataFrame,
    master: pd.DataFrame,
    payment_col: str = "Payment Type",
    amount_col: str = "POS Amount",
    commission_col: str = "Commission",
    vat_col: str = "VAT",
    tolerance: float = 0.05,
) -> pd.DataFrame:
    """
    Shared V46B commission/VAT control.

    Rules are the production Commission Validation rules:
      * CONTRACT_RATE -> expected commission = abs(POS amount) * rate %
      * expected VAT = expected commission * VAT rate %
      * PROVIDER_ACTUAL -> contract-rate expectation stays blank
      * variance = actual - expected
      * +/- SAR 0.05 -> OK
    """
    if transactions is None:
        transactions = pd.DataFrame()

    out = transactions.copy()

    for c, default in [
        (payment_col, ""),
        (amount_col, 0.0),
        (commission_col, 0.0),
        (vat_col, 0.0),
    ]:
        if c not in out.columns:
            out[c] = default

    prepared = prepare_rate_master(master)

    rate_map = (
        prepared.set_index("Payment Type")["Commission Rate %"].to_dict()
        if not prepared.empty
        else {}
    )
    vat_map = (
        prepared.set_index("Payment Type")["VAT Rate %"].to_dict()
        if not prepared.empty
        else {}
    )
    method_map = (
        prepared.set_index("Payment Type")["Validation Method"].to_dict()
        if not prepared.empty
        else {}
    )

    out["Payment Type"] = out[payment_col].map(norm_payment)
    out["Contract Rate %"] = out["Payment Type"].map(rate_map)
    out["VAT Rate %"] = out["Payment Type"].map(vat_map).fillna(15.0)
    out["Validation Method"] = (
        out["Payment Type"].map(method_map).fillna("RATE_NOT_CONFIGURED")
    )

    pos_amount = pd.to_numeric(out[amount_col], errors="coerce").fillna(0.0)
    out["Actual Commission"] = pd.to_numeric(
        out[commission_col], errors="coerce"
    ).fillna(0.0).round(2)
    out["Actual VAT"] = pd.to_numeric(
        out[vat_col], errors="coerce"
    ).fillna(0.0).round(2)

    def _expected_commission(row):
        method = str(row["Validation Method"]).upper()
        rate = row["Contract Rate %"]

        if method == "CONTRACT_RATE" and pd.notna(rate):
            return round(abs(float(row["_POS_AMOUNT_FOR_CONTROL"])) * float(rate) / 100.0, 2)

        # Provider actual mode deliberately has no invented expected contract fee.
        return np.nan

    out["_POS_AMOUNT_FOR_CONTROL"] = pos_amount
    out["Expected Commission"] = out.apply(_expected_commission, axis=1)
    out["Expected VAT"] = (
        out["Expected Commission"] * out["VAT Rate %"] / 100.0
    ).round(2)

    out["Commission Variance"] = (
        out["Actual Commission"] - out["Expected Commission"]
    ).round(2)
    out["VAT Variance"] = (
        out["Actual VAT"] - out["Expected VAT"]
    ).round(2)

    def _status(row):
        method = str(row["Validation Method"]).upper()

        if method == "PROVIDER_ACTUAL":
            return "CONTRACT RATE PENDING"

        if pd.isna(row["Expected Commission"]):
            return "RATE NOT CONFIGURED"

        commission_variance = float(row["Commission Variance"])
        vat_variance = (
            float(row["VAT Variance"])
            if pd.notna(row["VAT Variance"])
            else 0.0
        )

        if (
            float(row["Actual Commission"]) == 0.0
            and float(row["Expected Commission"]) > tolerance
        ):
            return "SOURCE COMMISSION MISSING"

        if (
            float(row["Actual VAT"]) == 0.0
            and pd.notna(row["Expected VAT"])
            and float(row["Expected VAT"]) > tolerance
        ):
            return "SOURCE VAT MISSING"

        if abs(commission_variance) > tolerance:
            return "COMMISSION VARIANCE — REVIEW"

        if abs(vat_variance) > tolerance:
            return "VAT VARIANCE"

        return "OK"

    out["Control Status"] = out.apply(_status, axis=1)
    # Backward-compatible name used by the existing Commission Validation page.
    out["Commission Status"] = out["Control Status"]

    out["Expected Net Amount"] = (
        pos_amount.abs()
        - out["Expected Commission"].fillna(0.0)
        - out["Expected VAT"].fillna(0.0)
    ).round(2)
    out.loc[out["Expected Commission"].isna(), "Expected Net Amount"] = np.nan

    return out.drop(columns=["_POS_AMOUNT_FOR_CONTROL"], errors="ignore")

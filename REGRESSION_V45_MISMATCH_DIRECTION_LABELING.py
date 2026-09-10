"""
REGRESSION_V45_MISMATCH_DIRECTION_LABELING.py

Purpose: verify the new excess/shortfall diagnostic labeling added to
logic/bank_settlement_extension.py (V-fix, 2026-09-10), requested directly
by the user in response to their real "excess amount received in the bank"
question:

    "i need something better options amount in bank i can't keep open the
    recon file mangement will not accept this logice"
    "Not sure -- I'd rather see it flagged first before deciding"

Scope, exactly as authorized: purely additive diagnostic flagging only.
This test asserts BOTH that the new labeling appears correctly, AND that
Settlement Status / Bank Settled classification behavior is completely
unchanged from before the fix (no auto-split, no new eligibility path).

Covers:
  1. reconcile_card_batches_advanced() (ANB card batches) -- excess case.
  2. reconcile_card_batches_advanced() -- shortfall case.
  3. reconcile_card_batches_advanced() -- exact match still BANK RECEIVED,
     with no mismatch labeling (proves classification is unchanged).
  4. reconcile_provider_batches_to_rajhi() (TABBY/TAMARA/TAP payouts) --
     excess case (this function previously had NO reason text at all here).
  5. reconcile_provider_batches_to_rajhi() -- shortfall case.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from logic import bank_settlement_extension as bank_ext

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

# ---------------------------------------------------------------------
# 1 & 2 & 3: reconcile_card_batches_advanced (ANB)
# ---------------------------------------------------------------------
card_batches = pd.DataFrame([
    {  # excess: bank sent MORE than POS batch expects
        "Provider": "ANB POS", "Store Code": "601", "Terminal ID": "T1",
        "Payment Type": "MADA", "Settlement Date": "2026-08-01",
        "Gross Amount": 150.00, "Transaction Count": 3,
    },
    {  # shortfall: bank sent LESS than POS batch expects
        "Provider": "ANB POS", "Store Code": "602", "Terminal ID": "T2",
        "Payment Type": "VISA", "Settlement Date": "2026-08-01",
        "Gross Amount": 500.00, "Transaction Count": 2,
    },
    {  # exact match -- must remain BANK RECEIVED, no mismatch label
        "Provider": "ANB POS", "Store Code": "603", "Terminal ID": "T3",
        "Payment Type": "MADA", "Settlement Date": "2026-08-01",
        "Gross Amount": 300.00, "Transaction Count": 4,
    },
])
bank = pd.DataFrame([
    {"Bank": "ANB", "Bank Date": "2026-08-02", "Credit": 384.00, "Bank Amount": 384.00,
     "Narration Terminal ID": "T1", "Narration Scheme": "MADA", "Narration Transaction Count": 3,
     "Description": "ANB SETTLE T1"},
    {"Bank": "ANB", "Bank Date": "2026-08-02", "Credit": 420.00, "Bank Amount": 420.00,
     "Narration Terminal ID": "T2", "Narration Scheme": "VISA", "Narration Transaction Count": 2,
     "Description": "ANB SETTLE T2"},
    {"Bank": "ANB", "Bank Date": "2026-08-02", "Credit": 300.00, "Bank Amount": 300.00,
     "Narration Terminal ID": "T3", "Narration Scheme": "MADA", "Narration Transaction Count": 4,
     "Description": "ANB SETTLE T3"},
])

res, _ = bank_ext.reconcile_card_batches_advanced(card_batches, bank, tolerance=1.0)
res = res.set_index("Terminal ID")

_assert(res.loc["T1", "Settlement Status"] == "BANK REVIEW REQUIRED", "T1 (excess) stays BANK REVIEW REQUIRED -- classification unchanged")
_assert(res.loc["T1", "Mismatch Direction"] == "EXCESS RECEIVED", "T1 labeled EXCESS RECEIVED")
_assert(abs(res.loc["T1", "Closest Bank Candidate Amount"] - 384.00) < 0.01, "T1 closest candidate amount recorded correctly")
_assert("MORE than" in res.loc["T1", "Settlement Review Reason"], "T1 reason text explicitly says MORE than expected")

_assert(res.loc["T2", "Settlement Status"] == "BANK REVIEW REQUIRED", "T2 (shortfall) stays BANK REVIEW REQUIRED -- classification unchanged")
_assert(res.loc["T2", "Mismatch Direction"] == "SHORTFALL", "T2 labeled SHORTFALL")
_assert("LESS than" in res.loc["T2", "Settlement Review Reason"], "T2 reason text explicitly says LESS than expected")

_assert(res.loc["T3", "Settlement Status"] == "BANK RECEIVED", "T3 (exact) still classifies as BANK RECEIVED -- unchanged")
_assert(res.loc["T3", "Mismatch Direction"] == "", "T3 has no mismatch label (exact match, nothing to flag)")
_assert(pd.isna(res.loc["T3", "Closest Bank Candidate Amount"]), "T3 has no closest-candidate value (not applicable on an exact match)")

# ---------------------------------------------------------------------
# 4 & 5: reconcile_provider_batches_to_rajhi (TABBY/TAMARA/TAP)
# ---------------------------------------------------------------------
provider_batches = pd.DataFrame([
    {  # excess
        "Provider": "TAMARA", "Store Code": "601", "Settlement Date": "2026-08-01",
        "Expected Bank Amount": 1000.00,
    },
    {  # shortfall
        "Provider": "TAP", "Store Code": "602", "Settlement Date": "2026-08-01",
        "Expected Bank Amount": 2000.00,
    },
])
prov_bank = pd.DataFrame([
    {"Bank": "AL RAJHI", "Provider": "TAMARA", "Bank Date": "2026-08-05", "Credit": 1250.00,
     "Bank Amount": 1250.00, "Description": "TAMARA PAYOUT", "Bank Source File": "rajhi.xlsx"},
    {"Bank": "AL RAJHI", "Provider": "TAP", "Bank Date": "2026-08-05", "Credit": 1700.00,
     "Bank Amount": 1700.00, "Description": "TAP PAYOUT", "Bank Source File": "rajhi.xlsx"},
])

pres, _ = bank_ext.reconcile_provider_batches_to_rajhi(provider_batches, prov_bank, tolerance=1.0)
pres = pres.set_index("Provider")

_assert(pres.loc["TAMARA", "Settlement Status"] == "BANK REVIEW REQUIRED", "TAMARA (excess) is BANK REVIEW REQUIRED -- classification unchanged")
_assert(pres.loc["TAMARA", "Mismatch Direction"] == "EXCESS RECEIVED", "TAMARA labeled EXCESS RECEIVED")
_assert(pres.loc["TAMARA", "Settlement Review Reason"] != "", "TAMARA now has non-empty reason text (previously blank in this branch)")
_assert("MORE than" in pres.loc["TAMARA", "Settlement Review Reason"], "TAMARA reason text explicitly says MORE than expected")

_assert(pres.loc["TAP", "Settlement Status"] == "BANK REVIEW REQUIRED", "TAP (shortfall) is BANK REVIEW REQUIRED -- classification unchanged")
_assert(pres.loc["TAP", "Mismatch Direction"] == "SHORTFALL", "TAP labeled SHORTFALL")
_assert(pres.loc["TAP", "Settlement Review Reason"] != "", "TAP now has non-empty reason text (previously blank in this branch)")
_assert("LESS than" in pres.loc["TAP", "Settlement Review Reason"], "TAP reason text explicitly says LESS than expected")

print("\nREGRESSION V45 MISMATCH DIRECTION LABELING PASS")

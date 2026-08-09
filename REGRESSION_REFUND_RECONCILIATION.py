from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("core_t", root / "core.py")
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
spec2 = importlib.util.spec_from_file_location("bsv_t", root / "bank_settlement_final.py")
bsv = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(bsv)

refund_df = pd.DataFrame([
    {"Store Code": "601", "Date": "2026-07-10", "Amount": -150.0, "Auth Code": "075304", "Payment Type": "MASTERCARD"},
    {"Store Code": "601", "Date": "2026-07-11", "Amount": -999.0, "Auth Code": "", "Payment Type": "MADA"},
])
refunds = core.normalize_refunds(refund_df, source="refunds.xlsx")
assert len(refunds) == 2
assert round(refunds.iloc[0]["Refund Amount"], 2) == 150.0  # sign discarded, magnitude kept

matched_sales = pd.DataFrame([
    {"Store Code": "601", "Date": pd.Timestamp("2026-07-06"), "Auth Code": "075304",
     "Payment Type": "MASTERCARD", "POS Amount": 150.0},
])

# A refund with no proof against a real sale must be an exception, never silently accepted.
result = core.reconcile_refunds(refunds, matched_sales)
assert result.iloc[0]["Status"] == "Matched"
assert result.iloc[0]["Match Rule"] == "Original Reference + Amount"
assert result.iloc[1]["Status"] == "Exception"
assert result.iloc[1]["Exception"] == "Refund Without Matching Sale"

# No sales table at all -> every refund is an exception, not a false pass.
result_empty = core.reconcile_refunds(refunds, pd.DataFrame())
assert (result_empty["Status"] == "Exception").all()

# Bank-debit verification only applies to already-proven ("Matched") refunds.
bankfile = pd.DataFrame({"Date": ["2026-07-12"], "Description": ["REFUND DEBIT"], "Amount": [-150.0]})
bank = core.normalize_bank(bankfile, "Test Bank")
out = bsv.verify_refund_bank_settlement(result, bank, tolerance=1.0)
assert bool(out.iloc[0]["Bank Settled"])
assert not bool(out.iloc[1]["Bank Settled"])  # exception rows are never bank-matched

print("REFUND RECONCILIATION TEST PASS")

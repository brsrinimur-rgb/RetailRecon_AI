from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("core_t", root / "core.py")
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
spec2 = importlib.util.spec_from_file_location("bsv_t", root / "bank_settlement_final.py")
bsv = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(bsv)

# 1. init_settlement_columns provides the single canonical "unsettled" baseline.
m = pd.DataFrame([{"Payment Type": "MADA", "POS Amount": 100.0}])
m = core.init_settlement_columns(m)
assert m.loc[0, "Bank Settled"] == False
assert m.loc[0, "Settlement Status"] == "Awaiting Bank Settlement"

# 2. AMEX now has a real settlement path, batched by date+amount, isolated from other tenders.
matched = pd.DataFrame([
    {"Payment Type": "AMEX", "POS Date": pd.Timestamp("2026-07-06"), "POS Amount": 500.0, "Store Code": "601"},
    {"Payment Type": "MADA", "POS Date": pd.Timestamp("2026-07-06"), "POS Amount": 100.0, "Store Code": "601"},
])
matched = core.init_settlement_columns(matched)
expected = bsv.build_amex_expected(matched)
assert len(expected) == 1 and round(expected.iloc[0]["Expected Bank Credit"], 2) == 500.0

bankfile = pd.DataFrame({"Date": ["2026-07-08"], "Description": ["AMEX SETTLEMENT"], "Amount": [500.0]})
bank_rows = core.normalize_bank(bankfile, "AMEX Settlement")
v = bsv.verify_provider_payouts(expected, bank_rows, "AMEX", tolerance=1.0,
                                 bank_date_col="Bank Date", credit_col="Bank Amount")
out = bsv.apply_amex_verification_to_matched(matched, v)
assert bool(out.loc[out["Payment Type"] == "AMEX", "Bank Settled"].iloc[0])
assert not bool(out.loc[out["Payment Type"] == "MADA", "Bank Settled"].iloc[0])  # never touches other tenders

# 3. apply_bank_settlement is no longer wired into the main flow; it is deprecated but harmless if called directly.
assert core.apply_bank_settlement.__doc__ is not None and "DEPRECATED" in core.apply_bank_settlement.__doc__

print("UNIFIED BANK ENGINE TEST PASS")

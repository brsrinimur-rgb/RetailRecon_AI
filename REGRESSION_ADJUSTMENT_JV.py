from pathlib import Path
import importlib.util, os
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("db_t", root / "db.py")
db = importlib.util.module_from_spec(spec); spec.loader.exec_module(db)
spec2 = importlib.util.spec_from_file_location("core_t", root / "core.py")
core = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(core)

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

gl_config = db.load_gl_config()
ctrl = db.load_accounting_period_control("ULC")

# Positive amount = late/missing sale: Debit Bank/Commission/VAT, Credit Sale, and it balances.
j = core.create_adjustment_jv("601", "MADA", 750.0, "Late file after close",
                               gl=gl_config, commission_master=db.load_commission_rate_master(),
                               accounting_date="2026-08-01", period_control=ctrl, batch_seq=1,
                               source_date="2026-07-30")
assert not j.empty
j = core.validate_jv(j, gl_config)
assert bool(j["Validation Passed"].all())
debit = pd.to_numeric(j["Debit"], errors="coerce").sum()
credit = pd.to_numeric(j["Credit"], errors="coerce").sum()
assert round(debit - credit, 2) == 0.0
sale_line = j[j["Main Account"] == gl_config["CC_GL"]].iloc[0]
assert sale_line["Credit"] == 750.0 and sale_line["Debit"] == 0.0

# Negative amount = reversal: every line flips side, still balances, same accounts.
jr = core.create_adjustment_jv("601", "MADA", -750.0, "Reverse prior overstated entry",
                                gl=gl_config, commission_master=db.load_commission_rate_master(),
                                accounting_date="2026-08-01", period_control=ctrl, batch_seq=2,
                                source_date="2026-07-30")
jr = core.validate_jv(jr, gl_config)
assert bool(jr["Validation Passed"].all())
sale_line_r = jr[jr["Main Account"] == gl_config["CC_GL"]].iloc[0]
assert sale_line_r["Debit"] == 750.0 and sale_line_r["Credit"] == 0.0

# Unknown store display name -> refuses to guess, returns empty rather than an unpostable JV.
j_bad = core.create_adjustment_jv("999999", "MADA", 100.0, "reason",
                                   gl=gl_config, commission_master=db.load_commission_rate_master(),
                                   accounting_date="2026-08-01", period_control=ctrl)
assert j_bad.empty

# db.record_adjustment_jv saves to the SAME shared jv_batches table used by the normal JV flow,
# so it goes through the identical approval/posting pipeline.
batch = db.record_adjustment_jv("601", "MADA", 750.0, "Late file after close", "tester", j,
                                 accounting_date="2026-08-01")
jv = db.load_jv()
assert batch in set(jv["Journal Batch"])
adj = db.load_adjustments()
assert (adj["JV Batch"] == batch).any()

db.update_jv_approval([batch], "APPROVED")
db.update_jv_posting(batch, "V-ADJ-TEST")
jv2 = db.load_jv()
row = jv2[jv2["Journal Batch"] == batch].iloc[0]
assert row["Approval Status"] == "APPROVED"
assert row["D365 Status"] == "POSTED"

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
print("ADJUSTMENT JV TEST PASS")

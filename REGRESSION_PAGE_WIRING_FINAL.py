from pathlib import Path
import ast
root=Path(__file__).resolve().parent

pos=(root/"pages"/"1_POS_Reconciliation.py").read_text(encoding="utf-8")
assert "from logic import bank_settlement_extension as bank_ext" in pos
assert "payout_sheets=set()" in pos
assert "classify_settlement_source" in pos
assert "link_tabby_payout_underlying_ids" in pos
assert "build_settlement_carry_forward" in pos
assert "save_reconciliation_run" in pos

settle=(root/"pages"/"18_Settlement_Batch_Engine.py").read_text(encoding="utf-8")
assert "link_tabby_payout_underlying_ids" in settle
assert "reconcile_card_batches_advanced" in settle

jv=(root/"pages"/"24_JV_Creation.py").read_text(encoding="utf-8")
assert jv.find("### JV Basis & Provider Grouping") < jv.find("# JV Eligibility Breakdown")
assert "_Received_By_Period_End" in jv
assert "grouping_map=_current_map" in jv
assert "active_payment_types=_active_providers" in jv

assert (root/"pages"/"33_Settlement_Carry_Forward.py").exists()
assert (root/"pages"/"34_Reconciliation_Run_History.py").exists()
print("FINAL PAGE WIRING PASS")

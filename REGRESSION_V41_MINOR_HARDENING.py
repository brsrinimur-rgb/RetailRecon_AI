"""
REGRESSION_V41_MINOR_HARDENING.py

Two small, real, non-speculative fixes found while re-reviewing the source
for open items (no new external evidence needed for either):

1. reconcile_card_batches_to_anb() filtered on raw bank-label equality
   ("Bank" == "ANB" exactly), unlike the live reconcile_card_batches_advanced()
   which already canonicalizes via _canonical_bank(). Not called from any
   live page (confirmed by grep -- only regression tests call it directly),
   so not a live production bug, but a real trap. Fixed to canonicalize
   identically to the live matcher.

2. release_guard.py's REQUIRED_LEGACY_FILES was missing
   logic/bank_settlement_extension.py, pages/18_Settlement_Batch_Engine.py,
   and pages/14_Store_Mapping_Master.py -- flagged as a gap in the V26
   review and never actually fixed until now.

Run: python3 REGRESSION_V41_MINOR_HARDENING.py
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_v41",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v41"]=core; sp.loader.exec_module(core)
from logic import bank_settlement_extension as bank_ext

batch=pd.DataFrame([{
    "Settlement Source":"ANB POS","Settlement Batch ID":"B1","Provider":"ANB POS",
    "Store Code":"601","Terminal ID":"55610694","Payment Type":"MADA",
    "Settlement Date":pd.Timestamp("2026-07-07"),
    "Gross Amount":1000.0,"Expected Bank Amount":1000.0,"Transaction Count":1,
}])
bank_legacy_label=pd.DataFrame([{
    "Bank":"ANB Bank",
    "Bank Date":pd.Timestamp("2026-07-08"),"Bank Amount":1000.0,"Credit":1000.0,
    "Description":"X","Narration Terminal ID":"55610694","Narration Scheme":"MADA",
    "Narration Source Date":pd.Timestamp("2026-07-07"),"Narration Transaction Count":1,
}])

res,_=bank_ext.reconcile_card_batches_to_anb(batch,bank_legacy_label,1.0)
assert len(res)==1
assert res.iloc[0]["Settlement Status"]=="BANK RECEIVED", (
    f"reconcile_card_batches_to_anb must recognize 'ANB Bank', got {res.iloc[0].to_dict()}"
)
print("[PASS] reconcile_card_batches_to_anb() now canonicalizes 'ANB Bank' -> 'ANB'.")

bank_wrong_bank=bank_legacy_label.copy()
bank_wrong_bank["Bank"]="AL RAJHI"
res2,_=bank_ext.reconcile_card_batches_to_anb(batch,bank_wrong_bank,1.0)
assert res2.iloc[0]["Settlement Status"]!="BANK RECEIVED"
print("[PASS] A genuinely different bank (AL RAJHI) is still correctly excluded.")

from logic.release_guard import REQUIRED_LEGACY_FILES, run_release_health

for expected in [
    "logic/bank_settlement_extension.py",
    "pages/18_Settlement_Batch_Engine.py",
    "pages/14_Store_Mapping_Master.py",
]:
    assert expected in REQUIRED_LEGACY_FILES, f"{expected} missing from REQUIRED_LEGACY_FILES"
print("[PASS] release_guard.py's required-file list now includes bank_settlement_extension.py "
      "and the two central pages.")

health=run_release_health()
assert health["Healthy"] is True, health
files_by_name={f["File"]:f for f in health["Files"]}
for expected in ["logic/bank_settlement_extension.py","pages/18_Settlement_Batch_Engine.py","pages/14_Store_Mapping_Master.py"]:
    assert files_by_name[expected]["Exists"] is True, f"{expected} reported missing"
print("[PASS] System Logic Health reports all newly-required files present, overall HEALTHY.")

print("REGRESSION V41 MINOR HARDENING PASS")

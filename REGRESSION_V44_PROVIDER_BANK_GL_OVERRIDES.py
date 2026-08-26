"""
V44 provider-specific Bank GL regression.

Proves:
- existing behavior remains 1015 by default;
- TABBY/TAMARA/TAP can each use an independent Bank GL from GL Configuration;
- CC remains on BANK_ACCOUNT;
- validate_jv() validates against the same group-specific account;
- a wrong bank account is blocked.
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location("core_v44",root/"core.py")
core=importlib.util.module_from_spec(spec); sys.modules["core_v44"]=core; spec.loader.exec_module(core)

cfg=dict(core.D365_JV_DEFAULTS)
assert core._bank_gl_for_group(cfg,"CC")=="1015"
assert core._bank_gl_for_group(cfg,"TABBY")=="1015"
assert core._bank_gl_for_group(cfg,"TAMARA")=="1015"
assert core._bank_gl_for_group(cfg,"TAP")=="1015"
print("[PASS] Backward compatibility: all groups remain on 1015 by default.")

cfg.update({
    "TABBY_BANK_ACCOUNT":"2015",
    "TAMARA_BANK_ACCOUNT":"3015",
    "TAP_BANK_ACCOUNT":"4015",
})
assert core._bank_gl_for_group(cfg,"TABBY")=="2015"
assert core._bank_gl_for_group(cfg,"TAMARA")=="3015"
assert core._bank_gl_for_group(cfg,"TAP")=="4015"
assert core._bank_gl_for_group(cfg,"CC")=="1015"
print("[PASS] Provider-specific Bank GL overrides resolve independently; CC remains on BANK_ACCOUNT.")

# Minimal hand-built JV batches to exercise validate_jv independently.
def batch(group, bank_acct, sale_acct):
    return pd.DataFrame([
        {"Journal Batch":f"B-{group}","Store Code":"601","Group":group,
         "Company accounts":"ULC","Currency":"SAR","Account type":"Bank",
         "Main Account":bank_acct,"Ledger Dimension":bank_acct,"Debit":90.0,"Credit":0.0},
        {"Journal Batch":f"B-{group}","Store Code":"601","Group":group,
         "Company accounts":"ULC","Currency":"SAR","Account type":"Ledger",
         "Main Account":"7231","Ledger Dimension":"7231-601--Sale","Debit":8.0,"Credit":0.0},
        {"Journal Batch":f"B-{group}","Store Code":"601","Group":group,
         "Company accounts":"ULC","Currency":"SAR","Account type":"Vendor",
         "Main Account":"P0672","Ledger Dimension":"P0672","Debit":2.0,"Credit":0.0},
        {"Journal Batch":f"B-{group}","Store Code":"601","Group":group,
         "Company accounts":"ULC","Currency":"SAR","Account type":"Ledger",
         "Main Account":sale_acct,"Ledger Dimension":f"{sale_acct}-601---","Debit":0.0,"Credit":100.0},
    ])

sale={"TABBY":"11020913","TAMARA":"11020922","TAP":"11020904"}
for gp,bank_acct in [("TABBY","2015"),("TAMARA","3015"),("TAP","4015")]:
    j=batch(gp,bank_acct,sale[gp])
    v=core.validate_jv(j,cfg)
    assert v["Validation Passed"].all(), v["Validation Errors"].iloc[0]
print("[PASS] validate_jv accepts each provider's configured Bank GL.")

bad=batch("TABBY","1015",sale["TABBY"])
vb=core.validate_jv(bad,cfg)
assert not vb["Validation Passed"].all()
assert "2015" in vb["Validation Errors"].iloc[0]
print("[PASS] validate_jv blocks a TABBY JV using the wrong Bank GL.")

print("REGRESSION V44 PROVIDER BANK GL OVERRIDES PASS")

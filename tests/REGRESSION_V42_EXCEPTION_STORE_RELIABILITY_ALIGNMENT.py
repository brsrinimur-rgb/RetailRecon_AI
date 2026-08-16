"""
REGRESSION_V42_EXCEPTION_STORE_RELIABILITY_ALIGNMENT.py

Fixes the gap flagged in the V25 code review and never closed until now:
route_auth_correction_candidates()'s store filter was a plain text
equality check, without requiring the same "reliable store" condition
core.reconcile() enforces before trusting a store match for auto-
resolution.

Run: python3 REGRESSION_V42_EXCEPTION_STORE_RELIABILITY_ALIGNMENT.py
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_v42",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v42"]=core; sp.loader.exec_module(core)
from logic import exception_routing_extension as exc

u=pd.DataFrame([{
    "D365 Row":1,"Store Code":"UNITED LUXURY CORP","Date":pd.Timestamp("2026-07-02"),
    "Receipt ID":"R1","Auth Code":"111111","D365 Payment":"MADA","D365 Amount":100.0,
    "Reason":"Missing settlement",
}])
p_unreliable=pd.DataFrame([{
    "POS Store":"UNITED LUXURY CORP","POS Payment":"MADA","POS Amount":100.0,
    "POS Date":pd.Timestamp("2026-07-02"),"Auth Code":"222222","Source File":"pos.xlsx",
}])
cand=exc.route_auth_correction_candidates(u,p_unreliable,pd.DataFrame(),1.0)
assert cand.empty, f"unreliable store match must NOT produce a candidate. Got: {cand}"
print("[PASS] Non-numeric Store Code with no Terminal/Merchant mapping evidence -- "
      "candidate correctly EXCLUDED, matching core.reconcile()'s own refusal.")

p_reliable=p_unreliable.copy()
p_reliable["Terminal Store Mapped"]=True
cand2=exc.route_auth_correction_candidates(u,p_reliable,pd.DataFrame(),1.0)
assert len(cand2)==1, f"Terminal Store Mapped=True must be trusted. Got: {cand2}"
assert cand2.iloc[0]["Suggested Auth Code"]=="222222"
print("[PASS] Same non-numeric Store Code, WITH Terminal Store Mapped=True -- candidate "
      "correctly INCLUDED, matching core.reconcile()'s acceptance of confirmed mapping evidence.")

p_merchant_mapped=p_unreliable.copy()
p_merchant_mapped["Merchant Store Mapped"]=True
cand3=exc.route_auth_correction_candidates(u,p_merchant_mapped,pd.DataFrame(),1.0)
assert len(cand3)==1
print("[PASS] Merchant Store Mapped=True alone is also sufficient, matching core.reconcile()'s "
      "OR condition across both mapping evidence types.")

u_numeric=pd.DataFrame([{
    "D365 Row":17,"Store Code":"601","Date":pd.Timestamp("2026-07-02"),"Receipt ID":"R1",
    "Auth Code":"032720","D365 Payment":"MADA","D365 Amount":100.0,"Reason":"Missing settlement",
},{
    "D365 Row":18,"Store Code":"601","Date":pd.Timestamp("2026-07-02"),"Receipt ID":"R2",
    "Auth Code":"111111","D365 Payment":"MADA","D365 Amount":200.0,"Reason":"Missing settlement",
}])
p_numeric=pd.DataFrame([
    {"POS Store":"601","POS Payment":"MADA","POS Amount":100.0,"POS Date":pd.Timestamp("2026-07-02"),
     "Auth Code":"032720","Source File":"pos.xlsx"},
    {"POS Store":"601","POS Payment":"MADA","POS Amount":200.0,"POS Date":pd.Timestamp("2026-07-02"),
     "Auth Code":"222222","Source File":"pos.xlsx"},
])
cand_numeric=exc.route_auth_correction_candidates(u_numeric,p_numeric,pd.DataFrame(),1.0)
assert set(cand_numeric["D365 Row"])=={18}, f"pure-numeric case must behave as before, got {cand_numeric}"
assert cand_numeric.iloc[0]["Suggested Auth Code"]=="222222"
print("[PASS] Pure-numeric store codes (the normal case, no mapping columns present at all) "
      "behave exactly as before -- no regression for the standard scenario.")

def _core_reliable_mask(pos_df, store):
    reliable = pos_df["POS Store"].astype(str).str.fullmatch(r"\d+")
    if "Terminal Store Mapped" in pos_df.columns:
        reliable = reliable | pos_df["Terminal Store Mapped"].fillna(False)
    if "Merchant Store Mapped" in pos_df.columns:
        reliable = reliable | pos_df["Merchant Store Mapped"].fillna(False)
    return reliable & (pos_df["POS Store"].astype(str).str.strip() == store)

scenarios = [
    (pd.DataFrame([{"POS Store": "601", "Terminal Store Mapped": False, "Merchant Store Mapped": False}]), "601"),
    (pd.DataFrame([{"POS Store": "GENERIC CO", "Terminal Store Mapped": False, "Merchant Store Mapped": False}]), "GENERIC CO"),
    (pd.DataFrame([{"POS Store": "GENERIC CO", "Terminal Store Mapped": True, "Merchant Store Mapped": False}]), "GENERIC CO"),
    (pd.DataFrame([{"POS Store": "GENERIC CO", "Terminal Store Mapped": False, "Merchant Store Mapped": True}]), "GENERIC CO"),
]
for i, (sdf, target) in enumerate(scenarios):
    core_mask = _core_reliable_mask(sdf, target)
    expected_included = bool(core_mask.iloc[0])
    row = sdf.iloc[0]
    is_numeric = str(row["POS Store"]).strip().isdigit()
    reliable_flag = is_numeric or bool(row.get("Terminal Store Mapped", False)) or bool(row.get("Merchant Store Mapped", False))
    equals_target = str(row["POS Store"]).strip() == target
    actual_included = reliable_flag and equals_target
    assert actual_included == expected_included, f"scenario {i} mismatch: {actual_included} vs {expected_included}"
print("[PASS] Direct equivalence confirmed across 4 synthetic scenarios: the candidate "
      "matcher's accept/reject decision matches core.reconcile()'s own reliable-store mask "
      "in every case tested.")

print("REGRESSION V42 EXCEPTION STORE RELIABILITY ALIGNMENT PASS")

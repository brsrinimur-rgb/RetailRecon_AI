from pathlib import Path
import importlib.util
import pandas as pd
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_test",root/"core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
base_t={"D365 Row":1,"Store Code":"601","Date":pd.Timestamp("2026-07-06"),"Receipt ID":"R1","Auth Code":"075304","D365 Payment":"MASTERCARD","D365 Amount":1260.00,"D365 Duplicate":False,"Unique Transaction ID":"U1"}
base_p={"POS Row":1,"Source File":"pos.xlsx","POS Store":"601","POS Date":pd.Timestamp("2026-07-06"),"Posting Date":pd.Timestamp("2026-07-07"),"Auth Code":"","POS Payment":"MASTERCARD","POS Amount":1260.00,"Net Amount":1240.00,"Commission":17.39,"VAT":2.61,"Terminal ID":"55610703","POS Duplicate":False,"Settlement Delay Days":1,"Terminal Store Mapped":True,"Terminal Mapping Required":False,"Merchant Mapping Required":False}
m,u,up=core.reconcile(pd.DataFrame([base_t]),pd.DataFrame([base_p]),1.0)
assert len(m)==1 and u.empty and up.empty
assert str(m.iloc[0]["Match Rule"]).startswith("AUTH MISSING")
assert "Auth Code Missing" in str(m.iloc[0]["Remarks"])
wrong=dict(base_p);wrong["Auth Code"]="999999"
m,u,up=core.reconcile(pd.DataFrame([base_t]),pd.DataFrame([wrong]),1.0)
assert len(m)==0
notmapped=dict(base_p);notmapped["Terminal Store Mapped"]=False
m,u,up=core.reconcile(pd.DataFrame([base_t]),pd.DataFrame([notmapped]),1.0)
assert len(m)==0
p2=dict(base_p);p2["POS Row"]=2;p2["Terminal ID"]="55610704"
m,u,up=core.reconcile(pd.DataFrame([base_t]),pd.DataFrame([base_p,p2]),1.0)
assert len(m)==0
tol=dict(base_p);tol["POS Amount"]=1259.50
m,u,up=core.reconcile(pd.DataFrame([base_t]),pd.DataFrame([tol]),1.0)
assert len(m)==1 and "Approved Tolerance" in str(m.iloc[0]["Match Rule"])
print("AUTH CODE MISSING CONTROLLED FALLBACK TEST PASS")

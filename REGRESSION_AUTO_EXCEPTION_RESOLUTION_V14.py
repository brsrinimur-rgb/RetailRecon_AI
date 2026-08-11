from pathlib import Path
import importlib.util,sys,pandas as pd
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("corev14",root/"core.py")
core=importlib.util.module_from_spec(sp);sys.modules["corev14"]=core;sp.loader.exec_module(core)

# Duplicate logic should include Date+Receipt, so repeated auth on another day is legitimate.
raw=pd.DataFrame([
 {"Store":"601","Transdate":"8/2/2026","Receiptid":"R1","Auth Code":"006631","MADA":100.0},
 {"Store":"601","Transdate":"8/3/2026","Receiptid":"R2","Auth Code":"006631","MADA":100.0},
])
n=core.normalize_tender(raw)
assert not n["D365 Duplicate"].any(),n[["Date","Receipt ID","Auth Code","D365 Duplicate"]]

# Build normalized tender directly for reconciliation.
t=pd.DataFrame([{
 "Unique Transaction ID":"U1","Store Code":"601","Date":pd.Timestamp("2026-08-02"),
 "Receipt ID":"R1","Auth Code":"006631","D365 Payment":"MADA","D365 Amount":100.0,
 "D365 Duplicate":False
}])
p=pd.DataFrame([{
 "POS Row":1,"Source File":"POS.xlsx","Provider":"","POS Store":"601",
 "POS Date":pd.Timestamp("2026-08-02"),"Posting Date":pd.Timestamp("2026-08-03"),
 "Auth Code":"006631","POS Payment":"MADA","POS Amount":100.0,"Net Amount":99.0,
 "Commission":0.87,"VAT":0.13,"Terminal ID":"T1","Merchant ID":"M1",
 "Settlement Delay Days":1,"POS Duplicate":False
}])
m,us,up=core.reconcile(t,p,1.0)
assert len(m)==1 and us.empty and up.empty
assert m.iloc[0]["Status"]=="Matched"

# Wrong/missing D365 auth, but exactly one Store+Date+Payment+Amount candidate:
# deterministic auto reconciliation, no manual correction.
t2=t.copy();t2["Auth Code"]="999999";t2["Unique Transaction ID"]="U2"
m2,us2,up2=core.reconcile(t2,p,1.0)
assert len(m2)==1 and us2.empty
assert "Date + Tender" in m2.iloc[0]["Match Rule"]

# Ambiguous same-store/date/payment/amount stays manual.
p2=pd.concat([p,p.assign(**{"POS Row":2,"Auth Code":"777777"})],ignore_index=True)
m3,us3,up3=core.reconcile(t2,p2,1.0)
assert not us3.empty
assert us3.iloc[0]["Auto Resolution Status"]=="Manual Review Required"

print("AUTO EXCEPTION RESOLUTION V14 PASS")

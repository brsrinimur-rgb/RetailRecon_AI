from pathlib import Path
import importlib.util
import pandas as pd
import numpy as np

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_test",root/"core.py")
core=importlib.util.module_from_spec(spec); spec.loader.exec_module(core)

def T(**kw):
    d={
        "D365 Row":1,"Store Code":"601","Date":pd.Timestamp("2026-07-06"),
        "Receipt ID":"R1","Auth Code":"075304","D365 Payment":"MASTERCARD",
        "D365 Amount":1260.00,"D365 Duplicate":False,"Unique Transaction ID":"U1"
    }
    d.update(kw); return d

def P(**kw):
    d={
        "POS Row":1,"Source File":"pos.xlsx","POS Store":"601",
        "POS Date":pd.Timestamp("2026-07-06"),"Posting Date":pd.Timestamp("2026-07-07"),
        "Auth Code":"","POS Payment":"MASTERCARD","POS Amount":1260.00,
        "Net Amount":1240.00,"Commission":17.39,"VAT":2.61,
        "Terminal ID":"55610703","POS Duplicate":False,"Settlement Delay Days":1,
        "Terminal Store Mapped":True,"Terminal Mapping Required":False,
        "Merchant Mapping Required":False
    }
    d.update(kw); return d

# POS Auth missing.
m,u,up=core.reconcile(pd.DataFrame([T()]),pd.DataFrame([P()]),1.0)
assert len(m)==1
assert str(m.iloc[0]["Match Rule"]).startswith("AUTH MISSING")
assert "Auth Code Missing" in str(m.iloc[0]["Remarks"])

# D365 Auth missing (real NaN), POS Auth present.
m,u,up=core.reconcile(
    pd.DataFrame([T(**{"Auth Code":np.nan})]),
    pd.DataFrame([P(**{"Auth Code":"075304"})]),
    1.0
)
assert len(m)==1
assert str(m.iloc[0]["Match Rule"]).startswith("AUTH MISSING")

# D365 Auth missing + Tender UNKNOWN, unique POS evidence.
m,u,up=core.reconcile(
    pd.DataFrame([T(**{"Auth Code":np.nan,"D365 Payment":"UNKNOWN"})]),
    pd.DataFrame([P(**{"Auth Code":"075304","POS Payment":"VISA"})]),
    1.0
)
assert len(m)==1
assert str(m.iloc[0]["Match Rule"]).startswith("AUTH/TENDER MISSING")
assert m.iloc[0]["Payment Type"]=="VISA"
assert "D365 Tender missing" in str(m.iloc[0]["Remarks"])

# Present but different Auth must not use fallback.
m,u,up=core.reconcile(
    pd.DataFrame([T(**{"Auth Code":"111111"})]),
    pd.DataFrame([P(**{"Auth Code":"999999"})]),
    1.0
)
assert len(m)==0

# Multiple candidates: never guess.
p2=P(**{"POS Row":2,"Terminal ID":"55610704","POS Payment":"VISA","Auth Code":"222222"})
m,u,up=core.reconcile(
    pd.DataFrame([T(**{"Auth Code":np.nan,"D365 Payment":"UNKNOWN"})]),
    pd.DataFrame([P(**{"Auth Code":"075304","POS Payment":"VISA"}),p2]),
    1.0
)
assert len(m)==0

# Terminal must be mapped.
m,u,up=core.reconcile(
    pd.DataFrame([T(**{"Auth Code":np.nan})]),
    pd.DataFrame([P(**{"Terminal Store Mapped":False,"Auth Code":"075304"})]),
    1.0
)
assert len(m)==0

# SAR 1 tolerance fallback.
m,u,up=core.reconcile(
    pd.DataFrame([T(**{"Auth Code":np.nan})]),
    pd.DataFrame([P(**{"Auth Code":"075304","POS Amount":1259.50})]),
    1.0
)
assert len(m)==1
assert "Approved Tolerance" in str(m.iloc[0]["Match Rule"])

print("RECONCILIATION FALLBACK CONTROL TESTS PASS")

from pathlib import Path
import importlib.util, io
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_test",root/"core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

# ISO parser must preserve month/day.
assert core.dt("2026-07-03")==pd.Timestamp("2026-07-03")
assert core.dt("2026-03-07")==pd.Timestamp("2026-03-07")
assert core.dt("04/07/2026")==pd.Timestamp("2026-07-04")

# Account/reference filenames must not create a fake source year.
assert core._date_plausible_for_source(pd.Timestamp("2026-07-03"),"traf 09582037.xlsx") is True
assert core._date_plausible_for_source(pd.Timestamp("2026-07-03"),"provider_20260701_to_20260731.xlsx") is True
assert core._date_plausible_for_source(pd.Timestamp("2025-07-03"),"provider_20260701_to_20260731.xlsx") is False

# Provider fallback without Terminal ID: TABBY store/date/amount unique.
t=pd.DataFrame([{
    "D365 Row":1,"Store Code":"601","Date":pd.Timestamp("2026-07-06"),
    "Receipt ID":"R1","Auth Code":"","D365 Payment":"TABBY","D365 Amount":2874.77,
    "D365 Duplicate":False,"Unique Transaction ID":"T1"
}])
p=pd.DataFrame([{
    "POS Row":1,"Source File":"tabby.xlsx","POS Store":"601",
    "POS Date":pd.Timestamp("2026-07-06"),"Posting Date":pd.NaT,
    "Auth Code":"","Provider Reference":"pay_1","POS Payment":"TABBY",
    "POS Amount":2874.77,"Net Amount":2874.77,"Commission":0.0,"VAT":0.0,
    "Terminal ID":"","Merchant ID":"","POS Duplicate":False,
    "Settlement Delay Days":float("nan"),"Terminal Store Mapped":False,
    "Merchant Store Mapped":False,"Store Name Mapped":True,
    "Terminal Mapping Required":False,"Merchant Mapping Required":False
}])
m,u,up=core.reconcile(t,p,1.0)
assert len(m)==1, (m,u,up)
assert m.iloc[0]["Status"]=="Matched"

# Distinct provider references must not be collapsed.
p2=pd.concat([p,p.assign(**{"POS Row":2,"Provider Reference":"pay_2"})],ignore_index=True)
collapsed=core._collapse_exact_pos_duplicates(p2)
assert len(collapsed)==2

print("DATE + PROVIDER IMPORT/FALLBACK TEST PASS")

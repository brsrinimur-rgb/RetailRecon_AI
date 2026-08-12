from pathlib import Path
import importlib.util,sys,io,pandas as pd
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_gl_v15",root/"core.py")
core=importlib.util.module_from_spec(sp);sys.modules["core_gl_v15"]=core;sp.loader.exec_module(core)

# Exact sample layout.
raw=pd.DataFrame([
 {"Journal number":"ULC-666266","Voucher":"ULC-80049169","Date":46245,
  "Year closed":"No","Type":"Operating","Ledger account":"11020913-613------",
  "Account name":"POS/Online Clearing -Tabby","Description":"Payment for order SO6-000410700",
  "Currency":"SAR","Amount in transaction currency":188.0,"Amount":188.0,"Amount in reporting currency":188.0},
 {"Journal number":"ULC-666300","Voucher":"ULC-40397215","Date":46245,
  "Year closed":"No","Type":"Operating","Ledger account":"11020913-609--Sale-5087---",
  "Account name":"POS/Online Clearing -Tabby","Description":"",
  "Currency":"SAR","Amount in transaction currency":193.996,"Amount":193.996,"Amount in reporting currency":193.996},
])
g=core.normalize_d365_gl(raw,"sample.xlsx")
assert list(g["Main Account"])==["11020913","11020913"]
assert list(g["Store Code"])==["613","609"]
assert g.iloc[0]["Sales Order"]=="SO6-000410700"
assert g.iloc[0]["GL Group"]=="TABBY"

# Store 613 Sales Order trace.
t=pd.DataFrame([{
 "Store Code":"613","Date":pd.Timestamp("2026-08-11"),"Receipt ID":"R613",
 "Sales Order":"SO6-000410700","Auth Code":"","D365 Payment":"TABBY","D365 Amount":188.0
}])
tr,gl_only=core.trace_d365_source_to_gl(t,g,1.0)
assert len(tr)==1
assert tr.iloc[0]["GL Trace Status"]=="GL MATCHED",tr.iloc[0].to_dict()
assert tr.iloc[0]["GL Trace Rule"].startswith("Store 613 Sales Order")

# Wrong GL account for a known Sales Order must fail account validation.
g_bad=g.copy()
g_bad.loc[0,"Main Account"]="11020922"
tr2,_=core.trace_d365_source_to_gl(t,g_bad,1.0)
assert tr2.iloc[0]["GL Trace Status"]=="GL ACCOUNT MISMATCH"

# JV exact account/store/date/amount.
jv=pd.DataFrame([{
 "Journal Batch":"RR-609-X","Journal batch number":"RR-609-X","Store Code":"609",
 "Group":"TABBY","Main Account":"11020913","Debit":0.0,"Credit":194.0,
 "JV Accounting Date":pd.Timestamp("2026-08-11"),"Voucher":"ULC-40397215"
}])
ver,_=core.reconcile_jv_to_d365_gl(jv,g,1.0)
assert len(ver)==1
assert ver.iloc[0]["GL Verification Status"]=="GL MATCHED"

cc=core.d365_gl_clearing_control(g)
assert not cc.empty and "Net GL Movement" in cc.columns
ex=core.build_d365_gl_exceptions(tr,ver,gl_only,g)
assert isinstance(ex,pd.DataFrame)
print("D365 GL CONTROL V15 PASS")


import sys
from pathlib import Path
import pandas as pd
root=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
from logic.store_tender_pos_gl import run_three_way

tender=pd.DataFrame([{"Unique Transaction ID":"TX1","Store Code":"601","Date":pd.Timestamp("2026-08-01"),
"Receipt ID":"R1","Auth Code":"A1","D365 Payment":"VISA","D365 Amount":100.0,"D365 Duplicate":False}])
pos=pd.DataFrame([{"POS Store":"601","POS Date":pd.Timestamp("2026-08-01"),"POS Payment":"VISA",
"POS Amount":100.0,"Auth Code":"A1","Net Amount":98.0,"Commission":2.0,"VAT":0.0,
"Posting Date":pd.Timestamp("2026-08-01"),"Settlement Delay Days":1,"Terminal ID":"T1","Source File":"pos.xlsx"}])
gl=pd.DataFrame([{"GL Row":1,"Source File":"gl.xlsx","Journal Number":"J1","Voucher":"V1",
"GL Date":pd.Timestamp("2026-08-01"),"Main Account":"11020907","Store Code":"601",
"Ledger Account":"11020907-601","Description":"Cash control","Signed Amount":100.0,
"Absolute Amount":100.0,"Controlled Clearing Account":True,"Sales Order":"","GL Event Type":"NORMAL"}])

r=run_three_way(tender,pos,gl,1.0)
assert r["detail"].iloc[0]["GL Amount Status"]=="GL AMOUNT MATCHED"
assert r["detail"].iloc[0]["Three-Way Status"]=="THREE-WAY RECONCILED"
print("[PASS] POS Amount = GL Amount")

gl_tol=gl.copy(); gl_tol["Signed Amount"]=100.50; gl_tol["Absolute Amount"]=100.50
r=run_three_way(tender,pos,gl_tol,1.0)
assert r["detail"].iloc[0]["GL Amount Status"]=="GL AMOUNT MATCHED"
print("[PASS] POS/GL within tolerance")

gl_bad=gl.copy(); gl_bad["Signed Amount"]=90.0; gl_bad["Absolute Amount"]=90.0
r=run_three_way(tender,pos,gl_bad,1.0)
assert r["detail"].iloc[0]["GL Amount Status"]=="GL AMOUNT EXCEPTION"
assert r["detail"].iloc[0]["Three-Way Status"]=="POS RECONCILED / GL AMOUNT EXCEPTION"
print("[PASS] POS/GL outside tolerance")

gl_missing=gl.copy(); gl_missing["Signed Amount"]=float("nan"); gl_missing["Absolute Amount"]=float("nan")
r=run_three_way(tender,pos,gl_missing,1.0)
assert r["detail"].iloc[0]["GL Amount Status"]=="GL NOT POSTED"
print("[PASS] Missing GL amount")

print("REGRESSION V46 POS GL AMOUNT CONTROL PASS")

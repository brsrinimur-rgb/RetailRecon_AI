
import sys
from pathlib import Path
import pandas as pd
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from logic.store_tender_pos_gl import run_three_way

tender=pd.DataFrame([{
    "Unique Transaction ID":"TX1","Store Code":"601","Date":pd.Timestamp("2026-07-01"),
    "Receipt ID":"R1","Auth Code":"A1","D365 Payment":"VISA","D365 Amount":100.0,
    "D365 Duplicate":False
}])
pos=pd.DataFrame([{
    "POS Store":"601","POS Date":pd.Timestamp("2026-07-01"),"POS Payment":"VISA",
    "POS Amount":100.0,"Auth Code":"A1","Net Amount":98.0,"Commission":2.0,"VAT":0.0,
    "Posting Date":pd.Timestamp("2026-07-01"),"Settlement Delay Days":1,
    "Terminal ID":"T1","Source File":"pos.xlsx"
}])
gl=pd.DataFrame([{
    "GL Row":1,"Source File":"gl.xlsx","Journal Number":"J1","Voucher":"V1",
    "GL Date":pd.Timestamp("2026-07-01"),"Main Account":"11020907","Store Code":"601",
    "Ledger Account":"11020907-601","Description":"VISA clearing",
    "Signed Amount":100.0,"Absolute Amount":100.0,"Controlled Clearing Account":True,
    "Sales Order":"","GL Event Type":"NORMAL"
}])
r=run_three_way(tender,pos,gl,1.0)
assert int(r["summary"].iloc[0]["Three-Way Reconciled"])==1
assert int(r["summary"].iloc[0]["Exceptions"])==0
assert r["detail"].iloc[0]["Three-Way Status"]=="THREE-WAY RECONCILED"
print("[PASS] Store Tender + POS + GL deterministic three-way match.")

gl_bad=gl.copy(); gl_bad["Signed Amount"]=90.0; gl_bad["Absolute Amount"]=90.0
r2=run_three_way(tender,pos,gl_bad,1.0)
assert int(r2["summary"].iloc[0]["Three-Way Reconciled"])==0
assert int(r2["summary"].iloc[0]["Exceptions"])==1
print("[PASS] GL amount mismatch becomes exception.")

cash=tender.copy(); cash["D365 Payment"]="CASH"
r3=run_three_way(cash,pd.DataFrame(),gl,1.0)
assert r3["detail"].iloc[0]["Three-Way Status"] in {"CASH / GL CONTROL ONLY","CASH / GL EXCEPTION"}
print("[PASS] Cash does not require POS.")
print("REGRESSION V45 STORE TENDER POS GL PASS")

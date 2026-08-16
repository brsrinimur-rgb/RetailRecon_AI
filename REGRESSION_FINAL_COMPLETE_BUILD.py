from pathlib import Path
import sys, pandas as pd, numpy as np, tempfile, sqlite3, shutil, importlib.util, os
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
import core
from logic import bank_settlement_extension as bank_ext
from logic.carry_forward_extension import build_settlement_carry_forward

# 1) Classifier proof
assert core.classify_settlement_source("tap.csv",pd.DataFrame(columns=["payout_id","settlement_id","amount"]))=="TAP_PAYOUT"
assert core.classify_settlement_source("tap.xlsx",pd.DataFrame(columns=["Payout ID","Settlement ID","Amount"]))=="TAP_PAYOUT"
assert core.classify_settlement_source("tabby.xlsx",pd.DataFrame(columns=["Order Number","Transferred Amount","Transfer Date","Merchant"]))=="TABBY_PAYOUT"

# 2) TABBY linking proof
matched=pd.DataFrame([
 {"Unique Transaction ID":"T1","Provider Reference":"ORD-1","Payment Type":"TABBY","Bank Settled":False},
 {"Unique Transaction ID":"T2","Provider Reference":"ORD-2","Payment Type":"TABBY","Bank Settled":False},
])
pb=pd.DataFrame([{"Provider":"TABBY","Order Numbers":"ORD-1|ORD-2","Underlying IDs":""}])
linked=core.link_tabby_payout_underlying_ids(pb,matched)
assert linked.iloc[0]["Underlying IDs"]=="T1|T2"

# 3) Correct ANB proof: POS batch amount equals bank credit.
batch=pd.DataFrame([{
 "Settlement Source":"ANB POS","Settlement Batch ID":"B1","Provider":"ANB POS",
 "Store Code":"601","Terminal ID":"55610694","Payment Type":"MADA",
 "Settlement Date":pd.Timestamp("2026-07-07"),
 "Gross Amount":13052.02,"Expected Bank Amount":13052.02,"Transaction Count":17,
 "Underlying IDs":"|".join(f"U{i}" for i in range(17))
}])
bank=pd.DataFrame([{
 "Bank":"ANB","Bank Date":pd.Timestamp("2026-07-08"),"Bank Amount":13052.02,
 "Credit":13052.02,"Debit":0.0,"Description":"POS MD_88077230_UNITED LUXURY",
 "Narration Terminal ID":"55610694","Narration Scheme":"MADA",
 "Narration Source Date":pd.Timestamp("2026-07-08"),
 "Narration Transaction Count":17,"Narration Fee":71.80,"Narration VAT":10.76,
 "Bank Source File":"anb.xlsx","Bank Source Sheet":"anb","Bank Source Row":1,
}])
res,_=bank_ext.reconcile_card_batches_advanced(batch,bank,1.0)
assert res.iloc[0]["Settlement Status"]=="BANK RECEIVED",res.iloc[0].to_dict()
assert round(float(res.iloc[0]["Actual Bank Amount"]),2)==13052.02
assert round(float(res.iloc[0]["ANB Commission"]),2)==71.80
assert round(float(res.iloc[0]["ANB VAT"]),2)==10.76
assert round(float(res.iloc[0]["Net Bank Movement"]),2)==12969.46

# 4) Carry-forward proof: July item settled in August stays July original period.
m=pd.DataFrame([{
 "Unique Transaction ID":"LATE1","Store Code":"601","Payment Type":"MADA",
 "Date":pd.Timestamp("2026-07-31"),"D365 Amount":1000.0,
 "Bank Settled":True,"Settlement Bank Date":pd.Timestamp("2026-08-02"),
}])
cf=build_settlement_carry_forward(m,pd.Timestamp("2026-07-31"))
assert len(cf)==1
assert cf.iloc[0]["Original Period"]=="2026-07"
assert cf.iloc[0]["Carry Forward Period"]=="2026-08"
assert cf.iloc[0]["Resolution Period"]=="2026-08"
assert cf.iloc[0]["Carry Forward Status"]=="SETTLED IN NEXT PERIOD"

# 5) JV full-month received-only gate.
jvsrc=pd.DataFrame([
 {"Status":"Matched","Difference":0.0,"Bank Settled":True,
  "Settlement Bank Date":pd.Timestamp("2026-07-31"),"Date":pd.Timestamp("2026-07-30"),
  "Payment Type":"MADA","Store Code":"601","D365 Amount":1000.0,"POS Amount":1000.0,
  "Commission":0.0,"VAT":0.0},
 {"Status":"Matched","Difference":0.0,"Bank Settled":True,
  "Settlement Bank Date":pd.Timestamp("2026-08-02"),"Date":pd.Timestamp("2026-07-31"),
  "Payment Type":"MADA","Store Code":"601","D365 Amount":500.0,"POS Amount":500.0,
  "Commission":0.0,"VAT":0.0},
])
j=core.create_jv(
    jvsrc,from_date=pd.Timestamp("2026-07-01"),to_date=pd.Timestamp("2026-07-31"),
    grouping_map={"MADA":"MADA"},active_payment_types={"MADA"}
)
assert not j.empty
assert set(j["Group"])=={"MADA"}
# Only first SAR 1000 item is eligible; second settles in Aug and is carry-forward.
assert round(float(j["Gross Amount"].max()),2)==1000.0

print("FINAL COMPLETE BUILD REGRESSION PASS")

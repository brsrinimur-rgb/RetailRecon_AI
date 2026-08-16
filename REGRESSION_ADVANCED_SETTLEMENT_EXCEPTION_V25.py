from pathlib import Path
import sys,pandas as pd
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
from logic import bank_settlement_extension as bank_ext
from logic import exception_routing_extension as exc

batches=pd.DataFrame([{
 "Settlement Source":"ANB POS","Settlement Batch ID":"B1","Provider":"ANB POS",
 "Store Code":"601","Terminal ID":"T1","Payment Type":"VISA",
 "Settlement Date":pd.Timestamp("2026-07-04"),"Gross Amount":1015.0,
 "Expected Bank Amount":1000.0,"Transaction Count":2
}])
bank=pd.DataFrame([
 {"Bank":"ANB","Bank Date":pd.Timestamp("2026-07-05"),"Bank Amount":400.0,"Credit":400.0,
  "Narration Terminal ID":"T1","Narration Scheme":"VISA","Narration Source Date":pd.Timestamp("2026-07-04"),
  "Narration Transaction Count":1,"Narration Fee":5.0,"Narration VAT":1.0,"Description":"A","Bank Source File":"anb.xlsx"},
 {"Bank":"ANB","Bank Date":pd.Timestamp("2026-07-05"),"Bank Amount":600.0,"Credit":600.0,
  "Narration Terminal ID":"T1","Narration Scheme":"VISA","Narration Source Date":pd.Timestamp("2026-07-04"),
  "Narration Transaction Count":1,"Narration Fee":7.5,"Narration VAT":1.5,"Description":"B","Bank Source File":"anb.xlsx"},
])
res,_=bank_ext.reconcile_card_batches_advanced(batches,bank,1.0)
# Superseded by the later Finance-approved ANB rule:
# POS batch amount must equal ANB credit. Commission/VAT are separate debits.
# Therefore the old 400+600 credit aggregation against a 1,015 POS batch must NOT auto-settle.
assert res.iloc[0]["Settlement Status"]=="BANK REVIEW REQUIRED",res.iloc[0].to_dict()

u=pd.DataFrame([
 {"D365 Row":17,"Store Code":"601","Date":pd.Timestamp("2026-07-02"),"Receipt ID":"R1",
  "Auth Code":"032720","D365 Payment":"MADA","D365 Amount":100.0,"Reason":"Missing settlement"},
 {"D365 Row":18,"Store Code":"601","Date":pd.Timestamp("2026-07-02"),"Receipt ID":"R2",
  "Auth Code":"111111","D365 Payment":"MADA","D365 Amount":200.0,"Reason":"Missing settlement"},
])
p=pd.DataFrame([
 {"POS Store":"601","POS Payment":"MADA","POS Amount":100.0,"POS Date":pd.Timestamp("2026-07-02"),
  "Auth Code":"032720","Source File":"pos.xlsx"},
 {"POS Store":"601","POS Payment":"MADA","POS Amount":200.0,"POS Date":pd.Timestamp("2026-07-02"),
  "Auth Code":"222222","Source File":"pos.xlsx"},
])
cand=exc.route_auth_correction_candidates(u,p,pd.DataFrame(),1.0)
assert set(cand["D365 Row"])=={18},cand
assert cand.iloc[0]["Suggested Auth Code"]=="222222"
other=exc.unresolved_non_auth_exceptions(u,cand)
assert set(other["D365 Row"])=={17}
print("ADVANCED SETTLEMENT + EXCEPTION ROUTING V25 PASS")

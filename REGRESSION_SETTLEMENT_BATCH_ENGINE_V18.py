from pathlib import Path
import importlib.util,sys,pandas as pd,numpy as np
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("corev18",root/"core.py")
core=importlib.util.module_from_spec(sp);sys.modules["corev18"]=core;sp.loader.exec_module(core)

# ANB batch propagation.
matched=pd.DataFrame([
 {"Unique Transaction ID":"U1","Store Code":"606","Payment Type":"MADA","POS Date":pd.Timestamp("2026-08-01"),
  "Terminal ID":"55610688","POS Amount":100.0,"Net Amount":99.0,"Commission":0.87,"VAT":0.13,"D365 Amount":100.0,"Bank Settled":False},
 {"Unique Transaction ID":"U2","Store Code":"606","Payment Type":"MADA","POS Date":pd.Timestamp("2026-08-01"),
  "Terminal ID":"55610688","POS Amount":200.0,"Net Amount":198.0,"Commission":1.74,"VAT":0.26,"D365 Amount":200.0,"Bank Settled":False},
])
batches=core.build_card_settlement_batches(matched)
assert len(batches)==1
assert round(float(batches.iloc[0]["Expected Bank Amount"]),2)==297.00

bank=pd.DataFrame([{
 "Bank Date":pd.Timestamp("2026-08-02"),"Bank Amount":297.00,"Narration":"MADA TID 55610688 TX_2"
}])
nr=bank["Narration"].apply(core.parse_bank_narration).apply(pd.Series)
bank=pd.concat([bank,nr],axis=1)
res,un=core.reconcile_settlement_batches_to_bank(batches,bank,1.0,5.0)
assert res.iloc[0]["Settlement Status"]=="BANK RECEIVED",res.iloc[0].to_dict()
upd=core.propagate_batch_settlement_to_matched(matched,res)
assert upd["Bank Settled"].all()
assert set(upd["Settlement Stage"])=={"BANK RECEIVED"}

# Tabby fixed settlement-level fee.
tb=pd.DataFrame([{
 "Settlement Source":"TABBY","Settlement Batch ID":"TB1","Provider":"TABBY",
 "Settlement Date":pd.Timestamp("2026-07-06"),"Expected Bank Amount":48304.47
}])
bb=pd.DataFrame([{"Bank Date":pd.Timestamp("2026-07-06"),"Bank Amount":48299.47,"Narration":"TABBY"}])
res2,_=core.reconcile_settlement_batches_to_bank(tb,bb,1.0,5.0)
assert res2.iloc[0]["Settlement Status"]=="BANK RECEIVED"
assert "Fixed Fee SAR 5.00" in res2.iloc[0]["Bank Match Rule"]

# TAP settlement date from settlement_id if Excel date is implausible.
tap=pd.DataFrame([{
 "payout_id":"P1","settlement_id":"SETTLEMENT_20260804_X","amount":100.0,
 "status":"CAPTURED","settlement_date":"2026-04-01","payout_date":"2026-08-05","authorization_id":"A1"
}])
tp=core.normalize_tap_payout(tap,"tap.xlsx")
assert pd.to_datetime(tp.iloc[0]["Settlement Date"]).date()==pd.Timestamp("2026-08-04").date()

print("SETTLEMENT BATCH ENGINE V18 PASS")

from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("bsv",root/"bank_settlement_final.py")
bsv=importlib.util.module_from_spec(spec);spec.loader.exec_module(bsv)

tabby=pd.DataFrame({"Store Name":["Faisaliah"],"Transfer Date":["2026-07-06"],"Transferred Amount":[645.40]})
tb=bsv.build_tabby_payouts(tabby,5.0)
assert round(tb.loc[0,"Expected Bank Credit"],2)==640.40

tamara=pd.DataFrame({"Channel":["Online"],"Payout Date":["2026-07-14"],"Payable to Merchant":[63794.88]})
tm=bsv.build_tamara_payouts(tamara)
assert round(tm.loc[0,"Expected Bank Credit"],2)==63794.88

tap=pd.DataFrame({"payout_id":["p1","p1"],"payout_date":["2026-07-20","2026-07-20"],"net_amount":[50000,53561.94]})
tp=bsv.build_tap_payouts(tap)
assert round(tp.loc[0,"Expected Bank Credit"],2)==103561.94

anb=pd.DataFrame({
    "Value Date":["2026-07-06"],
    "Amount Cr.":[63321.99],
    "Narration 2":["301128607303_55610683_050726"],
    "Narration 3":["Mada_47.07_313.79_TX_2"]
})
ab=bsv.normalize_anb_bank_batches(anb)
assert ab.loc[0,"Terminal ID"]=="55610683"
assert ab.loc[0,"Payment Type"]=="MADA"
assert int(ab.loc[0,"Bank TX Count"])==2
assert round(ab.loc[0,"Bank Gross"],2)==63321.99

print("FULL BANK INTEGRATION TEST PASS")

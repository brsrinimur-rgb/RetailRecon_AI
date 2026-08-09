
import pandas as pd
from bank_settlement_final import build_tabby_payouts, build_tamara_payouts, build_tap_payouts, verify_provider_payouts

tabby=pd.DataFrame({"Store Name":["Faisaliah"],"Transfer Date":["2026-07-06"],"Transferred Amount":[645.40]})
o=build_tabby_payouts(tabby)
assert round(o.loc[0,"Expected Bank Credit"],2)==640.40

tamara=pd.DataFrame({"Channel":["Online"],"Payout Date":["2026-07-14"],"Payable to Merchant":[63794.88]})
o=build_tamara_payouts(tamara)
assert round(o.loc[0,"Expected Bank Credit"],2)==63794.88

tap=pd.DataFrame({"payout_id":["p1","p1"],"payout_date":["2026-07-20","2026-07-20"],"net_amount":[50000,53561.94]})
o=build_tap_payouts(tap)
assert round(o.loc[0,"Expected Bank Credit"],2)==103561.94

bank=pd.DataFrame({"Date":["2026-07-20"],"Credit":[103561.94],"Transaction Details":["TAP TECHNOLOGIES COMPANY"]})
v=verify_provider_payouts(o,bank,"TAP")
assert bool(v.loc[0,"Bank Settled"])
print("FINAL BANK SETTLEMENT REGRESSION TESTS PASS")

from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_614",root/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

# D365 export shape matching the user's screenshot.
d365=pd.DataFrame([
    {"Store":614,"Transdate":"8/1/2026","Receiptid":"614R1","Authcode":"001553","MADA":128.80},
    {"Store":614,"Transdate":"8/3/2026","Receiptid":"614R2","Authcode":"044272","MADA":128.80},
    {"Store":614,"Transdate":"8/3/2026","Receiptid":"614R3","Authcode":"029339","Visa":157.55},
    {"Store":614,"Transdate":"8/3/2026","Receiptid":"614R4","Authcode":"102941","Visa":128.80},
    {"Store":614,"Transdate":"8/3/2026","Receiptid":"614R5","Authcode":"510968","Visa":128.80},
    {"Store":614,"Transdate":"8/4/2026","Receiptid":"614R6","Authcode":"079257","Visa":157.55},
    {"Store":614,"Transdate":"8/6/2026","Receiptid":"614R7","Authcode":"069606","Visa":128.80},
    {"Store":614,"Transdate":"8/6/2026","Receiptid":"614R8","Authcode":"014753","MADA":151.80},
    {"Store":614,"Transdate":"8/7/2026","Receiptid":"614R9","Authcode":"120808","Master":128.80},
    {"Store":614,"Transdate":"8/7/2026","Receiptid":"614R10","Authcode":"002227","MADA":1516.85},
    {"Store":614,"Transdate":"8/8/2026","Receiptid":"614R11","Authcode":"017481","Visa":188.60},
])

tender=core.normalize_tender(d365)

# Confirm dates are Aug, not Jan/Mar/Jun/etc.
assert tender["Date"].dt.month.eq(8).all(), tender[["Date","Auth Code"]]

pos_rows=[
    ("001553","MADA",128.80,"8/1/2026"),
    ("044272","MADA",128.80,"8/3/2026"),
    ("029339","VISA",157.55,"8/3/2026"),
    ("102941","VISA",128.80,"8/3/2026"),
    ("510968","VISA",128.80,"8/3/2026"),
    ("079257","VISA",157.55,"8/4/2026"),
    ("069606","VISA",128.80,"8/6/2026"),
    ("014753","MADA",151.80,"8/6/2026"),
    ("120808","MASTERCARD",128.80,"8/7/2026"),
    ("002227","MADA",1516.85,"8/7/2026"),
    ("017481","VISA",188.60,"8/8/2026"),
]
pos=pd.DataFrame([{
    "POS Row":i+1,"Source File":"POS.xlsx","POS Store":"614",
    "POS Date":core.dt(d),"Posting Date":core.dt(d),"Auth Code":a,
    "POS Payment":p,"POS Amount":amt,"Net Amount":amt,
    "Commission":0.0,"VAT":0.0,"Terminal ID":"55610688",
    "Merchant ID":"","Account":"","ARN":"","Slip No":"",
    "POS Duplicate":False,"Settlement Delay Days":0
} for i,(a,p,amt,d) in enumerate(pos_rows)])

matched,us,up=core.reconcile(tender,pos,1.0)
assert len(matched)==11, (len(matched),len(us),len(up),us,up)
assert us.empty
assert up.empty
assert matched["Status"].eq("Matched").all()

expected={"001553","044272","029339","102941","510968","079257","069606","014753","120808","002227","017481"}
assert set(matched["Auth Code"])==expected

print("STORE 614 EXACT MATCH REGRESSION PASS")

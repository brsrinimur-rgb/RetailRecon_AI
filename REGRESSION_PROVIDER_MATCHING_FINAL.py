from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_final",root/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

# TABBY: Order Number is primary reference, Creation date is recognized.
tabby_raw=pd.DataFrame([{
    "Store":"Aigner - Tahlia Center, Payment Links",
    "Payment ID":"019fe554-6830-8bc0-ac17-ba066084e81f",
    "Creation date":"8/9/2026",
    "Status":"captured",
    "Order number":"8942394",
    "Captured amount":427,
    "Payment amount":427,
}])
tabby=core.normalize_pos(tabby_raw,"Sales TABBY.xlsx","TABBY")
assert str(tabby.iloc[0]["Auth Code"])=="8942394"
assert pd.notna(tabby.iloc[0]["POS Date"])

# TAMARA leading-zero match.
tender=pd.DataFrame([{
    "Unique Transaction ID":"x1","Store Code":"603","Date":pd.Timestamp("2026-08-08"),
    "Receipt ID":"603603011027284","Auth Code":"0554030397",
    "D365 Payment":"TAMARA","D365 Amount":384.0,"D365 Duplicate":False
}])
pos=pd.DataFrame([{
    "POS Row":1,"Source File":"Tamara.csv","POS Store":"603",
    "POS Date":pd.Timestamp("2026-08-08"),"Posting Date":pd.NaT,
    "Auth Code":"554030397","POS Payment":"TAMARA","POS Amount":384.0,
    "Net Amount":384.0,"Commission":0.0,"VAT":0.0,"Terminal ID":"",
    "Merchant ID":"","Account":"","ARN":"","Slip No":"",
    "POS Duplicate":False,"Settlement Delay Days":None
}])
matched,us,up=core.reconcile(tender,pos,1.0)
assert len(matched)==1
assert matched.iloc[0]["Status"]=="Matched"
assert matched.iloc[0]["Provider Reference"]=="554030397"

# Same confirmed pattern for store 601.
tender2=tender.copy()
tender2.loc[0,"Store Code"]="601"
tender2.loc[0,"Auth Code"]="0518584327"
tender2.loc[0,"Date"]=pd.Timestamp("2026-08-01")
pos2=pos.copy()
pos2.loc[0,"POS Store"]="601"
pos2.loc[0,"Auth Code"]="518584327"
pos2.loc[0,"POS Date"]=pd.Timestamp("2026-08-01")
matched2,_,_=core.reconcile(tender2,pos2,1.0)
assert len(matched2)==1

print("FINAL PROVIDER MATCHING REGRESSION PASS")

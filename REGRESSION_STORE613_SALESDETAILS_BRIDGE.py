from pathlib import Path
import importlib.util,sys,pandas as pd
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core613",root/"core.py")
core=importlib.util.module_from_spec(sp);sys.modules["core613"]=core;sp.loader.exec_module(core)

# Mimic StoreTender 613 after normalization: Sales Order exists, Receipt/Auth absent.
tender=pd.DataFrame([{
 "D365 Row":1,"Store Code":"613","Date":pd.Timestamp("2026-08-01"),
 "Receipt ID":"","Auth Code":"","D365 Raw Auth Code":"","Sales Order":"SO6-000408896",
 "StoreTender Reference":"ULC-606815","D365 Payment":"VISA","D365 Amount":1000.0,
 "D365 Duplicate":False,"Unique Transaction ID":"old","D365 Match Key":"old",
}])
sales=pd.DataFrame([{
 "SalesDetails Row":10,"Store Code":"613","Store Name":"Aignerme - KSA",
 "Sales Order":"SO6-000408896","Receipt ID":"16000194050","Auth Code":"123456",
 "Invoice":"ULC-239683","Invoice Date":pd.Timestamp("2026-08-02"),
 "SalesDetails Source":"D365_FIN_SalesDetails.xlsx"
}])
out,audit=core.enrich_store613_from_sales_details(tender,sales)
r=out.iloc[0]
assert r["Receipt ID"]=="16000194050"
assert r["Auth Code"]=="123456"
assert r["Sales Order"]=="SO6-000408896"
assert "Receipt Bridged" in r["SalesDetails Bridge Status"]
assert "Auth Bridged" in r["SalesDetails Bridge Status"]
assert len(audit)==1

# Ambiguous Receipt IDs must never be guessed.
sales2=pd.concat([sales,sales.assign(**{"Receipt ID":"DIFFERENT"})],ignore_index=True)
out2,a2=core.enrich_store613_from_sales_details(tender,sales2)
assert out2.iloc[0]["Receipt ID"]==""
assert "Ambiguous Receipt" in out2.iloc[0]["SalesDetails Bridge Status"]

# Missing Auth in SalesDetails is valid: Receipt still bridges, Auth remains blank.
sales3=sales.copy();sales3["Auth Code"]=""
out3,a3=core.enrich_store613_from_sales_details(tender,sales3)
assert out3.iloc[0]["Receipt ID"]=="16000194050"
assert out3.iloc[0]["Auth Code"]==""
assert "Auth Not Available" in out3.iloc[0]["SalesDetails Bridge Status"]

print("STORE 613 SALESDETAILS BRIDGE PASS")

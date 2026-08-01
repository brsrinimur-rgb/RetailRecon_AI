from pathlib import Path
r=Path(__file__).parent
required=[
"Home.py","core.py","auth.py","theme.py",
"pages/1_POS_Reconciliation.py","pages/10_Commission_Validation.py",
"pages/11_Bank_Settlement_Audit.py","pages/12_Refund_Reconciliation.py",
"pages/13_POS_Auto_Mapper.py","pages/14_Store_Mapping_Master.py","pages/16_POS_Terminal_Master.py","pages/17_Merchant_ID_Master.py","pages/15_Bank_Claim_Follow_Up.py",
"pages/21_Month_End_Close_Calendar.py","pages/22_GL_Configuration.py",
"pages/23_Exception_Correction_Center.py","pages/24_JV_Creation.py",
"pages/25_JV_Approval_Center.py","pages/26_D365_Posting_Center.py",
"pages/27_D365_Posting_Verification.py","pages/28_Late_Transaction_Adjustment_JV.py"]
missing=[x for x in required if not (r/x).exists()]
assert not missing, missing
src=(r/"pages/1_POS_Reconciliation.py").read_text(encoding="utf-8")
for token in ["POS-TO-GL CONTROL CENTER","RUN RECONCILIATION","Commission Validation","Bank Settlement Audit","JV Approval Center","D365 Posting Center"]:
    assert token in src, token
print("BUILD CHECK PASS")


# Mandatory finance regression: Store 601 / 06-Jul-2026 / Auth 075304 / MASTER / SAR 1,260
import importlib.util
import pandas as pd

spec=importlib.util.spec_from_file_location("rr_core_regression",r/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

tender=pd.DataFrame([{
    "D365 Row":1,
    "Store Code":"601",
    "Date":pd.Timestamp("2026-07-06"),
    "Receipt ID":"601601011017644",
    "Auth Code":"075304",
    "D365 Payment":"MASTERCARD",
    "D365 Amount":1260.00,
    "D365 Duplicate":False,
    "Unique Transaction ID":"REG-601-075304"
}])

pos=pd.DataFrame([{
    "POS Row":1,
    "Source File":"2026-07-07_13-46-44_UNITED_LUXURY_Transactions Report.xlsx",
    "POS Store":"601",
    "POS Date":pd.Timestamp("2026-07-06"),
    "Posting Date":pd.Timestamp("2026-07-06"),
    "Auth Code":"075304",
    "POS Payment":"MASTERCARD",
    "POS Amount":1260.00,
    "Net Amount":1260.00,
    "Commission":0.0,
    "VAT":0.0,
    "Terminal ID":"55610716",
    "POS Duplicate":False,
    "Settlement Delay Days":0
}])

m,u,p=core.reconcile(tender,pos,1.0)
assert len(m)==1, "Regression 601/075304 failed: transaction must match"
assert u.empty, "Regression 601/075304 failed: D365 remained unmatched"
assert p.empty, "Regression 601/075304 failed: POS remained unmatched"
assert m.iloc[0]["Difference"]==0.0
assert m.iloc[0]["Status"]=="Matched"

# Exact repeated POS statements must collapse rather than block the match.
pos2=pd.concat([pos,pos.assign(**{"Source File":"OVERLAPPING_DAILY_REPORT.xlsx"})],ignore_index=True)
pos2["POS Duplicate"]=True
m2,u2,p2=core.reconcile(tender,pos2,1.0)
assert len(m2)==1, "Exact repeated POS rows should collapse and remain matchable"
assert int(m2.iloc[0]["Exact POS Repeat Count"])==2

print("REGRESSION PASS: 601 / 06-Jul-2026 / 075304 / MASTER / SAR 1,260.00")

from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_cash",root/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

d365=pd.DataFrame([
    {
        "Store":601,
        "Transdate":"8/3/2026",
        "Receiptid":"601601012001362",
        "Auth Code":"",
        "Cash":-475.00,
    },
    {
        "Store":601,
        "Transdate":"8/7/2026",
        "Receiptid":"601601011018062",
        "Auth Code":"",
        "Cash":460.00,
    },
])

tender=core.normalize_tender(d365)
cash=tender[tender["D365 Payment"]=="CASH"].copy()

assert len(cash)==2, cash
refund=cash[cash["Receipt ID"]=="601601012001362"].iloc[0]
sale=cash[cash["Receipt ID"]=="601601011018062"].iloc[0]

assert refund["Cash Classification"]=="Cash Refund"
assert float(refund["Cash Amount"])==-475.00
assert sale["Cash Classification"]=="Cash Sales"
assert float(sale["Cash Amount"])==460.00

# Cash must be excluded before POS reconciliation.
tender_for_pos=tender[tender["D365 Payment"]!="CASH"].copy()
matched,us,up=core.reconcile(tender_for_pos,pd.DataFrame(),1.0)
assert us.empty, us
assert matched.empty
assert up.empty

print("CASH CLASSIFICATION REGRESSION PASS")

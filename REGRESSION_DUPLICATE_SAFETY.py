from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_test",root/"core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

# Two genuinely separate anonymous sales with same store/date/payment/amount must remain two rows.
x=pd.DataFrame([
    {"POS Store":"601","POS Date":pd.Timestamp("2026-07-01"),"Auth Code":"",
     "Provider Reference":"","Provider Order Reference":"","Terminal ID":"5561",
     "POS Payment":"MADA","POS Amount":100.0,"Source File":"a.xlsx","POS Duplicate":False},
    {"POS Store":"601","POS Date":pd.Timestamp("2026-07-01"),"Auth Code":"",
     "Provider Reference":"","Provider Order Reference":"","Terminal ID":"5561",
     "POS Payment":"MADA","POS Amount":100.0,"Source File":"b.xlsx","POS Duplicate":False},
])
o=core._collapse_exact_pos_duplicates(x)
assert len(o)==2

# Same provider transaction repeated across overlapping uploads should collapse.
y=x.copy()
y["Provider Reference"]="provider_tx_1"
o=core._collapse_exact_pos_duplicates(y)
assert len(o)==1
assert int(o.iloc[0]["Exact POS Repeat Count"])==2
print("DUPLICATE SAFETY TEST PASS")

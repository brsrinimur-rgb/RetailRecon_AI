from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("rrcore",root/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

# ANB-like transaction + statement Sum row.
df=pd.DataFrame([
    {
        "Terminal ID":"55610683",
        "Transaction Date":"04-Jul-2026",
        "Trans Approval Cd":"3595720",
        "Transaction Amount":27962.00,
        "Scheme":"P",
        "Merchant Name":"UNITED LUXURY CORP",
        "Posting Date":"04-Jul-2026"
    },
    {
        "Terminal ID":"Sum:",
        "Transaction Date":None,
        "Trans Approval Cd":None,
        "Transaction Amount":215772.62,
        "Scheme":None,
        "Merchant Name":None,
        "Posting Date":None
    }
])

out=core.normalize_pos(df,"ANB_TEST.xlsx")

assert len(out)==1, f"Expected 1 transaction, got {len(out)}"
assert out.iloc[0]["Terminal ID"]=="55610683"
assert out.iloc[0]["Auth Code"]=="3595720"
assert float(out.iloc[0]["POS Amount"])==27962.00
assert "SUM" not in out["Terminal ID"].astype(str).str.upper().tolist()

print("SUMMARY ROW FILTER PASS")

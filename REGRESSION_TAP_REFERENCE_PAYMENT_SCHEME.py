from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_tap_v4",root/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

src="charge_2608100931_283731_260801_to_260809.csv"

raw=pd.DataFrame([{
    "transaction date":"08/03/2026",
    "posting date":"08/03/2026",
    "reference_order":"932768",
    "auth code":"WRONG999",
    "amount":617.40,
    "net amount":609.15,
    "commission":7.17,
    "payment type":"DEBIT",
    "payment_scheme":"MADA",
    "merchant id":"283731",
}])

out=core.normalize_pos(raw,src,"TAP")
r=out.iloc[0]

assert r["Provider"]=="TAP"
assert r["Auth Code"]=="932768"
assert r["Provider Reference"]=="932768"
assert r["POS Payment"]=="MADA"
assert r["POS Date"].strftime("%Y-%m-%d")=="2026-08-03"

# Same provider, different scheme.
raw2=raw.copy()
raw2.loc[0,"reference_order"]="123456"
raw2.loc[0,"payment_scheme"]="VISA"
out2=core.normalize_pos(raw2,src,"TAP")
assert out2.iloc[0]["Auth Code"]=="123456"
assert out2.iloc[0]["POS Payment"]=="VISA"
assert out2.iloc[0]["Provider"]=="TAP"

print("TAP REFERENCE/PAYMENT SCHEME REGRESSION PASS")

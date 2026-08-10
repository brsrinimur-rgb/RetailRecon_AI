from pathlib import Path
import importlib.util, pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_tap",root/"core.py")
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

src="charge_2608100931_283731_260801_to_260809.csv"

for raw,expected in {
    "08/03/2026":"2026-08-03",
    "08/08/2026":"2026-08-08",
    "09/08/2026":"2026-08-09",
    "2026-08-05":"2026-08-05",
}.items():
    got=core.parse_provider_date(raw,src,"TAP")
    assert got.strftime("%Y-%m-%d")==expected,(raw,got,expected)

raw=pd.DataFrame([{
    "transaction date":"08/03/2026",
    "posting date":"08/03/2026",
    "auth code":"932768",
    "amount":617.40,
    "net amount":609.15,
    "commission":7.17,
    "payment type":"DEBIT",
    "merchant id":"283731",
}])
out=core.normalize_pos(raw,src,"TAP")
assert out.iloc[0]["POS Date"].strftime("%Y-%m-%d")=="2026-08-03"

print("TAP DATE REGRESSION PASS")

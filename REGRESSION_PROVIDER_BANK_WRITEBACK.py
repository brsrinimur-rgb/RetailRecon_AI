from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("bsv",root/"bank_settlement_final.py")
bsv=importlib.util.module_from_spec(spec);spec.loader.exec_module(bsv)

matched=pd.DataFrame([
    {"Payment Type":"TAP","Provider Reference":"chg1","Provider Order Reference":"","Bank Settled":False},
    {"Payment Type":"TABBY","Provider Reference":"pay1","Provider Order Reference":"3133343","Bank Settled":False},
    {"Payment Type":"TAMARA","Provider Reference":"tam1","Provider Order Reference":"MO100","Bank Settled":False},
])

for provider,refs in [
    ("TAP","chg1"),
    ("TABBY","3133343"),
    ("TAMARA","MO100"),
]:
    v=pd.DataFrame([{
        "Provider":provider,"Provider References":refs,
        "Bank Settled":True,"Bank Date":pd.Timestamp("2026-07-20"),
        "Actual Bank Credit":100.0,"Settlement Status":"Bank Verified"
    }])
    matched=bsv.apply_provider_verification_to_matched(matched,v,provider)

assert bool(matched.loc[matched["Payment Type"]=="TAP","Bank Settled"].iloc[0])
assert bool(matched.loc[matched["Payment Type"]=="TABBY","Bank Settled"].iloc[0])
assert bool(matched.loc[matched["Payment Type"]=="TAMARA","Bank Settled"].iloc[0])
print("PROVIDER BANK WRITE-BACK TEST PASS")

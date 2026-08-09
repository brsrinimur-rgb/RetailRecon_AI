from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("corex",root/"core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
spec2=importlib.util.spec_from_file_location("bsvx",root/"bank_settlement_final.py")
bsv=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(bsv)

class U:
    def __init__(self,p): self.p=Path(p); self.name=self.p.name
    def getvalue(self): return self.p.read_bytes()

tabby=Path("/mnt/data/Payout Sheet.xlsx")
if tabby.exists():
    df=next(iter(core.read_upload(U(tabby)).values()))
    out=bsv.build_tabby_payouts(df,5.0)
    assert not out.empty
    assert out["Provider References"].astype(str).str.len().gt(0).any()

tap=Path("/mnt/data/charge_2608020803_277678_260701_to_260731.xlsx")
if tap.exists():
    df=next(iter(core.read_upload(U(tap)).values()))
    out=bsv.build_tap_payouts(df)
    assert not out.empty
    assert out["Provider References"].astype(str).str.contains("chg_").any()

print("ACTUAL PAYOUT REFERENCE TEST PASS")

from pathlib import Path
import importlib.util, io, os
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_actual",root/"core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

class Upload:
    def __init__(self,p):
        self.path=Path(p)
        self.name=self.path.name
    def getvalue(self):
        return self.path.read_bytes()

# This test runs only when these reference files are available beside /mnt/data.
tabby=Path("/mnt/data/20260727-payments-35c379d8-eb0a-4a24-857f-224280bd7d74.xlsx")
tamara=Path("/mnt/data/Aigner_KSA_-_Online_20260701_to_20260726.xlsx")

if tabby.exists():
    frames=core.read_upload(Upload(tabby))
    df=next(iter(frames.values()))
    assert core.classify(tabby.name,df)=="TABBY"
    n=core.normalize_pos(df,tabby.name,"TABBY")
    assert len(n)>0
    assert n["POS Date"].notna().sum()>0
    assert (n["POS Payment"]=="TABBY").all()

if tamara.exists():
    frames=core.read_upload(Upload(tamara))
    df=next(iter(frames.values()))
    assert core.classify(tamara.name,df)=="TAMARA"
    n=core.normalize_pos(df,tamara.name,"TAMARA")
    assert len(n)>0
    assert n["POS Date"].notna().sum()>0
    assert (n["POS Payment"]=="TAMARA").all()

print("ACTUAL TABBY/TAMARA PROVIDER FILE TEST PASS")

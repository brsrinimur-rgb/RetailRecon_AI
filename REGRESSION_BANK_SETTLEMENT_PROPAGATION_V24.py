from pathlib import Path
import sys,io,pandas as pd,importlib.util
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))

import core
from logic import bank_settlement_extension as ext

class UploadBytes(io.BytesIO):
    def __init__(self,path):
        self.name=Path(path).name
        super().__init__(Path(path).read_bytes())
    def getvalue(self): return super().getvalue()

anb_path=Path("/mnt/data/ACC_0108095820370014_2026-08-02-084639231 - Final(1).xlsx")
rajhi_path=Path("/mnt/data/Statements - 3439(1).xlsx")
assert anb_path.exists() and rajhi_path.exists()

anb_parts=[]
for sh,df in core.read_upload(UploadBytes(anb_path)).items():
    x=ext.normalize_bank_statement(df,anb_path.name)
    if not x.empty: anb_parts.append(x)
anb=pd.concat(anb_parts,ignore_index=True)
assert len(anb)>1000
assert round(anb.loc[anb["Credit"]>0,"Credit"].sum(),2)==7690111.56
assert ((anb["Narration Terminal ID"]=="55610715") & (anb["Narration Scheme"]=="VISA")).any()

rajhi_parts=[]
for sh,df in core.read_upload(UploadBytes(rajhi_path)).items():
    x=ext.normalize_bank_statement(df,rajhi_path.name)
    if not x.empty: rajhi_parts.append(x)
rajhi=pd.concat(rajhi_parts,ignore_index=True)
assert round(rajhi.loc[rajhi["Credit"]>0,"Credit"].sum(),2)==9421448.48
assert int((rajhi["Provider"]=="TABBY").sum())==51
assert int((rajhi["Provider"]=="TAMARA").sum())==8
assert int((rajhi["Provider"]=="TAP").sum())==31

# Real ANB evidence row:
# 01-Jul bank credit SAR 6,567.01 for terminal 55610715,
# source date 30-Jun-2026, VISA, TX_12.
matched=pd.DataFrame([
    {
        "Unique Transaction ID":f"U{i}",
        "Store Code":"TEST",
        "Payment Type":"VISA",
        "POS Date":pd.Timestamp("2026-06-30"),
        "Terminal ID":"55610715",
        "POS Amount":6687.88/12,
        "Net Amount":6567.01/12,
        "Commission":105.09/12,
        "VAT":15.78/12,
        "D365 Amount":6687.88/12,
        "Bank Settled":False,
    } for i in range(12)
])
batches=core.build_card_settlement_batches(matched)
assert len(batches)==1
res,_=ext.reconcile_card_batches_to_anb(batches,anb,1.0)
assert len(res)==1,res
assert res.iloc[0]["Settlement Status"]=="BANK RECEIVED",res.iloc[0].to_dict()
assert round(float(res.iloc[0]["Actual Bank Amount"]),2)==6567.01

upd=ext.propagate_verified_batches(matched,res)
assert upd["Bank Settled"].all()
assert set(upd["Settlement Stage"])=={"BANK RECEIVED"}

print("BANK SETTLEMENT PROPAGATION V24 PASS")

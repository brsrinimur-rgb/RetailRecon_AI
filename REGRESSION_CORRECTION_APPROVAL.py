from pathlib import Path
import importlib.util, tempfile, os
import pandas as pd

root=Path(__file__).resolve().parent

# Load db/core from project.
spec=importlib.util.spec_from_file_location("db_corr",root/"db.py")
db=importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

spec2=importlib.util.spec_from_file_location("core_corr",root/"core.py")
core=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(core)

# Use isolated DB.
tmp=Path(tempfile.gettempdir())/"retailrecon_corr_regression.db"
for suffix in ["","-wal","-shm"]:
    p=Path(str(tmp)+suffix)
    if p.exists(): p.unlink()
db.DB_PATH=tmp
db.init_db()

tender=pd.DataFrame([{
    "D365 Row":65,
    "Store Code":"601",
    "Date":pd.Timestamp("2026-08-05"),
    "Receipt ID":"R65",
    "Auth Code":"111111",
    "D365 Payment":"MADA",
    "D365 Amount":186.00,
    "D365 Duplicate":False,
    "Unique Transaction ID":"u65",
}])

# Maker submits.
db.append_correction_log(
    65,"478688","Wrong authcode","maker",
    original_auth="111111",store_code="601",receipt_id="R65"
)
pending=db.load_correction_log("PENDING APPROVAL")
assert len(pending)==1
cid=int(pending.iloc[0]["ID"])

# Maker cannot approve own request.
ok,msg=db.decide_correction(cid,"APPROVED","maker","")
assert not ok
assert "cannot" in msg.lower()

# Checker approves.
ok,msg=db.decide_correction(cid,"APPROVED","checker","Evidence checked")
assert ok,msg

approved=db.load_approved_corrections()
assert len(approved)==1
assert approved.iloc[0]["Approver"]=="checker"

# Approved correction becomes effective, original remains preserved.
fixed=db.apply_approved_corrections(tender)
assert fixed.iloc[0]["Auth Code"]=="478688"
assert fixed.iloc[0]["Original Auth Code"]=="111111"
assert str(fixed.iloc[0]["Auth Correction Approved By"])=="checker"

# Matching now succeeds against corrected POS auth.
pos=pd.DataFrame([{
    "POS Row":1,"Source File":"POS.xlsx","POS Store":"601",
    "POS Date":pd.Timestamp("2026-08-05"),"Posting Date":pd.Timestamp("2026-08-05"),
    "Auth Code":"478688","POS Payment":"MADA","POS Amount":186.0,
    "Net Amount":186.0,"Commission":0.0,"VAT":0.0,"Terminal ID":"T1",
    "Merchant ID":"","Account":"","ARN":"","Slip No":"","POS Duplicate":False,
    "Settlement Delay Days":0,
}])
matched,us,up=core.reconcile(fixed,pos,1.0)
assert len(matched)==1
assert us.empty
assert up.empty

print("CORRECTION APPROVAL REGRESSION PASS")

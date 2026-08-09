from pathlib import Path
import importlib.util, os
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("db_test",root/"db.py")
db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

def batch(name,acct):
    return pd.DataFrame([{
        "Journal Batch":name,"Journal batch number":name,"Line number":1,
        "Account":acct,"Debit":100.0,"Credit":100.0,"Balanced":True,
        "Validation Passed":True,"Approval Status":"PENDING",
        "D365 Status":"NOT POSTED","Voucher":""
    }])

db.replace_jv(batch("A","1015"))
db.update_jv_approval(["A"],"APPROVED")
db.update_jv_posting("A","V-A")

db.replace_jv(batch("B","1015"))
j=db.load_jv()
assert set(j["Journal Batch"])=={"A","B"}
a=j[j["Journal Batch"]=="A"].iloc[0]
assert a["Approval Status"]=="APPROVED"
assert a["D365 Status"]=="POSTED"
assert a["Voucher"]=="V-A"

try:
    db.replace_jv(batch("A","9999"))
    raise AssertionError("Posted batch overwrite must be blocked.")
except ValueError:
    pass

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
print("JV HISTORY PERSISTENCE TEST PASS")

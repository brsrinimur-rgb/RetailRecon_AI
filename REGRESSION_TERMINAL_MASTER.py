from pathlib import Path
import importlib.util, os
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("db_test",root/"db.py")
db=importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

# Multiple terminals for one store: allowed.
valid=pd.DataFrame([
    {"Terminal ID":"55610682","Store Code":"601"},
    {"Terminal ID":"55610683","Store Code":"601"},
])
db.save_terminal_master(valid,"replace",user="test")
assert len(db.load_terminal_master())==2

# Same terminal + same store: accepted and collapsed.
same=pd.DataFrame([
    {"Terminal ID":"55610682","Store Code":"601"},
    {"Terminal ID":"55610682","Store Code":"601"},
])
db.save_terminal_master(same,"replace",user="test")
loaded=db.load_terminal_master()
assert len(loaded)==1
assert loaded.iloc[0]["Store Code"]=="601"

# Same terminal + different stores: rejected.
bad=pd.DataFrame([
    {"Terminal ID":"55610682","Store Code":"601"},
    {"Terminal ID":"55610682","Store Code":"603"},
])
try:
    db.save_terminal_master(bad,"replace",user="test")
    raise AssertionError("Conflict was not rejected")
except ValueError:
    pass

spec2=importlib.util.spec_from_file_location("core_test",root/"core.py")
core=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(core)

pos=pd.DataFrame([{
    "POS Store":"",
    "Terminal ID":"55610682",
    "Merchant ID":"999",
    "Merchant Mapping Required":True,
    "POS Payment":"MADA",
    "POS Date":pd.Timestamp("2026-07-01"),
    "Posting Date":pd.Timestamp("2026-07-02"),
    "Auth Code":"123456",
    "POS Amount":100.0,
    "Net Amount":99.0,
    "Commission":0.5,
    "VAT":0.075,
    "Source File":"x.xlsx",
    "POS Duplicate":False,
    "Settlement Delay Days":1,
}])
tm=pd.DataFrame([{"Terminal ID":"55610682","Store Code":"601"}])
mapped=core.apply_terminal_master(pos,tm)
assert mapped.iloc[0]["POS Store"]=="601"
assert bool(mapped.iloc[0]["Merchant Mapping Required"]) is False

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)

print("TERMINAL MASTER BUSINESS RULES PASS")

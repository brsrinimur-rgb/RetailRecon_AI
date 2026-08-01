from pathlib import Path
import importlib.util
import pandas as pd

r=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("core_test",r/"core.py")
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

# Case 1: confirmed exact match must match.
t=pd.DataFrame([{"D365 Row":1,"Store Code":"601","Date":pd.Timestamp("2026-07-06"),
"Receipt ID":"601601011017644","Auth Code":"075304","D365 Payment":"MASTERCARD",
"D365 Amount":1260.0,"D365 Duplicate":False,"Unique Transaction ID":"CASE601"}])
p=pd.DataFrame([{"POS Row":1,"Source File":"x.xlsx","POS Store":"601","POS Date":pd.Timestamp("2026-07-06"),
"Posting Date":pd.Timestamp("2026-07-06"),"Auth Code":"075304","POS Payment":"MASTERCARD",
"POS Amount":1260.0,"Net Amount":1260.0,"Commission":0.0,"VAT":0.0,"Terminal ID":"55610716",
"POS Duplicate":False,"Settlement Delay Days":0}])
m,u,up=core.reconcile(t,p,1.0)
assert len(m)==1 and u.empty and up.empty

# Case 2: generic merchant + unknown terminal must become Terminal Mapping Required.
raw=pd.DataFrame([{"POS Store":"UNITED LUXURY CORP","Terminal ID":"55610683","POS Payment":"MADA",
"POS Date":pd.Timestamp("2026-07-04"),"Posting Date":pd.Timestamp("2026-07-04"),
"Auth Code":"3595720","POS Amount":27962.0,"Net Amount":27962.0,"Commission":0.0,"VAT":0.0,
"Source File":"x.xlsx","POS Duplicate":False,"Settlement Delay Days":0}])
tm=pd.DataFrame(columns=["Terminal ID","Store Code"])
mapped=core.apply_terminal_master(raw,tm)
assert mapped.iloc[0]["POS Store"]==""
assert bool(mapped.iloc[0]["Terminal Mapping Required"]) is True

empty_t=pd.DataFrame(columns=t.columns)
m,u,up=core.reconcile(empty_t,mapped,1.0)
# Empty tender returns POS unchanged, so mapping flag must survive.
assert bool(up.iloc[0]["Terminal Mapping Required"]) is True

# Case 3: same terminal becomes a real Store Code once master is uploaded.
tm2=pd.DataFrame([{"Terminal ID":"55610683","Store Code":"658"}])
mapped2=core.apply_terminal_master(raw,tm2)
assert mapped2.iloc[0]["POS Store"]=="658"
assert bool(mapped2.iloc[0]["Terminal Store Mapped"]) is True
assert bool(mapped2.iloc[0]["Terminal Mapping Required"]) is False

print("ALL REGRESSION TESTS PASS")

# ---------------------------------------------------------------------------
# Case 4: Merchant ID Master resolves store when Terminal ID is absent
# (TAP-style settlement files carry merchant_id but no terminal reference).
raw_mid = pd.DataFrame([{"POS Store":"","Terminal ID":"","Merchant ID":"34993479","POS Payment":"VISA",
    "POS Date":pd.Timestamp("2026-07-14"),"Posting Date":pd.Timestamp("2026-07-21"),
    "Auth Code":"61675","POS Amount":5860.0,"Net Amount":5725.16,"Commission":117.25,"VAT":17.59,
    "Source File":"tap.xlsx","POS Duplicate":False,"Settlement Delay Days":7}])
unresolved = core.apply_merchant_master(raw_mid, pd.DataFrame(columns=["Merchant ID","Store Code"]))
assert unresolved.iloc[0]["POS Store"] == ""
assert bool(unresolved.iloc[0]["Merchant Mapping Required"]) is True

mm = pd.DataFrame([{"Merchant ID":"34993479","Store Code":"606"}])
resolved = core.apply_merchant_master(raw_mid, mm)
assert resolved.iloc[0]["POS Store"] == "606"
assert bool(resolved.iloc[0]["Merchant Store Mapped"]) is True

# Terminal ID must always win over Merchant ID when both resolve.
raw_both = raw_mid.copy()
raw_both["Terminal ID"] = "55610686"
step1 = core.apply_merchant_master(raw_both, mm)              # -> 606 via merchant
tm = pd.DataFrame([{"Terminal ID":"55610686","Store Code":"601"}])
step2 = core.apply_terminal_master(step1, tm)                  # terminal must override
assert step2.iloc[0]["POS Store"] == "601"

# ---------------------------------------------------------------------------
# Case 5: JV persistence round-trip through the shared SQLite layer must
# preserve the full D365 export schema (this used to crash outright - see
# db.replace_jv/load_jv - "no such table: jv_batches").
import db
import os
if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
    db.init_db()  # DB_PATH removal deletes the schema too; recreate it

matched = pd.DataFrame([{
    "Unique Transaction ID":"u1","Store Code":"601","Date":pd.Timestamp("2026-07-06"),
    "Receipt ID":"R1","Auth Code":"075304","Payment Type":"MASTERCARD","D365 Amount":1260.0,
    "POS Amount":1260.0,"Net Amount":1250.0,"Commission":6.93,"VAT":1.04,"Difference":0.0,
    "Status":"Matched","Match Rule":"L1","POS Date":pd.Timestamp("2026-07-06"),
    "Posting Date":pd.Timestamp("2026-07-06"),"Settlement Delay Days":0,"Terminal ID":"T1",
    "Source File":"x.xlsx","D365 Duplicate":False,"POS Duplicate":False,"Bank Settled":True,
    "Bank Name":"ANB","Bank Date":pd.Timestamp("2026-07-07"),"Bank Amount":1250.0
}])
jv = core.create_jv(matched, gl=None, commission_master=None)
jv = core.validate_jv(jv, gl=None)
assert jv["Validation Passed"].all(), jv["Validation Errors"].unique()

db.replace_jv(jv)
loaded = db.load_jv()
assert len(loaded) == len(jv), "JV persistence lost rows"
assert "Ledger Dimension" in loaded.columns, "JV persistence lost the D365 export schema"
assert set(loaded["Ledger Dimension"]) == set(jv["Ledger Dimension"])
assert loaded["Validation Passed"].all()

os.remove(db.DB_PATH)

# ---------------------------------------------------------------------------
# Case 6: validate_jv() must block a corrupted batch (wrong GL account) and
# must pass a correctly generated one - a real control gate, not a decoration.
bad = jv.copy()
bad.loc[bad["Account type"]=="Bank","Main Account"]="9999"
bad_validated = core.validate_jv(bad, gl=None)
assert not bad_validated["Validation Passed"].any()
assert "Bank line" in bad_validated["Validation Errors"].iloc[0]

print("ALL EXTENDED REGRESSION TESTS PASS (Merchant Master, JV persistence, JV validation)")

# ---------------------------------------------------------------------------
# Case 7: GL mapping snapshot immunity. A JV batch validated at creation time
# must keep validating against the mapping it was CREATED with, even after
# GL Configuration is later changed - not against whatever config is live now.
snap_gl_a = dict(core.D365_JV_DEFAULTS)
jv_a = core.create_jv(matched, snap_gl_a, None)
jv_a = core.validate_jv(jv_a, snap_gl_a)
assert jv_a["Validation Passed"].all()
version_a = jv_a["Mapping Version"].iloc[0]

snap_gl_b = dict(snap_gl_a); snap_gl_b["BANK_ACCOUNT"] = "1099"  # a later, legitimate change
revalidated_a = core.validate_jv(jv_a, gl=None)  # no gl passed -> must use the batch's own snapshot
assert revalidated_a["Validation Passed"].all(), revalidated_a["Validation Errors"].unique()
assert revalidated_a["Mapping Version"].iloc[0] == version_a

jv_b = core.create_jv(matched, snap_gl_b, None)
jv_b = core.validate_jv(jv_b, snap_gl_b)
assert jv_b["Validation Passed"].all()
assert jv_b["Mapping Version"].iloc[0] != version_a
assert jv_b.loc[jv_b["Account type"]=="Bank","Main Account"].iloc[0] == "1099"

# ---------------------------------------------------------------------------
# Case 8: master-data upload validation must reject bad data outright and
# never partially apply it; clean changes must be logged with who/what.
if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

clean = pd.DataFrame([{"Terminal ID":"55610686","Store Code":"601"}])
res = db.save_terminal_master(clean, "merge", user="maker")
assert res["added"] == ["55610686"]

dupe = pd.DataFrame([{"Terminal ID":"1","Store Code":"601"},{"Terminal ID":"1","Store Code":"602"}])
try:
    db.save_terminal_master(dupe, "merge", user="maker")
    raise AssertionError("duplicate terminal upload should have been rejected")
except ValueError:
    pass

blank = pd.DataFrame([{"Terminal ID":"2","Store Code":""}])
try:
    db.save_terminal_master(blank, "merge", user="maker")
    raise AssertionError("blank store code upload should have been rejected")
except ValueError:
    pass

after_bad_uploads = db.load_terminal_master()
assert len(after_bad_uploads) == 1, "a rejected upload must not partially apply"

log = db.load_master_audit_log("terminal_master")
assert len(log) == 1 and log.iloc[0]["User"] == "maker"

os.remove(db.DB_PATH)

print("ALL EXTENDED REGRESSION TESTS (ROUND 2) PASS (GL snapshot immunity, master audit + validation)")

"""
REGRESSION_V40B_STORE_MASTER_SCHEMA_MIGRATION.py

Proves the store_mapping_master schema change (new column
d365_store_display_name) is genuinely additive/self-healing, matching the
same discipline already used for every other migration in db.py.

Run: python3 REGRESSION_V40B_STORE_MASTER_SCHEMA_MIGRATION.py
"""
from pathlib import Path
import sqlite3, shutil, tempfile, importlib.util, sys
import pandas as pd

src=Path(__file__).resolve().parent/"db.py"
tmp=Path(tempfile.mkdtemp(prefix="rr_v40b_"))
shutil.copy2(src,tmp/"db.py")
db_path=tmp/"retailrecon.db"

conn=sqlite3.connect(db_path)
conn.execute("""CREATE TABLE store_mapping_master (
    provider_store_name TEXT PRIMARY KEY,
    store_code TEXT,
    active TEXT,
    notes TEXT,
    updated_at TEXT
)""")
conn.execute(
    "INSERT INTO store_mapping_master(provider_store_name,store_code,active,notes,updated_at) "
    "VALUES ('AIGNER TAHLIA','601','Yes','legacy row','2026-01-01T00:00:00')"
)
conn.commit()
conn.close()

spec=importlib.util.spec_from_file_location("dbv40b",tmp/"db.py")
mod=importlib.util.module_from_spec(spec); sys.modules["dbv40b"]=mod
spec.loader.exec_module(mod)

conn=sqlite3.connect(db_path)
cols={r[1] for r in conn.execute("PRAGMA table_info(store_mapping_master)").fetchall()}
assert "d365_store_display_name" in cols, cols
row=conn.execute(
    "SELECT provider_store_name,store_code,active FROM store_mapping_master WHERE provider_store_name='AIGNER TAHLIA'"
).fetchone()
assert row==("AIGNER TAHLIA","601","Yes"), "existing legacy row must survive the migration untouched"
conn.close()
print("[PASS] d365_store_display_name column added to an existing table without touching "
      "the pre-existing legacy row -- additive/self-healing, same as every other migration here.")

loaded=mod.load_store_mapping_master()
assert "D365 Store Display Name" in loaded.columns
legacy=loaded[loaded["Provider Store Name"]=="AIGNER TAHLIA"].iloc[0]
assert legacy["D365 Store Display Name"] in (None,"") or pd.isna(legacy["D365 Store Display Name"])
print("[PASS] load_store_mapping_master() exposes the new column; the pre-existing legacy "
      "row correctly comes back with it blank, not an error.")

good_upload=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
])
result=mod.save_store_mapping_master(good_upload,mode="merge",user="tester")
assert result is not None
reloaded=mod.load_store_mapping_master()
names=set(reloaded.loc[reloaded["Store Code"]=="628","D365 Store Display Name"])
assert names=={"Aigner Panorama Mall"}
print("[PASS] save_store_mapping_master() accepts and correctly persists a multi-alias save "
      "where active rows agree on D365 Store Display Name.")

bad_upload=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA V2","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"TYPO ROW","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorma Mall","Active":"Yes"},
])
raised=False
try:
    mod.save_store_mapping_master(bad_upload,mode="merge",user="tester")
except ValueError as e:
    raised=True
    assert "628" in str(e)
    assert "distinct active D365 Store Display Name" in str(e)
assert raised, "save must reject conflicting active D365 Store Display Names for the same store code"
print("[PASS] save_store_mapping_master() correctly REJECTS a save with genuinely conflicting "
      "active D365 Store Display Names for the same Store Code, at save time.")

ok_with_inactive_conflict=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA V3","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"OLD RETIRED","Store Code":"628",
     "D365 Store Display Name":"Some Old Wrong Name","Active":"No"},
])
result2=mod.save_store_mapping_master(ok_with_inactive_conflict,mode="merge",user="tester")
assert result2 is not None
print("[PASS] An inactive row with a conflicting D365 Store Display Name does NOT trigger "
      "the save-time rejection -- only active rows are checked for agreement.")

h=mod.get_database_health()
assert h["Healthy"] is True, h
print("[PASS] Database health remains HEALTHY after this migration.")

# ---------------------------------------------------------------------
# 6. THE MERGE-STATE GAP FLAGGED IN REVIEW: an incoming merge upload that
#    looks conflict-free BY ITSELF can still introduce a conflict against
#    an existing active row already in the database (a different Provider
#    Store Name key, so the upsert doesn't touch it). This must be
#    rejected BEFORE writing, not discovered later when JV validation
#    fails closed. Confirms the database is left completely unchanged.
#
#    Uses a FRESH, isolated temp database so this scenario isn't polluted
#    by the store-628 rows already written in steps 3-5 above.
# ---------------------------------------------------------------------
tmp2=Path(tempfile.mkdtemp(prefix="rr_v40b_merge_"))
shutil.copy2(src,tmp2/"db.py")
db_path2=tmp2/"retailrecon.db"
spec2=importlib.util.spec_from_file_location("dbv40b_merge",tmp2/"db.py")
mod2=importlib.util.module_from_spec(spec2); sys.modules["dbv40b_merge"]=mod2
mod2.DB_PATH=db_path2
spec2.loader.exec_module(mod2)
mod2.init_db()

seed=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
])
mod2.save_store_mapping_master(seed,mode="merge",user="tester")
before_state=mod2.load_store_mapping_master()
assert set(before_state.loc[before_state["Store Code"]=="628","D365 Store Display Name"])=={"Aigner Panorama Mall"}

conflicting_merge=pd.DataFrame([
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Riyadh","Active":"Yes"},
])
raised=False
try:
    mod2.save_store_mapping_master(conflicting_merge,mode="merge",user="tester")
except ValueError as e:
    raised=True
    assert "628" in str(e)
    assert "resulting final state" in str(e)
assert raised, (
    "REGRESSION: a merge upload that conflicts with an EXISTING active row (not touched by "
    "this upload's own keys) must be rejected -- checking the upload in isolation is not enough"
)

after_state=mod2.load_store_mapping_master()
assert set(after_state["Provider Store Name"])==set(before_state["Provider Store Name"]), (
    "database must be completely unchanged after a rejected save -- no partial write"
)
assert set(after_state.loc[after_state["Store Code"]=="628","D365 Store Display Name"])=={"Aigner Panorama Mall"}
print("[PASS] Merge-state gap fixed: a new alias row that individually looks conflict-free but "
      "would conflict with an EXISTING active row already in the database is correctly rejected "
      "BEFORE writing. Database confirmed completely unchanged after rejection -- no partial write.")

agreeing_merge=pd.DataFrame([
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
])
mod2.save_store_mapping_master(agreeing_merge,mode="merge",user="tester")
final_state=mod2.load_store_mapping_master()
assert set(final_state.loc[final_state["Store Code"]=="628","Provider Store Name"])=={
    "AIGNER PANORAMA","PANORAMA PAYMENT LINKS"
}
assert set(final_state.loc[final_state["Store Code"]=="628","D365 Store Display Name"])=={"Aigner Panorama Mall"}
print("[PASS] A new alias row that AGREES with the existing active row merges successfully -- "
      "the merge-state check correctly distinguishes agreement from conflict.")

print("REGRESSION V40B STORE MASTER SCHEMA MIGRATION PASS")

# ---------------------------------------------------------------------
# 7. NORMALIZATION-PARITY GAP FLAGGED IN REVIEW, ROUND 2: the merge-state
#    validation simulation must apply the EXACT SAME normalization the
#    write loop applies, or a row that normalizes into a conflict at
#    write time can slip past validation looking conflict-free.
#
#    Case A: Store Code ".0" artifact. Existing "628" + incoming "628.0"
#    must be recognized as the SAME store code during validation, exactly
#    as they become the same code at write time.
# ---------------------------------------------------------------------
tmp3=Path(tempfile.mkdtemp(prefix="rr_v40b_norm_"))
shutil.copy2(src,tmp3/"db.py")
db_path3=tmp3/"retailrecon.db"
spec3=importlib.util.spec_from_file_location("dbv40b_norm",tmp3/"db.py")
mod3=importlib.util.module_from_spec(spec3); sys.modules["dbv40b_norm"]=mod3
mod3.DB_PATH=db_path3
spec3.loader.exec_module(mod3)
mod3.init_db()

seed_a=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Canonical Name A","Active":"Yes"},
])
mod3.save_store_mapping_master(seed_a,mode="merge",user="tester")

dotzero_conflict=pd.DataFrame([
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628.0",
     "D365 Store Display Name":"Canonical Name B","Active":"Yes"},
])
raised=False
try:
    mod3.save_store_mapping_master(dotzero_conflict,mode="merge",user="tester")
except ValueError as e:
    raised=True
    assert "628" in str(e)
assert raised, (
    "REGRESSION: Store Code '628.0' must be recognized as the same code as existing '628' "
    "during validation -- the write-time normalization ('628.0' -> '628') must be mirrored "
    "in the pre-save check, or this conflict slips through and persists."
)
state=mod3.load_store_mapping_master()
assert set(state["Provider Store Name"])=={"AIGNER PANORAMA"}, "database must be unchanged after rejection"
print("[PASS] Store Code '.0' normalization parity: existing '628' + incoming '628.0' with a "
      "different display name is correctly rejected during validation, matching what would "
      "happen at write time -- database confirmed unchanged.")

# Confirm the '.0' row DOES succeed and correctly lands as '628' when it agrees.
dotzero_agree=pd.DataFrame([
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628.0",
     "D365 Store Display Name":"Canonical Name A","Active":"Yes"},
])
mod3.save_store_mapping_master(dotzero_agree,mode="merge",user="tester")
state2=mod3.load_store_mapping_master()
assert set(state2.loc[state2["Provider Store Name"]=="PANORAMA PAYMENT LINKS","Store Code"])=={"628"}, (
    "the '.0' suffix must be stripped at persistence, landing as '628' not '628.0'"
)
print("[PASS] An agreeing '628.0' row correctly persists as Store Code '628' (suffix stripped), "
      "consistent with the write-time normalization.")

# ---------------------------------------------------------------------
# Case B: blank Active. A blank/NaN Active value defaults to "Yes" at
# write time -- the validation simulation must treat it as active too,
# or a blank-Active conflicting row can be excluded from the ambiguity
# check yet persist as active.
# ---------------------------------------------------------------------
tmp4=Path(tempfile.mkdtemp(prefix="rr_v40b_norm2_"))
shutil.copy2(src,tmp4/"db.py")
db_path4=tmp4/"retailrecon.db"
spec4=importlib.util.spec_from_file_location("dbv40b_norm2",tmp4/"db.py")
mod4=importlib.util.module_from_spec(spec4); sys.modules["dbv40b_norm2"]=mod4
mod4.DB_PATH=db_path4
spec4.loader.exec_module(mod4)
mod4.init_db()

seed_b=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Canonical Name A","Active":"Yes"},
])
mod4.save_store_mapping_master(seed_b,mode="merge",user="tester")

blank_active_conflict=pd.DataFrame([
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628",
     "D365 Store Display Name":"Canonical Name B","Active":None},
])
raised2=False
try:
    mod4.save_store_mapping_master(blank_active_conflict,mode="merge",user="tester")
except ValueError as e:
    raised2=True
    assert "628" in str(e)
assert raised2, (
    "REGRESSION: a row with a BLANK Active value defaults to 'Yes' at write time -- the "
    "validation simulation must treat it as active too, or a conflicting blank-Active row "
    "is excluded from the ambiguity check yet persists as active anyway."
)
state3=mod4.load_store_mapping_master()
assert set(state3["Provider Store Name"])=={"AIGNER PANORAMA"}, "database must be unchanged after rejection"
print("[PASS] Blank-Active normalization parity: a new row with a BLANK Active value (which "
      "defaults to active at write time) conflicting with an existing active row is correctly "
      "rejected during validation -- database confirmed unchanged.")

print("REGRESSION V40B STORE MASTER SCHEMA MIGRATION PASS (including normalization-parity round 2)")

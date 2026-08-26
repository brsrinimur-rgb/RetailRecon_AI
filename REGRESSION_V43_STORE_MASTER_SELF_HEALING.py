"""
REGRESSION_V43_STORE_MASTER_SELF_HEALING.py

Reproduces the exact production error reported and proves the fix.
Same class of bug, same fix pattern, as V20's correction_log self-healing.

Run: python3 REGRESSION_V43_STORE_MASTER_SELF_HEALING.py
"""
from pathlib import Path
import sqlite3, shutil, tempfile, importlib.util, sys
import pandas as pd

src=Path(__file__).resolve().parent/"db.py"

tmp=Path(tempfile.mkdtemp(prefix="rr_v43_"))
shutil.copy2(src,tmp/"db.py")
db_path=tmp/"retailrecon.db"

spec=importlib.util.spec_from_file_location("dbv43_repro",tmp/"db.py")
mod=importlib.util.module_from_spec(spec); sys.modules["dbv43_repro"]=mod
mod.DB_PATH=db_path
spec.loader.exec_module(mod)

conn=sqlite3.connect(db_path)
conn.execute("ALTER TABLE store_mapping_master RENAME TO store_mapping_master_new")
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
conn.execute("DROP TABLE store_mapping_master_new")
conn.commit()
conn.close()

cols={r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(store_mapping_master)").fetchall()}
assert "d365_store_display_name" not in cols, "test setup failed"
print("[SETUP] Old-shape store_mapping_master table confirmed, reproducing a real pre-existing DB.")

conn2=sqlite3.connect(db_path)
raised=False
try:
    pd.read_sql_query(
        """SELECT provider_store_name AS "Provider Store Name",
                  store_code AS "Store Code",
                  d365_store_display_name AS "D365 Store Display Name",
                  active AS "Active", notes AS "Notes", updated_at AS "Updated At"
           FROM store_mapping_master ORDER BY provider_store_name""",
        conn2
    )
except Exception as e:
    raised=True
    assert "d365_store_display_name" in str(e) or "no such column" in str(e).lower()
conn2.close()
assert raised, "the raw query against an old-shape table must fail"
print("[CONFIRMED BUG] Raw SELECT against the old-shape table fails exactly like the "
      "production traceback.")

result=mod.load_store_mapping_master()
assert "D365 Store Display Name" in result.columns
legacy_row=result[result["Provider Store Name"]=="AIGNER TAHLIA"].iloc[0]
assert legacy_row["Store Code"]=="601"
print("[FIXED] load_store_mapping_master() self-heals the old-shape table automatically.")

cols_after={r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(store_mapping_master)").fetchall()}
assert "d365_store_display_name" in cols_after
print("[PASS] The column genuinely exists in the database after the self-heal.")

tmp2=Path(tempfile.mkdtemp(prefix="rr_v43_save_"))
shutil.copy2(src,tmp2/"db.py")
db_path2=tmp2/"retailrecon.db"
spec2=importlib.util.spec_from_file_location("dbv43_save",tmp2/"db.py")
mod2=importlib.util.module_from_spec(spec2); sys.modules["dbv43_save"]=mod2
mod2.DB_PATH=db_path2
spec2.loader.exec_module(mod2)

conn3=sqlite3.connect(db_path2)
conn3.execute("ALTER TABLE store_mapping_master RENAME TO store_mapping_master_new")
conn3.execute("""CREATE TABLE store_mapping_master (
    provider_store_name TEXT PRIMARY KEY, store_code TEXT, active TEXT, notes TEXT, updated_at TEXT
)""")
conn3.execute("DROP TABLE store_mapping_master_new")
conn3.commit()
conn3.close()

new_row=pd.DataFrame([{
    "Provider Store Name":"TAG HEUER RASHID MALL","Store Code":"628",
    "D365 Store Display Name":"Tag Heuer Rashid Mall","Active":"Yes",
}])
mod2.save_store_mapping_master(new_row,mode="merge",user="tester")
reloaded=mod2.load_store_mapping_master()
assert set(reloaded.loc[reloaded["Store Code"]=="628","D365 Store Display Name"])=={"Tag Heuer Rashid Mall"}
print("[FIXED] save_store_mapping_master() also self-heals an old-shape table before writing.")

print("REGRESSION V43 STORE MASTER SELF-HEALING PASS")

from pathlib import Path
import sqlite3, shutil, tempfile, importlib.util, sys

src=Path(__file__).resolve().parent/"db.py"
tmp=Path(tempfile.mkdtemp(prefix="rr_db_migration_"))
shutil.copy2(src,tmp/"db.py")

# Simulate the old production database that only had the original correction_log columns.
db_path=tmp/"retailrecon.db"
conn=sqlite3.connect(db_path)
conn.execute("""CREATE TABLE correction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT,
    d365_row INTEGER,
    new_auth TEXT,
    reason TEXT,
    user TEXT,
    status TEXT
)""")
conn.execute("""INSERT INTO correction_log
    (time,d365_row,new_auth,reason,user,status)
    VALUES ('2026-08-01T10:00:00',1,'006631','legacy','maker','APPROVED')""")
conn.commit()
conn.close()

spec=importlib.util.spec_from_file_location("db_migration_test",tmp/"db.py")
mod=importlib.util.module_from_spec(spec)
sys.modules["db_migration_test"]=mod
spec.loader.exec_module(mod)

conn=sqlite3.connect(db_path)
cols={r[1] for r in conn.execute("PRAGMA table_info(correction_log)").fetchall()}
expected={"original_auth","store_code","receipt_id","approver","approval_time","approval_comment"}
assert expected.issubset(cols),(expected-cols)
row=conn.execute("SELECT new_auth,status FROM correction_log WHERE id=1").fetchone()
assert row==("006631","APPROVED"),row
conn.close()

# The formerly failing query must now run on the migrated legacy DB.
df=mod.load_correction_log("APPROVED")
assert len(df)==1
assert "Store Code" in df.columns and "Receipt ID" in df.columns
assert df.iloc[0]["New Auth"]=="006631"

print("DB SCHEMA MIGRATION V19 PASS")

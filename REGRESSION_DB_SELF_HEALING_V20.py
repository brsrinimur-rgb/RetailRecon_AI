from pathlib import Path
import sqlite3, shutil, tempfile, importlib.util, sys
src=Path(__file__).resolve().parent/"db.py"
tmp=Path(tempfile.mkdtemp(prefix="rr_db_selfheal_"))
shutil.copy2(src,tmp/"db.py")
db_path=tmp/"retailrecon.db"

# Legacy schema.
conn=sqlite3.connect(db_path)
conn.execute("""CREATE TABLE correction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT,d365_row INTEGER,new_auth TEXT,reason TEXT,user TEXT,status TEXT
)""")
conn.execute("""INSERT INTO correction_log
(time,d365_row,new_auth,reason,user,status)
VALUES ('2026-08-01T10:00:00',1,'006631','legacy','maker','APPROVED')""")
conn.commit();conn.close()

spec=importlib.util.spec_from_file_location("db_selfheal",tmp/"db.py")
mod=importlib.util.module_from_spec(spec);sys.modules["db_selfheal"]=mod
spec.loader.exec_module(mod)

# Recreate legacy table AFTER import to prove query-time self-healing.
conn=sqlite3.connect(db_path)
conn.execute("DROP TABLE correction_log")
conn.execute("""CREATE TABLE correction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT,d365_row INTEGER,new_auth TEXT,reason TEXT,user TEXT,status TEXT
)""")
conn.execute("""INSERT INTO correction_log
(time,d365_row,new_auth,reason,user,status)
VALUES ('2026-08-01T10:00:00',1,'006631','legacy','maker','APPROVED')""")
conn.commit();conn.close()

df=mod.load_correction_log("APPROVED")
assert len(df)==1
assert df.iloc[0]["New Auth"]=="006631"
assert "Store Code" in df.columns
assert "Receipt ID" in df.columns

conn=sqlite3.connect(db_path)
cols={r[1] for r in conn.execute("PRAGMA table_info(correction_log)").fetchall()}
for c in ["original_auth","store_code","receipt_id","approver","approval_time","approval_comment"]:
    assert c in cols,c
conn.close()

print("DB SELF-HEALING V20 PASS")

from pathlib import Path
import sqlite3,shutil,tempfile,importlib.util,sys

src=Path(__file__).resolve().parent/"db.py"
tmp=Path(tempfile.mkdtemp(prefix="rr_v21_"))
shutil.copy2(src,tmp/"db.py")
path=tmp/"retailrecon.db"

conn=sqlite3.connect(path)
# Legacy correction table
conn.execute("""CREATE TABLE correction_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,d365_row INTEGER,
 new_auth TEXT,reason TEXT,user TEXT,status TEXT
)""")
conn.execute("""INSERT INTO correction_log(time,d365_row,new_auth,reason,user,status)
 VALUES('2026-08-01',1,'006631','legacy','maker','APPROVED')""")

# Legacy GL control table missing most V15+ columns
conn.execute("""CREATE TABLE gl_control_mapping(
 main_account TEXT PRIMARY KEY,
 gl_group TEXT
)""")
conn.execute("""INSERT INTO gl_control_mapping(main_account,gl_group)
 VALUES('11020907','CARD')""")
conn.commit();conn.close()

spec=importlib.util.spec_from_file_location("dbv21",tmp/"db.py")
mod=importlib.util.module_from_spec(spec);sys.modules["dbv21"]=mod
spec.loader.exec_module(mod)

# Exact production GL path that was failing must self-heal.
m=mod.load_gl_control_mapping()
assert not m.empty
assert set(["Main Account","GL Group","Payment Types","Account Name","Active","Notes","Updated At"]).issubset(m.columns)

# Correction path still works.
c=mod.load_correction_log("APPROVED")
assert len(c)==1 and "Store Code" in c.columns

h=mod.get_database_health()
assert h["Healthy"] is True,h
assert h["Schema Version"]==21

# Existing legacy records preserved.
conn=sqlite3.connect(path)
assert conn.execute("SELECT COUNT(*) FROM correction_log").fetchone()[0]==1
assert conn.execute("SELECT COUNT(*) FROM gl_control_mapping WHERE main_account='11020907'").fetchone()[0]==1
conn.close()

print("DATABASE MIGRATION FRAMEWORK V21 PASS")

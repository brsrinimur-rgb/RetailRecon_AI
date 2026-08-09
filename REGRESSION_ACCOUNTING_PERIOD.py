from pathlib import Path
import importlib.util, os
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("db_period", root/"db.py")
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

db.save_accounting_period_control(
    "ULC","2026-07-31","2026-08-01",
    "CLOSED / NEXT PERIOD OPEN","test","Jul close"
)

assert db.is_accounting_date_open("2026-07-31","ULC")[0] is False
assert db.is_accounting_date_open("2026-08-01","ULC")[0] is True

resolved = db.resolve_accounting_date("2026-07-31", None, "ULC")
assert resolved == pd.Timestamp("2026-08-01")
assert pd.Timestamp("2026-07-31").strftime("%b-%Y") == "Jul-2026"
assert resolved.strftime("%b-%Y") == "Aug-2026"

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)

print("ACCOUNTING PERIOD CARRY-FORWARD TEST PASS")

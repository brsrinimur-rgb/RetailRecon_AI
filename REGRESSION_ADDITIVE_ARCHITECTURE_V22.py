from pathlib import Path
import sys
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))

from logic import reconciliation_logic,settlement_logic,jv_logic,gl_control_logic,database_logic,store613_logic
from logic.release_guard import run_release_health

for mod in [
    reconciliation_logic,settlement_logic,jv_logic,gl_control_logic,database_logic,store613_logic
]:
    h=mod.engine_health()
    assert h.get("legacy_preserved") is True,h

r=run_release_health()
assert r["Healthy"] is True,r
d=database_logic.health()
assert d["Healthy"] is True,d

print("ADDITIVE ARCHITECTURE V22 PASS")

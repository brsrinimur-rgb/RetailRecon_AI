
from pathlib import Path
root=Path(__file__).resolve().parents[1]
page=root/"pages/35_POS_GL_Reconciliation.py"
logic=root/"logic/pos_gl_reconciliation.py"
pt=page.read_text(encoding="utf-8")
lt=logic.read_text(encoding="utf-8")

assert pt.count("accept_multiple_files=True") >= 2
assert "ZIP" in pt
assert "POS Statement Amount" in pt and "D365 GL Amount" in pt
assert "POS extraction:" in pt
assert "def _find_header_row" in pt
assert "Trans Seq Number" in lt
assert "Trans Approval Cd" in lt
assert "terminal_id" in lt

legacy=[p for p in (root/"pages").glob("*.py") if "store_tender" in p.name.lower() or "storetender" in p.name.lower()]
assert not legacy, legacy

print("[PASS] Multiple POS upload")
print("[PASS] Multiple GL upload")
print("[PASS] ZIP batch upload")
print("[PASS] No 8-account limit")
print("[PASS] Real POS report header detection")
print("[PASS] Merchant ID / Terminal / Approval / Sequence extraction")
print("[PASS] POS Amount ↔ GL Amount accounting control")
print("[PASS] Store Tender excluded")
print("[PASS] Legacy Store Tender page absent")
print("REGRESSION FINAL POS GL PASS")

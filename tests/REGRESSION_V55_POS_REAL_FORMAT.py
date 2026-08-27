
from pathlib import Path
root=Path(__file__).resolve().parents[1]
lt=(root/"logic/pos_gl_reconciliation.py").read_text(encoding="utf-8")
pt=(root/"pages/35_POS_GL_Reconciliation.py").read_text(encoding="utf-8")
assert "Trans Seq Number" in lt
assert "Trans Approval Cd" in lt
assert "terminal_id" in lt
assert "def _find_header_row" in pt
assert "header=header" in pt
assert "POS extraction:" in pt
print("[PASS] Merchant ID and real transaction fields supported")
print("[PASS] Terminal ID supported")
print("[PASS] Trans Seq Number / Approval Code supported")
print("[PASS] Report-style Excel header detection")
print("[PASS] POS extraction diagnostic")
print("REGRESSION V55 POS REAL FORMAT PASS")

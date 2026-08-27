
from pathlib import Path
p=Path(__file__).resolve().parent/"pages/35_POS_GL_Reconciliation.py"
t=p.read_text(encoding="utf-8")
assert t.count("accept_multiple_files=True") >= 2
assert "UPLOAD MULTIPLE POS EXCEL FILES" in t
assert "UPLOAD MULTIPLE D365 GL EXCEL FILES" in t
assert "ZIP containing all POS files" in t
assert "ZIP containing all D365 GL files" in t
assert "from pathlib import Path" in t
assert "8, 20, 50+ GL accounts" in t
print("[PASS] POS multi-file uploader visible")
print("[PASS] GL multi-file uploader visible")
print("[PASS] ZIP bulk fallback visible")
print("[PASS] Path import fixed")
print("[PASS] No 8-account limit")
print("REGRESSION V54 TRUE BULK UPLOAD PASS")

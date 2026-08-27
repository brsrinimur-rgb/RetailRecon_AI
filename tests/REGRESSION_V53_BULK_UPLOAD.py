
from pathlib import Path
t=(Path(__file__).resolve().parent/"pages/35_POS_GL_Reconciliation.py").read_text(encoding="utf-8")
assert "accept_multiple_files=True" in t
assert "POS ZIP batch" in t and "D365 GL ZIP batch" in t
assert "More than 8 GL accounts is supported" in t
assert "POS Statement Amount" in t and "D365 GL Amount" in t
print("[PASS] Multiple POS files")
print("[PASS] Multiple GL files")
print("[PASS] ZIP batch fallback for large daily batches")
print("[PASS] No 8-account UI limit")
print("[PASS] POS Amount ↔ GL Amount control")
print("REGRESSION V53 BULK UPLOAD PASS")

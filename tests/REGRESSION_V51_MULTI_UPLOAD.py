from pathlib import Path
p=Path(__file__).resolve().parent/"pages/35_POS_GL_Reconciliation.py"
t=p.read_text(encoding="utf-8")
assert t.count("accept_multiple_files=True") >= 2
assert "v51_pos" in t and "v51_gl" in t
assert "POS files selected" in t and "D365 GL files selected" in t
print("[PASS] POS uploader accepts multiple files")
print("[PASS] D365 GL uploader accepts multiple files")
print("[PASS] Selected-file manifest is visible")
print("REGRESSION V51 MULTI UPLOAD PASS")

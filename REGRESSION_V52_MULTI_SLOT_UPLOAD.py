from pathlib import Path
root=Path(__file__).resolve().parents[1]
pages=root/"pages"
legacy=[p for p in pages.glob("*.py") if "store_tender" in p.name.lower() or "storetender" in p.name.lower()]
assert not legacy, f"Legacy Store Tender page remains: {legacy}"
t=(pages/"35_POS_GL_Reconciliation.py").read_text(encoding="utf-8")
assert t.count("st.file_uploader(")>=2
assert "v52_pos_slots" in t and "v52_gl_slots" in t
assert "Add another POS file" in t and "Add another GL file" in t
assert "POS Statement Amount" in t and "D365 GL Amount" in t
print("[PASS] Separate POS upload slots")
print("[PASS] Separate GL upload slots")
print("[PASS] Add-another-file controls")
print("[PASS] Legacy Store Tender page removed")
print("[PASS] POS Amount / GL Amount control present")
print("REGRESSION V52 MULTI SLOT UPLOAD PASS")

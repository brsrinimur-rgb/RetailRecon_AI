
from pathlib import Path
root=Path(__file__).resolve().parents[1]
pages=root/"pages"
legacy=list(pages.glob("*Store_Tender*"))+list(pages.glob("*store_tender*"))
assert not legacy, f"Legacy Store Tender page still present: {legacy}"
page=(pages/"35_POS_GL_Reconciliation.py").read_text(encoding="utf-8")
assert "Store Tender is NOT used" in page
assert 's.get("GL Matched"' in page
assert "POS Statement Amount" in page and "D365 GL Amount" in page
print("[PASS] No legacy Store Tender page")
print("[PASS] POS → GL page uses current summary schema")
print("[PASS] POS Amount ↔ GL Amount control present")
print("REGRESSION V50 POS GL PAGE PASS")

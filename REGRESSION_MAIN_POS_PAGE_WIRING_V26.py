from pathlib import Path
import ast

root=Path(__file__).resolve().parent
page=root/"pages"/"1_POS_Reconciliation.py"
src=page.read_text(encoding="utf-8")
tree=ast.parse(src)

# Critical: bank_ext must be imported on the main POS page.
imports=[]
for n in ast.walk(tree):
    if isinstance(n,ast.ImportFrom):
        imports.append((n.module,[(a.name,a.asname) for a in n.names]))
assert any(
    mod=="logic" and any(name=="bank_settlement_extension" and alias=="bank_ext" for name,alias in names)
    for mod,names in imports
),imports

required=[
    "bank_ext.normalize_bank_statement",
    "bank_ext.reconcile_card_batches_advanced",
    "bank_ext.propagate_verified_batches",
    "bank_ext.settlement_blocker_summary",
]
for token in required:
    assert token in src,token

# Provider settlement must be reachable from main page too.
assert "reconcile_provider_batches_to_rajhi" in src
assert "provider_payout_batches" in src

print("MAIN POS PAGE WIRING V26 PASS")

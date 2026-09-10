from pathlib import Path

PAGE = Path("pages/1_POS_Reconciliation.py")
MODULE = Path("payment_method_mismatch_diagnostic.py")

if not PAGE.exists():
    raise SystemExit("ERROR: pages/1_POS_Reconciliation.py not found.")
if not MODULE.exists():
    raise SystemExit("ERROR: payment_method_mismatch_diagnostic.py must be in project root.")

text = PAGE.read_text(encoding="utf-8")
original = text

import_line = "from payment_method_mismatch_diagnostic import classify_payment_method_mismatch\n"
if import_line not in text:
    if "import pandas as pd\n" not in text:
        raise SystemExit("ERROR: pandas import not found. No change made.")
    text = text.replace("import pandas as pd\n", "import pandas as pd\n" + import_line, 1)

anchors = [
    "        matched, us, up = core.reconcile(tender, pos, tolerance)\n",
    "        matched,us,up=core.reconcile(tender,pos,tolerance)\n",
]
anchor = next((x for x in anchors if x in text), None)
if anchor is None:
    raise SystemExit("ERROR: core.reconcile line not found. No change made.")

call = (
    "\n        # Additive exception-label diagnostic only; matched rows are untouched.\n"
    "        us, up, payment_mismatch_audit = classify_payment_method_mismatch(us, up)\n"
)
if "classify_payment_method_mismatch(us, up)" not in text:
    text = text.replace(anchor, anchor + call, 1)

# Safety: this patcher must not alter the core.reconcile call.
if sum(text.count(x.strip()) for x in []) != 0:
    raise SystemExit("Safety check failed.")

PAGE.write_text(text, encoding="utf-8")
print("PASS: diagnostic added after existing core.reconcile().")
print("core.py NOT changed.")
print("POS normalization NOT changed.")
print("store/merchant mapping NOT changed.")
print("matched rows NOT changed.")

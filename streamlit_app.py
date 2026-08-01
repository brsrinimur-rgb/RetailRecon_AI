from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "pages"

required = [
    ROOT / "Home.py",
    ROOT / "core.py",
    ROOT / "db.py",
    PAGES / "1_POS_Reconciliation.py",
    PAGES / "17_Merchant_ID_Master.py",
    PAGES / "24_JV_Creation.py",
    PAGES / "25_JV_Approval_Center.py",
    PAGES / "26_D365_Posting_Center.py",
]

missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
if missing:
    raise RuntimeError("Deployment package is incomplete. Missing: " + ", ".join(missing))

runpy.run_path(str(ROOT / "Home.py"), run_name="__main__")

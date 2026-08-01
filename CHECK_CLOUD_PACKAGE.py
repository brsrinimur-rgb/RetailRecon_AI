from pathlib import Path
import py_compile

root = Path(__file__).resolve().parent

required = [
    "streamlit_app.py",
    "Home.py",
    "core.py",
    "db.py",
    "auth.py",
    "theme.py",
    "requirements.txt",
    ".streamlit/config.toml",
    "pages/1_POS_Reconciliation.py",
    "pages/17_Merchant_ID_Master.py",
    "pages/24_JV_Creation.py",
    "pages/25_JV_Approval_Center.py",
    "pages/26_D365_Posting_Center.py",
]

missing = [p for p in required if not (root / p).exists()]
assert not missing, f"Missing deployment files: {missing}"

for p in root.rglob("*.py"):
    if "__pycache__" not in p.parts:
        py_compile.compile(str(p), doraise=True)

print("STREAMLIT CLOUD PACKAGE CHECK PASS")

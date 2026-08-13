from pathlib import Path
import sys,importlib.util

root=Path(__file__).resolve().parent
page=root/"pages"/"32_System_Logic_Health.py"
page_text=page.read_text(encoding="utf-8")

assert "APP_ROOT=Path(__file__).resolve().parents[1]" in page_text
assert 'sys.path.insert(0,str(APP_ROOT))' in page_text
assert "from logic.release_guard import run_release_health" in page_text
assert "from logic.database_logic import health as db_health" in page_text

# Emulate the path bootstrap from inside /pages.
pages=root/"pages"
old=list(sys.path)
try:
    sys.path=[p for p in sys.path if str(root)!=str(p)]
    app_root=page.resolve().parents[1]
    if str(app_root) not in sys.path:
        sys.path.insert(0,str(app_root))
    from logic.release_guard import run_release_health
    from logic.database_logic import engine_health as db_engine_health
    r=run_release_health()
    assert r["Healthy"] is True,r
    h=db_engine_health()
    assert h["legacy_preserved"] is True,h
finally:
    sys.path=old

print("SYSTEM LOGIC IMPORT V23 PASS")

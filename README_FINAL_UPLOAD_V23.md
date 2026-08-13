RetailRecon AI V23 — System Logic Health Import Fix

Fixes:
ModuleNotFoundError: No module named 'logic'
on pages/32_System_Logic_Health.py.

Root cause:
Streamlit executes page scripts independently and the application root was not
guaranteed to be on Python's module search path.

Fix:
The page now adds Path(__file__).resolve().parents[1] to sys.path before importing:
- logic.release_guard
- logic.database_logic

No existing reconciliation, settlement, JV, GL, database, Copilot, or Store 613
business logic was changed.

Development rule preserved:
PRESERVE → EXTEND → MIGRATE → REGRESSION TEST → RELEASE

All key regressions pass and all Python files compile clean.

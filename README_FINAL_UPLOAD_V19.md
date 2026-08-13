RetailRecon AI V19 — Automatic Database Schema Migration

Fixes production error:
DatabaseError: no such column: store_code

Root cause:
- Existing Streamlit deployments retained an older correction_log table.
- V18 db.py contained ALTER TABLE migration code inside init_db().
- However, normal Streamlit pages imported db.py directly and did not call init_db().
- Therefore the migration never executed before load_correction_log() queried the new columns.

Fix:
- db.init_db() now runs automatically when db.py is imported.
- Existing SQLite data is preserved.
- CREATE TABLE IF NOT EXISTS and PRAGMA/ALTER migrations are idempotent.
- Missing correction_log columns are added automatically:
  original_auth, store_code, receipt_id, approver, approval_time, approval_comment.
- No database deletion is required.

Regression:
- Simulated legacy correction_log database migrated successfully.
- Existing APPROVED correction row preserved.
- Former failing load_correction_log('APPROVED') query succeeds.
- Existing correction approval, settlement, JV eligibility, JV date range and D365 GL regressions pass.
- All Python files compile clean.

RetailRecon AI V20 — Self-Healing Database Schema

Fixes:
DatabaseError: no such column: store_code

V20 performs the correction_log migration:
1. On db.py import.
2. Immediately before correction INSERT.
3. Immediately before load_correction_log SELECT.
4. Immediately before maker-checker decision query.

This means even an old persistent Streamlit SQLite database is repaired at the exact query path that previously failed.

No DB deletion required.
Existing correction rows are preserved.
All prior settlement/JV/GL controls retained.

Regression simulated a legacy table recreated AFTER module startup.
The exact load_correction_log('APPROVED') query self-healed and passed.

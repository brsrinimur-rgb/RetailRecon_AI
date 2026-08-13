RetailRecon AI V21 — Central Database Migration Framework

Permanent fix for repeated SQLite schema errors.

Adds:
- schema_version table
- schema_migration_log
- CURRENT_DB_SCHEMA_VERSION = 21
- centralized migrate_database()
- idempotent table/column creation
- correction_log migration
- gl_control_mapping migration
- gl_verification_runs migration
- jv_batches migration
- accounting period migration
- merchant/terminal/store mapping migration
- commission rate migration
- GL config / approval / adjustment / close-calendar migration
- query-time migration before D365 GL Control reads
- Database Health & Migration admin page

Current error fixed:
D365 GL Reconciliation -> gl_control_mapping legacy schema.

Existing data is preserved.
No database deletion required.

Regression simulated both:
1. old correction_log
2. old gl_control_mapping

Both self-healed and existing rows were preserved.
All key settlement/JV/GL regressions pass.

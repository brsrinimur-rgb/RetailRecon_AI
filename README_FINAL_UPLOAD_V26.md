RetailRecon AI V26 — Main Flow Settlement Wiring Fix

This release fixes the critical V25 wiring defect where the main POS Reconciliation
page called bank_ext functions without importing bank_ext.

It also removes the undocumented two-step dependency for provider bank settlement:
when Tabby/Tamara/TAP payout files are present in the main run, provider payout
matching to Al Rajhi is executed there too.

No proven core.py/db.py logic was deleted.

Deployment:
Upload the full V26 package. At minimum, the changed files are:
- pages/1_POS_Reconciliation.py
- logic/bank_settlement_extension.py
- REGRESSION_MAIN_POS_PAGE_WIRING_V26.py

All key regressions pass.

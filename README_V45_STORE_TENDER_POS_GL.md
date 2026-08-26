# V45 — Store Tender → POS Statement → D365 GL Control

New read-only three-way accounting control.

Store Tender → POS Statement → D365 GL.

The module combines the existing deterministic engines only:
- core.reconcile() remains authoritative for Store Tender → POS.
- core.trace_d365_source_to_gl() remains authoritative for Store Tender → GL.
- Non-cash THREE-WAY RECONCILED requires both matches.
- Cash is Store Tender → GL control only.
- No settlement status, bank receipt, JV eligibility, JV creation, approval or posting state is modified.

Page: pages/35_Store_Tender_POS_GL_Reconciliation.py
Engine: logic/store_tender_pos_gl.py
Regression: tests/REGRESSION_V45_STORE_TENDER_POS_GL.py

# V50 — Clean POS Statement → D365 GL Reconciliation

This release fixes the deployed-page mismatch shown in production.

The old `Store Tender → POS Statement → GL` page is removed.
The only page 35 is:

`pages/35_POS_GL_Reconciliation.py`

Accounting authority:
**POS Statement Amount ↔ D365 GL Amount**

Merchant ID is displayed and used as a key identity control.
Multiple POS files and multiple GL files can be selected.

The dashboard uses the current POS→GL summary schema:
- POS Rows
- GL Matched
- GL Amount Exceptions
- GL Not Posted
- Review Required
- Identifier Mismatch
- POS Data Incomplete
- Unmatched GL Rows

The page no longer expects legacy `GL Matched` values from a Store Tender
three-way result, eliminating the KeyError shown in the production traceback.

# V53 — Bulk Daily POS + D365 GL Upload

Designed for daily operational use.

POS:
- Multiple XLSX/XLS/CSV files can be selected together.
- A ZIP containing any number of POS files can also be uploaded.

D365 GL:
- Multiple XLSX/XLS/CSV account dumps can be selected together.
- More than 8 GL accounts is supported.
- A ZIP containing any number of GL files can also be uploaded.

All source files are combined before reconciliation.

Accounting authority:
POS Statement Amount ↔ D365 GL Amount.

Merchant ID is retained as a key identity control.
Store Tender is not used in this module.

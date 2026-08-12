RetailRecon AI V15 — D365 GL Reconciliation & Clearing Control

Built against the 7 Finance-supplied D365 General Journal Account Entry files.

Detected controlled clearing accounts:
- 11020907 POS Clearing - DC/CC (MADA/VISA/MASTERCARD)
- 11020901 POS Clearing - AMEX
- 11020902 POS Clearing - Cash/Cheques
- 11020913 POS/Online Clearing - Tabby
- 11020922 POS/Online Clearing - Tamara
- 11020904 POS Clearing - Tap
- 11020908 Online Clearing - Tap Gateway

New module: pages/30_D365_GL_Reconciliation.py
- Upload multiple D365 GL extracts
- Normalize Journal/Voucher/Date/Ledger Account/Store/Description/Amounts
- Extract Store dimension from Ledger Account
- Extract Store 613 Sales Order from D365 Description
- Source -> actual D365 GL trace
- RetailRecon clearing JV -> actual D365 GL verification
- Reverse GL -> source reconciliation
- Duplicate fingerprint / offset / reversal evidence
- Clearing-account movement control
- GL exception center
- Store 613 Sales Order audit tab
- Persistent GL verification run history
- Downloadable GL verification pack
- AI Finance Copilot GL questions

Important accounting control:
The uploaded files are clearing-account extracts. The module calls the result
'Net GL Movement' rather than 'Closing Balance' unless the uploaded GL population
contains the full opening/period population. Full Bank/Commission/VAT voucher
integrity requires those D365 voucher lines to be included in a future/full GL extract.

Actual uploaded GL rows normalized during build test: 1959
Store 613 GL rows with extracted Sales Order evidence: 329

All Python files compile clean.
REGRESSION_D365_GL_CONTROL_V15: PASS
Actual 7-file GL parser/normalizer integration: PASS

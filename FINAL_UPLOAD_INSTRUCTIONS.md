# FINAL POS → D365 GL PACKAGE

## Upload
Replace the production `pages/35_POS_GL_Reconciliation.py` with the file in this package and deploy the package contents to the repository.

## Daily workflow
1. POS Statement: use MULTIPLE FILES or one ZIP containing all daily POS files.
2. D365 GL: use MULTIPLE FILES or one ZIP containing all GL account dumps.
3. No 8-account limit.
4. Run POS → GL Reconciliation.
5. Review Merchant ID, Terminal ID, Store/Provider/Reference/Date identity and then POS Amount ↔ GL Amount.

## Real POS format supported
The parser detects report-style Excel headers (including headers below title rows) and reads both `Details_mada` and `Details_CC` style sheets.

## Accounting rule
Amount is never used to select a GL row. A GL row must first be identified from deterministic evidence. Only then is POS Statement Amount compared with D365 GL Amount using the configured tolerance.

Store Tender is not part of this module.

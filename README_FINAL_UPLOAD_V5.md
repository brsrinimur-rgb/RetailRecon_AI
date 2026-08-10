RetailRecon AI V5 - Cash Sales / Cash Refund

Confirmed D365 Store Tender cash rules:
- Cash > 0 = Cash Sales
- Cash < 0 = Cash Refund
- Cash = 0/blank = ignored
- Original signed cash amount is retained
- Cash is displayed in reconciliation output
- Cash is excluded from POS/provider matching
- Cash never creates Missing POS

Locked examples:
- Store 601, 03-Aug-2026, Receipt 601601012001362, Cash -475.00 = Cash Refund
- Store 601, 07-Aug-2026, Receipt 601601011018062, Cash +460.00 = Cash Sales

All prior Store 614, Tabby, Tamara and TAP fixes remain included.

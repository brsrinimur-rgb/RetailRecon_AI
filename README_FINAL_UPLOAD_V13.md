RetailRecon AI V13 — Store 613 D365 SalesDetails Bridge

New POS Reconciliation input:
- D365 Store Tender
- D365 Sales Details
- POS / AMEX / Tabby / Tamara / Tap
- Bank Statements

Store 613 logic:
1. Preserve Sales Order from D365 StoreTender.
2. Normalize D365 Sales Details separately.
3. Match Store 613 using Store Code + Sales Order.
4. Bring Receipt ID from Sales Details only when unique.
5. Bring Auth Code from Sales Details only when unique and available.
6. Never overwrite an existing StoreTender Receipt/Auth value.
7. Ambiguous/missing mappings are flagged, never guessed.
8. Bridge happens before approved corrections and POS/provider reconciliation.
9. Store 613 Bridge tab shows the audit evidence.

This allows the user to upload an updated D365 Sales Details report each reconciliation run.

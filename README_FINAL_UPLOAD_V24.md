RetailRecon AI V24 — Bank Settlement Propagation

Fixes the main JV blocker issue without deleting old working code.

Flow:
Matched transaction
→ settlement batch
→ bank statement evidence
→ BANK RECEIVED
→ propagate Bank Settled to every underlying matched transaction
→ JV Eligibility

ANB matching uses:
Terminal ID + source transaction date + card scheme + expected net amount.
Transaction count strengthens the evidence when present.

Al Rajhi provider settlement supports Tabby/Tamara/TAP payout matching.

Existing transaction-level bank matching remains in place as a legacy first pass.
All previous core/database/JV/GL logic remains intact.

All key regressions pass.

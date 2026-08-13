RetailRecon AI V18 — Settlement Batch Engine

Foundation added:
- ANB / AMEX card settlement batch construction from Matched transactions
- Provider-specific payout source classification
- Tamara payout/statement parser
- Tabby payout/bulk settlement parser
- TAP payout parser preserving payout_id and settlement_id
- TAP date recovery from settlement_id when Excel date conflicts materially
- Bank narration intelligence for provider/scheme/terminal/merchant/payout/count
- Bank header support including Trans: Date, Amount Cr., Amount Dr.
- Bank name detection from content/filename fallback
- Settlement Batch → Bank Credit reconciliation
- Configurable Tabby fixed payout-level deduction (default SAR 5)
- Batch-level settlement propagation back to underlying matched transactions
- Multi-stage settlement status fields
- Settlement Batch Engine Streamlit page
- JV Eligibility now uses propagated Bank Settled status
- AI Copilot settlement-batch questions

Control principle:
RetailRecon does not weaken the JV bank-settlement gate. It proves settlement at batch/payout level,
then propagates verified bank receipt evidence to the underlying matched transactions.

Regression tests:
- Settlement Batch Engine V18 PASS
- JV Eligibility V17 PASS
- Date Range JV V16 PASS
- D365 GL Control V15 PASS
- All Python files compile clean.

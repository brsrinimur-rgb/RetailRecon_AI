RetailRecon AI V17 — JV Eligibility Breakdown

Added to JV Creation:
- Every store in the selected From/To period is visible before JV creation.
- Transactions in Period
- Matched in Period
- Bank Settled & Within Tolerance
- Ready for JV
- Blocked
- Exact blocking reason

Blocking reasons:
- Not Matched
- Difference > SAR 1
- Bank Settlement Pending

Existing rules retained:
- All locations in one run.
- CC = MADA + VISA + MASTERCARD.
- AMEX / TABBY / TAMARA / TAP separate.
- One JV per Store + JV Group for selected From/To period.
- D365 period gate, validation, approval, posting and GL verification remain unchanged.

Regression tests passed.
All Python files compile clean.

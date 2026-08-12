RetailRecon AI V16 — All-Location Date-Range JV Creation

Change requested by Finance:
- User selects JV From Date and To Date.
- Date filter is inclusive.
- Source is the current Matched reconciliation report.
- All locations are processed in one run.
- Only Matched + <= SAR 1 difference + Bank Settled transactions are eligible.
- MADA + VISA + MASTERCARD are combined as CC.
- AMEX / TABBY / TAMARA / TAP remain separate.
- One JV batch per Store + JV Group for the selected date range.
- Transactions outside the selected date range are excluded.
- JV From Date, JV To Date and JV Source Period are stored on every JV line.
- Batch IDs contain Store + Group + From/To dates.
- Narrations contain Store + Group + selected From/To period.
- Existing D365 accounting-period gate and JV validation remain active.
- D365 GL Reconciliation V15 remains included.

Regression:
REGRESSION_JV_DATE_RANGE_V16: PASS
Existing D365 GL/JV regressions: PASS
All Python files compile clean.

# V26 — Main Flow Settlement Wiring Fix

Critical production fix:
- pages/1_POS_Reconciliation.py now imports:
  from logic import bank_settlement_extension as bank_ext

Main-flow settlement:
- V25 ANB advanced batch matching is reachable from RUN RECONCILIATION.
- Tabby/Tamara/TAP payout-to-Al-Rajhi reconciliation is also wired into the main flow when payout files are present.
- Provider payout batches are retained in session state for audit.

Bank-row safety:
- Bank-credit usage tracking now prefers Bank Source File + Bank Source Row identity.
- Narration text is only a legacy fallback, reducing duplicate/reuse risk.

Preserved:
- core.py unchanged.
- db.py unchanged.
- existing V25/V24/V23/V22/V21/V20/V18/V17/V16/V15 controls retained.

Known controlled gap:
- Multiple POS settlement batches -> one bank credit is not auto-matched in V26.
  It remains pending/review rather than being guessed.

# V24 — Bank Settlement Propagation

Added only:
- logic/bank_settlement_extension.py
- robust ANB statement normalization
- robust Al Rajhi statement normalization
- ANB narration parsing: terminal, merchant, source date, scheme, TX count, fee, VAT
- deterministic ANB settlement matching:
  Terminal + Source Date + Scheme + Net Amount
- provider/Al Rajhi payout matching for Tabby/Tamara/TAP
- verified batch settlement propagation to matched transactions
- settlement blocker summary

Modified only as integration points:
- pages/1_POS_Reconciliation.py
- pages/18_Settlement_Batch_Engine.py

Preserved:
- core.py unchanged
- db.py unchanged
- existing legacy transaction-level bank matching still runs first
- V23/V22/V21/V20/V18/V17/V16/V15 logic retained

Real bank statement regression:
- ANB credits total verified: SAR 7,690,111.56
- Al Rajhi credits total verified: SAR 9,421,448.48
- Provider rows detected: Tabby 51, Tamara 8, TAP 31
- Real ANB example 55610715 / VISA / 30-Jun / TX_12 / SAR 6,567.01 matched and propagated.

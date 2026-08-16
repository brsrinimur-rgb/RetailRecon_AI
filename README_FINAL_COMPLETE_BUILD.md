# RetailRecon AI — Final Complete Build V30

## Confirmed Finance control flow
D365 Store Tender → POS/provider match → settlement batch/payout → actual bank receipt →
transaction settlement propagation → full-period JV eligibility → maker-checker →
D365 posting → D365 GL verification.

## Critical rules included
- Normal JV includes only transactions whose settlement amount is actually received and verified in the bank.
- A few pending transactions do not block the full month; only those pending amounts are excluded/carry-forward.
- Bank receipt must be dated on/before the selected JV period end for a normal period JV.
- Late receipt keeps the original transaction period and becomes Settled in Next Period / controlled late-JV.
- ANB primary proof: POS batch amount = ANB bank credit.
- ANB commission and VAT are separate debit evidence; they are not added to POS amount.
- ANB deterministic evidence includes terminal, payment scheme, date window and transaction count.
- Payout-shaped files are not double-normalized as transaction files.
- Bank-row identity uses source file + source sheet + source row + bank date + bank amount.
- Legacy bank parser stamps source sheet/row and canonicalizes ANB / AL RAJHI.
- TABBY payout Order Number links to matched Provider Reference only when unique.
- TAMARA/TAP payout batches may be bank-received, but transaction-level propagation stays controlled until a trusted key is proven.
- Default JV grouping: CC=MADA+VISA+MASTERCARD; AMEX/TABBY/TAMARA/TAP separate.
- Finance can edit provider/payment JV grouping for the current run.
- Historical reconciliation runs are saved as separate Run IDs and can be reloaded.
- Settlement carry-forward preserves original period and records resolution period.
- Database schema migration is additive/self-healing; no DB deletion is required.

## New/updated control pages
- POS Reconciliation
- Bank Settlement Audit with settlement evidence
- Settlement Batch Engine
- Settlement Carry Forward
- Reconciliation Run History
- JV Creation with received-only full-period control and editable provider grouping
- D365 GL Reconciliation
- Database Health / System Logic Health

## Controlled open items
- TAMARA transaction-level payout propagation: pending trusted transaction key.
- TAP transaction-level payout propagation: pending trusted transaction key.
- Many POS settlement batches → one bank credit: remains review/pending until an accounting-proof aggregation design is approved.

These open items are intentionally not guessed or auto-settled.

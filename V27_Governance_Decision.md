# V27 Governance Decision — 2026-08-13

**Decision (confirmed by Srinivasa):** `V27_Settlement_Dedup_Bank_Identity_Spec.md` is the governing V27 specification. It supersedes the original narrow-scope draft, which is retained separately as `V27_Settlement_Dedup_Bank_Identity_Spec_NARROW_AUDIT_TRAIL.md` for audit trail only — not a source of truth for what V27 does.

**Reason:** the governing spec includes a finding the narrow draft doesn't — that a Tabby/Tamara/TAP payout batch could reach `BANK RECEIVED` with no code path back to `Bank Settled` on the underlying matched transaction — found by functionally proving Settlement Batch Engine rather than only compile-checking it, plus the `classify_settlement_source()` case-normalization fix that turned out to be a precondition for the other three fixes to have any observable effect at all.

**Confirmed findings, all treated as mandatory (not optional) going into production:**
- `classify_settlement_source()` case-normalization fix.
- Payout de-duplication (route payout-shaped files away from transaction normalization before they're processed twice).
- Bank-row identity: Source File + Source Sheet + Source Row + Bank Date + Bank Amount, never narration text.
- Legacy bank parser stamps Source Row / Source Sheet.
- Tabby Order Number → `Provider Reference` linking, so a settled Tabby batch actually reaches `Bank Settled`.
- Tamara/TAP intentionally left unlinked — no trusted transaction-level key confirmed yet; auto-linking without one would be guessing.

**Open before this is called the final V27 production baseline (all three carried forward, none resolved by V27 itself):**

1. **Tamara/TAP transaction-level linking** — their payout batches can reach `BANK RECEIVED` at the batch level, but the underlying transactions stay not-JV-eligible until a trusted per-transaction reference is confirmed for each provider (analogous to Tabby's Order Number ↔ `Provider Reference`). Candidate next step: TAP payout files sometimes carry `authorization_id` — needs confirmation of how a TAP Auth Code actually lands in `matched` before trusting it as a link key.
2. **Legacy bank-parser label mismatch** — `core.normalize_bank()`'s fallback path (and the two pages that call it) produce `"ANB Bank"` / `"Al Rajhi Bank"` (or, in `18_Settlement_Batch_Engine.py`'s case, the raw filename), while `reconcile_card_batches_to_anb()` / `reconcile_provider_batches_to_rajhi()` filter the bank pool on an exact `"ANB"` / `"AL RAJHI"` match. Needs a centrally-normalized bank label, touching both pages plus wherever else `bank=` gets set — deferred to the next patch, not fixed in V27.
3. **Many POS settlement batches → one bank credit** — intentionally out of scope for V27 and V28-as-originally-scoped; stays Review/Pending until a controlled, accounting-proof aggregation design is built, not a broad-amount-aggregation shortcut.

Note: V28 as delivered separately (Reconciliation Run History) is an unrelated feature and does not touch any of the three items above.

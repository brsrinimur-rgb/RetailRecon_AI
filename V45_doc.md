# V45 — Excess/Shortfall Diagnostic Labeling for Bank Settlement Review

**Date:** 2026-09-10
**File changed:** `logic/bank_settlement_extension.py`
**Scope:** purely additive diagnostic flagging. No classification, JV eligibility, Bank Settled propagation, or carry-forward logic changed.

## Why

This follows directly from the real Store 603 batch you pasted, where the review reason read:

> "ANB identity evidence found but POS amount SAR 150.00 does not equal candidate bank credit SAR 384.00 within tolerance SAR 1.00."

You asked whether, when the bank receives *more* than the POS batch expects, the JV could be created for the expected amount and the excess carried forward as an open item. I asked two clarifying questions before touching any logic, and your answers set the scope for this fix:

- *"i need something better options amount in bank i can't keep open the recon file mangement will not accept this logice"* — no silent auto-split or indefinitely-open carry-forward bucket; management won't accept that.
- *"Not sure — I'd rather see it flagged first before deciding"* — add visibility first, before any classification-affecting decision.

So this delivery does exactly one thing: makes it immediately obvious, on every BANK REVIEW REQUIRED row, whether the bank sent **more** or **less** than expected, and by how much — with no change to how those rows are classified or whether they're JV-eligible.

## What changed

A new shared helper, `_mismatch_direction_note()`, compares the expected amount to the closest bank candidate and returns:

- **Direction label**: `"EXCESS RECEIVED"`, `"SHORTFALL"`, or `""` (within tolerance — nothing to flag)
- **Reason text** that names the direction, the exact amount, and what to check next:
  - **Excess** → "This usually means an extra or unidentified transaction is folded into this bank credit — check for a POS/provider row not included in this batch, a duplicate, or a batch that should have been grouped together with this one."
  - **Shortfall** → "This usually means a POS/provider transaction has not been uploaded yet, or an unexpected deduction was taken — check for a missing file or an unmatched transaction of about this amount."

This is wired into both live batch-matching functions used by the Settlement Batch Engine page:

1. **`reconcile_card_batches_advanced()`** — the ANB card-batch matcher (MADA/VISA/etc., the exact function that produced your Store 603 reason text). Your example would now read:

   > "Bank credit SAR 384.00 is SAR 234.00 MORE than the POS batch amount SAR 150.00 (tolerance SAR 1.00). This usually means an extra or unidentified transaction is folded into this bank credit — check for a POS/provider row not included in this batch, a duplicate, or a batch that should have been grouped together with this one. Do not treat as settled until the extra amount is identified."

2. **`reconcile_provider_batches_to_rajhi()`** — the TABBY/TAMARA/TAP payout matcher. This one previously had **no reason text at all** in the "candidates exist but none tie out" case — a bigger gap than the ANB function. It now gets the same excess/shortfall labeling.

Two new columns appear on the batch results (and therefore on the "Batch-Level Bank Proof" table on the Bank Settlement Audit page, once that page's column list is extended to show them — see note below):

- **Mismatch Direction** — `EXCESS RECEIVED` / `SHORTFALL` / blank
- **Closest Bank Candidate Amount** — the nearest bank credit that was considered

## What did NOT change (verified)

- **Settlement Status** values and logic are identical. A mismatch — excess or shortfall — is still always `BANK REVIEW REQUIRED`, never auto-classified as received.
- **`propagate_verified_batches()`** still only sets `Bank Settled=True` on an exact `BANK RECEIVED` match. Nothing about this fix changes that.
- **JV eligibility** (`pages/24_JV_Creation.py`) is unaffected — it gates on `Bank Settled=True`, which this fix never sets. Excess/shortfall rows remain correctly blocked from JV creation, exactly as before.
- **No auto-splitting** of the excess or shortfall amount, and **no new carry-forward behavior**. This is visibility only, as you asked for.

## One follow-up worth knowing about

The "Batch-Level Bank Proof" table on `pages/11_Bank_Settlement_Audit.py` currently doesn't list "Mismatch Direction" or "Closest Bank Candidate Amount" in its displayed columns — those columns exist in the data now, but the page would need a one-line addition to `batch_cols` to actually show them. I didn't make that page change yet since it's a separate (very small, purely additive) file — say the word and I'll add it.

Also still outstanding from the JV conversation: the JV screen's block reason shows a generic "Bank Settlement Pending" for `BANK REVIEW REQUIRED` rows rather than naming that status specifically. I offered to fix that earlier — let me know if you'd like it done now or separately.

## Verification

- `py_compile` clean.
- New regression test `REGRESSION_V45_MISMATCH_DIRECTION_LABELING.py` (10 assertions): confirms excess/shortfall labeling and reason text for both matcher functions, AND explicitly confirms Settlement Status classification is unchanged for identical inputs (an exact match still classifies as `BANK RECEIVED` with no mismatch label). All pass.
- Existing regression suites re-run against the patched file in an isolated copy: `REGRESSION_ADVANCED_SETTLEMENT_EXCEPTION_V25.py`, `REGRESSION_FINAL_COMPLETE_BUILD.py`, `REGRESSION_V35_GL_LAG_TERMINAL_FIXES.py`, `REGRESSION_V41_MINOR_HARDENING.py` — all pass unchanged. (`REGRESSION_BANK_SETTLEMENT_PROPAGATION_V24.py`, `REGRESSION_MAIN_POS_PAGE_WIRING_V26.py`, `REGRESSION_PAGE_WIRING_FINAL.py`, `REGRESSION_V37/38/39` fail identically on the unpatched baseline too — they depend on local fixture files/paths not present in this environment, confirmed pre-existing and unrelated to this change.)
- Diff against the live repo copy is purely additive (new lines only, no existing line removed except the two reworded `reason=` fallback lines which now read from the same helper).

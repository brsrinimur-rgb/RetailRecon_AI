# V72 — GCC NET Narration/Batching Gap (Additive, V71/AMEX Untouched)

**Date:** 2026-09-23
**Scope:** `core.py` (2 small changes) and `logic/bank_settlement_extension.py` (2 small changes).
**Not touched:** `pages/18_Settlement_Batch_Engine.py`, `pages/38_Bank_Reconciliation_Control_Tower.py`,
`logic/bank_reconciliation_report.py` — V69 and V71 both stay exactly as frozen/delivered.
`reconcile_card_batches_advanced()`, `reconcile_amex_batches_via_statement()`,
`reconcile_amex_wires_to_bank()`, `finalize_amex_batches()`, `annotate_amex_wire_confirmations()` —
none of V71's matching/wrapper functions were touched.

This is the next item in the order you set after freezing V71: *"GCC NET parser gap → ANB 81-review
transaction-level investigation → ..."*

## Scope correction, stated plainly before anything else

V70 and V71's docs described this as "a one-line addition to the narration parser's scheme
regex." That was an undersell. Before touching anything, I traced the real chain end-to-end and
found the gap was in **three** places, not one — fixing only the narration side would have shipped
a change that tags bank credits correctly but has nothing to match them against, because GCC NET
POS transactions were being silently dropped before they ever became a settlement batch:

1. `logic/bank_settlement_extension.py`: `parse_anb_narration()`'s scheme regex recognized
   `MADA|VC|MC` but not `GC` — the originally-identified gap (V70 Finding 3, SAR 5,354.98 / 12
   rows). A `GC_`-prefixed ANB credit never got a `Provider`/`Narration Scheme` tag.
2. `logic/bank_settlement_extension.py`: the local `_norm_payment()` had no GCC NET case, so even a
   correctly-extracted `"GC"` token wouldn't normalize to the `"GCC NET"` string used everywhere
   else in the codebase.
3. **`core.py`: `build_card_settlement_batches()`'s Payment Type filter was hardcoded to
   `{"MADA","VISA","MASTERCARD","AMEX"}`.** GCC NET POS transactions were filtered out before batch
   construction and never became a settlement batch at all — confirmed real by running the
   untouched, pre-V72 function directly: it silently drops the GCC NET row every time (see
   regression section 2). Fixing #1 and #2 alone would have been a no-op in production: correctly
   tagged bank credits with literally nothing on the POS side to tie them to.

GCC NET was already a real, recognized payment type elsewhere in `core.py` — it has its own
commission rate (`_commission_master_maps()`'s defaults: 1.50% + 15% VAT, vs MADA's 0.55%) and its
own JV grouping (`jv_group()` keeps it separate from the "CC" bucket) — it just was never wired
into the ANB bank-matching side at all, on either leg.

## What changed

**`core.py`:**
- `_norm_payment()`: added `GC`/`GCC`/`GCCNET`/`GCC NET` (any casing/spacing) → normalizes to
  `"GCC NET"`, matching how every other scheme variant is normalized. Every other input's output is
  proven byte-identical to the pre-V72 function.
- `build_card_settlement_batches()`: the Payment Type filter now includes `"GCC NET"` alongside the
  existing four. A GCC NET POS transaction now produces a settlement batch, tagged
  `Provider="ANB POS"` (the same line that already handles this: `"ANB POS" if pay!="AMEX" else
  "AMEX"` — no change needed there, GCC NET falls through correctly). Proven via full-DataFrame
  comparison that this changes nothing about the MADA/VISA/MASTERCARD/AMEX batches built from the
  same input.

**`logic/bank_settlement_extension.py`:**
- `_norm_payment()`: added the same `GC`/`GCC`/`GCCNET` → `"GCC NET"` normalization, consistent with
  `core.py`'s version. Every other input proven byte-identical to pre-V72.
- `parse_anb_narration()`: the scheme regex now recognizes `GC` alongside `MADA|VC|MC`
  (`GC_<vat>_<fee>_TX_<count>`, the same shape every other card scheme uses in this narration
  format), and the `provider="ANB POS" if scheme in {...}` set now includes `"GCC NET"`. Proven that
  a real MADA/VC/MC narration and the real AMEX wire narration parse byte-identically to the
  pre-V72 function — every returned field compared, not a subset.

**One assumption flagged for confirmation on the real rerun:** the `GC_<vat>_<fee>_TX_<count>`
shape is assumed to match the same structural pattern the other three card schemes use in ANB's
narration, since `core.py` already treats GCC NET as a card-style scheme (its own commission rate,
its own JV grouping) rather than a BNPL-style provider. This mirrors the exact narration shape V70
reported finding in the real data (`POS GC_...`). If the real GCC NET narration text turns out to
differ even slightly in punctuation, that's a one-character regex adjustment to make on the real
rerun — same "synthetic now, confirm on real data next" discipline used for V71's AMEX wiring.

## Verification

`REGRESSION_V72_GCC_NET_PARSER_GAP.py` — 66 `_assert()` checks plus 2 full-DataFrame
`pd.testing.assert_frame_equal()` comparisons (68 checks total), all passing, run both standalone
and inside a full copy of your repo (the full-repo run caught a real bug in my own test script's
file-loading path — see note below — before I trusted any result from it).

One more thing I caught on a final pass before sending this: two of those checks were originally
written as `_assert(True, "...")` right after the real `assert_frame_equal()` call above them —
exactly the vacuous-assertion pattern you caught in V71 Round 3 (they could never actually fail on
their own; the real check was the line above). Replaced both with plain `print("[PASS] ...")`
messages, same fix as V71, and reran everything above to confirm it still passes clean. Flagging it
rather than quietly fixing it, same as the file-loader bug below.

- **Section 1–3:** `core._norm_payment()` and `bank_ext._norm_payment()` both get the new GCC NET
  cases, and every other input (MADA/VISA/MASTERCARD/AMEX/TABBY/TAMARA/TAP/empty/unknown) is proven
  byte-identical to the pre-V72 function — not spot-checked, every listed input compared.
- **Section 2, the real proof of the 3-place gap:** built a `matched` set with MADA + VISA +
  MASTERCARD + AMEX + GCC NET transactions. `build_card_settlement_batches()` now produces 5
  batches (was 4); the GCC NET batch is correctly tagged `Provider="ANB POS"` with the right
  expected amount; the other 4 batches are **byte-for-byte identical** via
  `pd.testing.assert_frame_equal()` whether the GCC NET row is present in the input or not. Then,
  separately, ran the **untouched, pre-V72** `build_card_settlement_batches()` on the same input and
  confirmed it silently drops the GCC NET row every time — direct proof the gap was real, not
  theoretical.
- **Section 4:** a synthetic `GC_15.78_105.09_TX_12` narration now returns `Provider="ANB POS"`,
  `Narration Scheme="GCC NET"` with VAT/fee/TX count parsed correctly (all previously blank). Ran
  the same narration through the **untouched, pre-V72** `parse_anb_narration()` and confirmed it
  returns `Provider=""`, `Narration Scheme=""` — again, direct proof, not an assumption. Five
  non-GCC-NET narration shapes (MADA, VC, MC, the real AMEX wire text, an unrecognized string) parse
  identically field-by-field to the pre-V72 function.
- **Section 5 — the one that actually matters:** built a GCC NET settlement batch and a matching
  `GC_`-narrated bank credit, ran them through the **completely untouched**
  `reconcile_card_batches_advanced()` (no matching-logic change at all), and it reaches **BANK
  RECEIVED** using the exact same deterministic evidence rule every other scheme uses (`Terminal +
  Scheme + Date + TX Count`). This is the proof the loop genuinely closes end-to-end, not just that
  a narration field gets a label.
- **Section 6:** before/after on `reconcile_card_batches_advanced()`: the MADA batch's full result
  is identical whether a GCC NET batch/credit pair is present in the same run or not.

**A bug I found and fixed in my own test script, not the implementation:** the first version of
this regression file loaded the "new" `bank_settlement_extension.py` from a flat path next to the
script, which happened to work by coincidence in my own scratch test directory but silently loaded
a stray, unrelated, pre-existing duplicate file when I ran the same script inside a full copy of
your repo (there's an old `bank_settlement_extension.py` sitting at your repo root, unrelated to
`logic/`, left over from before — same one V71's docs never needed to touch). That caused a false
failure the first time I ran it in the full-repo context. Fixed the loader to check
`logic/bank_settlement_extension.py` first (the real deployed location) and only fall back to a
flat copy for scratch-testing convenience — then reran everything and got a genuine pass. Flagging
this because it's exactly the kind of thing worth being upfront about rather than quietly fixing
and not mentioning.

**V71's regression file also needed one line updated, expected and by design:** V71's hash tripwire
correctly fired on `parse_anb_narration()` — it WAS legitimately modified by V72. Per V71's own
documented policy ("update the hash AND rerun the behavioral sections"), I updated that one hash
value in `REGRESSION_V71_AMEX_PAGE18_WIRING.py`, kept the old hash in a comment for the record, and
reran V71's full 45-check suite against the V72-modified files — all 45 still pass, confirming
V72's changes to `parse_anb_narration()` didn't disturb any AMEX behavior. This is a one-line
regression-file update, not a change to V71's runtime code or design.

I also reran the full adjacent suite (`REGRESSION_V35_GL_LAG_TERMINAL_FIXES`,
`REGRESSION_V41_MINOR_HARDENING`, `REGRESSION_ADVANCED_SETTLEMENT_EXCEPTION_V25`,
`REGRESSION_FINAL_COMPLETE_BUILD`, `REGRESSION_SETTLEMENT_BATCH_ENGINE_V18`) against the V72 files —
all still pass, same as before.

## Real-data validation — same situation as V71, I can't close this myself

I don't have your real GCC NET POS transactions or the real ANB narration text for those 12 rows —
only V70's earlier finding that the pattern is `POS GC_...`. Everything above is proven against
synthetic data shaped to match that finding and the existing MADA/VC/MC pattern it mirrors.

**What I'd need from you:** deploy `core.py` and `logic/bank_settlement_extension.py`, rerun the
real September dataset through page 18, and check the 12 GCC NET rows (SAR 5,354.98) specifically —
do they now show a `Provider`/`Narration Scheme` tag on the bank side, and does a GCC NET settlement
batch now appear and tie to BANK RECEIVED (or at least get correctly attempted, landing on REVIEW if
the amounts don't tie)? If the real narration shape differs even slightly from `GC_<vat>_<fee>_TX_<count>`,
tell me exactly what it looks like and I'll adjust the regex precisely rather than guess again.

## How to upload

Replace:
- `core.py`
- `logic/bank_settlement_extension.py`

Optional but recommended:
- `REGRESSION_V72_GCC_NET_PARSER_GAP.py`
- The updated `REGRESSION_V71_AMEX_PAGE18_WIRING.py` (one hash line changed; keeps V71's suite
  passing against the V72-modified files — not required for the app to run, only for your own
  regression record)

## Explicitly not touched here, per your instruction

The 81 `BANK REVIEW REQUIRED` groups (SAR 225,888.71) and the ANB settlement-batch-granularity
question (V70 Finding 1, the SAR 2.09M item) — next in line, per your own ordering, and needs the
transaction-level evidence pull you already specified before any matching code changes there.

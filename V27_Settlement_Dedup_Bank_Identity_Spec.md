# RetailRecon AI — V27: Settlement Input De-duplication & Bank Row Identity Hardening

Ordered per your priority: fix classifier → prove payout classification → prove Settlement Batch Engine → prove main POS flow → de-dup/row-identity hardening. Everything below was verified by execution against synthetic fixtures, not by reading the diff. `PROVE_V27_END_TO_END.py` (included) runs all four proof steps end-to-end; run it directly to reproduce every claim in this document.

## 0. Fix classifier

`core.classify_settlement_source()` built its comparison set via `norm_cols(df)`, which upper-cases every column and replaces separators with `_` (e.g. `"Payout ID"` → `"PAYOUT_ID"`), then compared that against its own lowercase, space/underscore-separated literals (`"payable to merchant"`, `"payout_id"`, ...). The case never matched, for any provider, ever — confirmed directly against realistic fixtures before the fix:

```
normalized columns: ['PAYOUT_ID', 'SETTLEMENT_ID', 'AMOUNT']
classify_settlement_source result: ''
```

**Fix:** build the comparison set from the raw column headers, lowercased only — the form the literals were clearly written for. Two lines changed; detection literals and branch logic untouched. Also hardened the TAP branch to accept both `"payout_id"` (snake_case export) and `"payout id"` (spaced Excel header) — `normalize_tap_payout()` already tolerates both via its own header search, the classifier gating it shouldn't be stricter.

This function is the sole gate feeding `18_Settlement_Batch_Engine.py` and the V26 main-page wiring. It's called from those two places only — confirmed by grep across the full uploaded codebase. Provider-payout classification has likely never worked in any release before this fix.

## 1. Prove payout classification

`PROVE_V27_END_TO_END.py` STEP 1 runs `classify_settlement_source()` against realistic column layouts for all three providers:

```
TAMARA fixture -> 'TAMARA_PAYOUT'
TABBY fixture -> 'TABBY_PAYOUT'
TAP fixture (snake_case headers) -> 'TAP_PAYOUT'
TAP fixture (spaced headers) -> 'TAP_PAYOUT'
```

All four pass. These are synthetic fixtures built from each `normalize_*_payout()` function's own documented column search list, not your actual export files — please run a real file from each provider through this before calling it verified end to end.

## 2. Prove Settlement Batch Engine — and a second, more serious bug found while proving it

Fixing the classifier alone turned out not to be enough. Replicating `18_Settlement_Batch_Engine.py`'s exact call sequence (upload loop → `reconcile_provider_batches_to_rajhi` → `propagate_verified_batches`) with real fixtures surfaced this: **a payout batch that correctly reaches `BANK RECEIVED` still has no way to flip the underlying matched transaction's `Bank Settled` flag.**

`propagate_verified_batches()` only links a batch back to `matched` two ways: an explicit `Underlying IDs` list, or — only for `Provider in {"ANB POS","AMEX"}` — a Store+Terminal+Date+Payment fallback. `Underlying IDs` is set in exactly one place in the whole codebase (`build_card_settlement_batches()`, the ANB card/AMEX path — confirmed by grep). None of `normalize_tamara_payout`, `normalize_tabby_payout`, `normalize_tap_payout` set it, and there's no TABBY/TAMARA/TAP branch in the fallback. So even with the classifier fixed, a settled Tabby/Tamara/TAP batch was structurally inert — it would never make the transaction JV-eligible.

**Fix chosen (you asked for "the best" option):** TABBY only, using an existing trusted key. `core.reconcile()` already sets `matched["Provider Reference"]` to the TABBY Auth Code, which **is** the Order Number (confirmed by `REGRESSION_PROVIDER_MATCHING_FINAL.py`, which asserts exactly this). New `core.link_tabby_payout_underlying_ids(provider_batches, matched)`:

- `normalize_tabby_payout()` now also keeps each batch's individual Order Numbers (pipe-joined, new `"Order Numbers"` column) alongside the existing `"Order Count"`.
- The new function resolves each Order Number to a matched transaction via `Provider Reference`, and only links it when the Order Number identifies **exactly one** matched transaction — same "never guess" discipline as every other auto-resolution rule in this codebase (`_auto_resolution_signature_candidates`, the ANB reserve logic, etc.). Ambiguous or unresolved Order Numbers are left unlinked; the batch still settles to `BANK RECEIVED`, it just doesn't propagate for that specific order — same behavior as before this fix, not a regression.
- Wired into both `pages/18_Settlement_Batch_Engine.py` and `pages/1_POS_Reconciliation.py`, right after `provider_batches`/`r_provider_batches` is assembled, before matching runs.

**TAMARA and TAP are intentionally NOT linked.** Their payout files don't currently carry a per-transaction reference this codebase already trusts elsewhere (TAP payout files do have an `authorization_id` column in some exports, but nothing here confirms how a TAP Auth Code lands in `matched` the way TABBY's does — linking on an unconfirmed key would be guessing, not evidence). Their batches settle to `BANK RECEIVED` at the batch level exactly as before; they stay unlinked to a specific matched transaction until that evidence exists. This is a deliberately incomplete fix, not a silently incomplete one — `PROVE_V27_END_TO_END.py` STEP 2 asserts TAP explicitly stays `Bank Settled: False` so this doesn't regress into looking fixed.

Proof output:

```
provider_batches rows: 2
  Provider  Expected Bank Amount Underlying IDs
0    TABBY                 727.0        TABBY-1
1      TAP                 384.0

  Unique Transaction ID  Bank Settled     Settlement Stage
0               TABBY-1          True        BANK RECEIVED
1                 TAP-1         False  TRANSACTION MATCHED
```

**A third, separate finding — not fixed, flagged for follow-up:** both `18_Settlement_Batch_Engine.py` and `1_POS_Reconciliation.py` label bank statements `"ANB Bank"` / `"Al Rajhi Bank"` (Settlement Batch Engine actually passes the raw filename) when the legacy `normalize_bank()` fallback fires. But `reconcile_card_batches_to_anb` / `reconcile_provider_batches_to_rajhi` filter the bank pool on an **exact** match against `"ANB"` / `"AL RAJHI"` — no `"Bank"` suffix, no filename. Any statement that falls through to the legacy parser is invisible to batch-level matching, independent of the V27 identity fixes. Not exercised by the proof run (which uses the V24 parser path — the expected path for your actual ANB/Al Rajhi statements) and not fixed here, since it needs a decision on canonical bank labels across two pages. Worth its own small follow-up.

## 3. Prove main POS Reconciliation flow

`PROVE_V27_END_TO_END.py` STEP 3 replicates the page's upload loop with a file named with "tap" in it that is also a genuine TAP payout export — the exact overlap the dedup guard (§4) exists for:

```
payout_sheets routed away from transaction classification: {('TAP_Payout_Aug2026.csv', 'Sheet1')}
pos_parts produced from the overlap file: 0
provider payout batches recovered from the payout scan: 1
```

The file is recognized once, routed to payout parsing, never also normalized as a POS transaction, and still reaches the payout-matching path exactly once.

## 4. De-dup / bank-row identity hardening

These are the three items from the original ask, unchanged from the prior draft:

- **De-dup:** the primary upload loop now checks `classify_settlement_source()` first; if a file/sheet matches a payout shape, it's routed away from `core.classify()`/`normalize_pos()`/`normalize_tender()` entirely and picked up exactly once by the existing payout scan.
- **Deterministic bank-row identity:** `_bank_row_key()` is now always `Bank Source File + Bank Source Sheet + Bank Source Row + Bank Date + Bank Amount` — no conditional fallback, narration text never in the key. `reconcile_card_batches_to_anb()` carries Source Sheet/Row forward on its output record; the reserve step in `reconcile_card_batches_advanced()` recomputes the key directly from those stored fields instead of re-searching the bank pool by Description text (which could match zero or multiple rows).
- **Legacy parser stamps Source Row/Sheet:** `normalize_bank(df, bank, source_file="", source_sheet="")` now stamps per-row `Bank Source Row`/`Bank Source Sheet` (backward compatible — existing 2-arg callers still work).

Reproduces and closes the exact double-count scenario from the V26 review (two ANB credits, same terminal/date/scheme, identical narration): both settlement batches now resolve independently to their correct, distinct bank credit.

## 5. Regression discipline going forward

Per your instruction, every settlement release now needs, at minimum: a page-level smoke test (this proof script's pattern — replicate the page's actual call sequence with real fixtures, not mocks), a direct test of the classifier against realistic column shapes for each provider, and a direct test of provider payout routing including the batch → matched-transaction propagation link. `REGRESSION_SETTLEMENT_DEDUP_AND_BANK_IDENTITY_V27.py` covers the dedup guard and bank-row identity; `PROVE_V27_END_TO_END.py` covers the classifier, Settlement Batch Engine, and main-flow proofs — both are included so they can be run as a permanent part of the suite, not one-off scripts.

## 6. Files delivered (all in the attached package)

- `core.py` — `classify_settlement_source()` fix; `normalize_bank()` row/sheet stamping; `normalize_tabby_payout()` Order Numbers; new `link_tabby_payout_underlying_ids()`.
- `logic/bank_settlement_extension.py` — deterministic `_bank_row_key()`; Source Sheet/Row carried through `reconcile_card_batches_to_anb()` and `reconcile_provider_batches_to_rajhi()`; rebuilt reserve step in `reconcile_card_batches_advanced()`.
- `pages/1_POS_Reconciliation.py` — dedup guard; updated `normalize_bank()` call site; wired `link_tabby_payout_underlying_ids()`.
- `pages/18_Settlement_Batch_Engine.py` — wired `link_tabby_payout_underlying_ids()`. This page wasn't in the original file list; it's included now because proving it functionally is what surfaced §2, and leaving it unpatched would mean "proven" and "fixed" describe different files.
- `REGRESSION_SETTLEMENT_DEDUP_AND_BANK_IDENTITY_V27.py`, `PROVE_V27_END_TO_END.py` — new tests, both pass against the patched files (re-verified after the §2 fix, alongside the existing regression suite: `REGRESSION_SETTLEMENT_BATCH_ENGINE_V18`, `REGRESSION_PROVIDER_MATCHING_FINAL`, `REGRESSION_MAIN_POS_PAGE_WIRING_V26`, `REGRESSION_STORE_614_EXACT_MATCHES`, `REGRESSION_STORE613_SALESDETAILS_BRIDGE`, `REGRESSION_ADVANCED_SETTLEMENT_EXCEPTION_V25` — all still pass unchanged. `REGRESSION_BANK_SETTLEMENT_PROPAGATION_V24` needs two real sample bank-statement files at a hardcoded local path never included in any upload; couldn't run it here, not a code issue).

Built against the V26 copies already on file. `core.py` was only ever sent once, at the very start of this whole review, not re-sent alongside V26 — diff it against your actual current `core.py` before applying, don't assume it matches. `db.py` has never been sent in this engagement and remains completely unverified.

## 7. Explicitly out of scope

- The many-POS-batches-to-one-bank-credit gap — untouched, deferred to V28 as agreed; needs its own accounting-proof aggregation design, not a broad-amount-aggregation shortcut.
- TAMARA and TAP propagation linking (§2) — deferred until a trusted per-transaction reference is confirmed for each.
- The bank-label exact-match mismatch on the legacy parser path (§2) — flagged, not fixed.
- `db.py`, `21_Month_End_Close_Calendar.py` — untouched.

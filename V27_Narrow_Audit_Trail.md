# RetailRecon AI — V27: Settlement Input De-duplication & Bank Row Identity Hardening

Scope, as agreed: three narrow fixes only. No change to matching thresholds, no attempt at the many-batches-to-one-credit problem (that's V28), nothing in `db.py` or any page other than `1_POS_Reconciliation.py`. A fourth, unplanned fix is included because it was found while building and testing the other three — see §0, it's load-bearing for the rest of this release to actually do anything.

All code below is delivered as full patched files (`core.py`, `logic/bank_settlement_extension.py`, `pages/1_POS_Reconciliation.py`) plus a new regression test, built directly against the V26 source you sent. Every claim in this doc was verified by actually running the patched functions against synthetic data, not just by reading the diff — see §4.

## 0. Unplanned but necessary: `classify_settlement_source()` never actually matched anything

While building the dedup guard (§1) and writing an executable test for it, `core.classify_settlement_source()` was run against realistic Tabby/Tamara/TAP payout column shapes and it returned `""` for all three, every time.

Root cause: the function builds its column set via `norm_cols(df)`, which upper-cases every column name and replaces separators with `_` (e.g. `"Payout ID"` → `"PAYOUT_ID"`). It then compares that against its own literal search terms, which are lowercase and space/underscore-separated (`"payable to merchant"`, `"payout_id"`, `"transferred amount"`, ...). `"payout_id" in {"PAYOUT_ID", ...}` is always `False` — the case never matches, for any provider, for any file. Confirmed directly:

```
normalized columns: ['PAYOUT_ID', 'SETTLEMENT_ID', 'AMOUNT']
classify_settlement_source result: ''
```

Impact: this function is the single gate that routes an uploaded file into `normalize_tamara_payout` / `normalize_tabby_payout` / `normalize_tap_payout`. It is called from **two** places — `pages/18_Settlement_Batch_Engine.py` (confirmed by grep against your V25 copy, the only one on file) and the new V26 wiring in `pages/1_POS_Reconciliation.py`. Since it always returns `""`, **provider-payout-to-Al-Rajhi batch matching has likely never actually fired in any release**, regardless of what files were uploaded — not because of anything V26 changed, this bug predates V26. No regression test in the full uploaded suite calls `classify_settlement_source()` at all, which is why nothing caught it.

Fix (in `core.py`): build the comparison column set from the raw column headers, lowercased only — no case/separator transform — which is the form the existing literal search terms were clearly written for. The detection literals and branch logic are untouched; only how `cols` is built changed. Two lines.

This isn't scope creep on V27's stated goals — it's a precondition for them. §1's dedup guard and the "same file processed twice" scenario it prevents cannot be observed or tested at all while the upstream classifier never fires. Flagging it separately here so it's not confused with the three items you asked for, and so it can be pulled out of the patch if you'd rather ship it separately or verify it yourselves first.

## 1. Prevent double-processing of a payout file recognized by both detectors

**Problem:** `provider_signature()` (used by `core.classify()`) recognizes a file as TABBY/TAMARA/TAP purely from a filename substring, independent of the file's actual role (transaction export vs. payout/settlement report). `classify_settlement_source()` recognizes a payout report by column shape. A file matching both — e.g. `TAP_Payout_Aug2026.xlsx` with genuine payout columns — would previously be normalized twice: once as `POS`-type transaction rows via `core.normalize_pos()`, and independently as a payout batch via the V26 payout scan.

**Fix (`pages/1_POS_Reconciliation.py`):** in the primary upload loop, classify each file/sheet by settlement-source shape *first*. If it matches a payout type, add it to a `payout_sheets` set and `continue` — it never reaches `core.classify()`/`normalize_pos()`/`normalize_tender()`. It's still picked up exactly once, downstream, by the existing V26 payout-scan block, which is otherwise unchanged. A file/sheet is now normalized as either a transaction file or a payout batch, never both.

## 2. Fully deterministic bank-credit identity

**Problem (from the V26 review):** `_bank_row_key()` preferred `Bank Source File::Bank Source Row`, but fell back to a hash of `Bank/Date/Amount/Description` when Source Row was missing — and the "reserve" step in `reconcile_card_batches_advanced` re-derived which bank row was already claimed by filtering on `Bank Source File` + `Description` text equality, which could match zero or multiple rows when two credits share identical narration, silently widening the double-count window.

**Fix (`logic/bank_settlement_extension.py`):**
- `_bank_row_key()` is now built from `Bank Source File + Bank Source Sheet + Bank Source Row + Bank Date + Bank Amount` only — always, no conditional fallback, no narration text anywhere in the key.
- `reconcile_card_batches_to_anb()` now carries `Bank Source Sheet` and `Bank Source Row` forward on its output record (it already carried Source File, Bank Date, and Actual Bank Amount).
- The reserve step in `reconcile_card_batches_advanced()` no longer re-searches the bank pool by filtering on Source File + Description. It directly recomputes `_bank_row_key()` from the five fields already stored on the output record from the base pass. Deterministic, O(1) per row, no ambiguity, no ability to match zero or multiple candidates.

Same two extra fields (`Bank Source Sheet`, `Bank Source Row`) were also added to `reconcile_provider_batches_to_rajhi()`'s output record for consistent audit trail, even though that function didn't have the two-pass reserve problem (it only ever does one pass, so its existing index-based `used` set was already safe).

## 3. Legacy bank-parser path stamps Source Row and Source Sheet

**Problem (from the V26 review):** any bank statement format outside ANB/Al Rajhi falls back to `core.normalize_bank()`, which never stamped a per-row `Bank Source Row`. Combined with the page's uniform `Bank Source File` stamp, every row from a legacy-parsed file collapsed to the identical `_bank_row_key()`.

**Fix (`core.py`):** `normalize_bank(df, bank, source_file="", source_sheet="")` now takes the source file/sheet as optional keyword arguments (backward compatible — existing 2-arg callers, including regression tests, are unaffected) and stamps `Bank Source File`, `Bank Source Sheet`, and a positional `Bank Source Row` (1-based, reflecting the row's position in the original uploaded sheet, before blank/zero rows are filtered out — same convention as the ANB/Al Rajhi parser) on every row. `pages/1_POS_Reconciliation.py`'s call site was updated to pass `source_file=f.name, source_sheet=sheet`.

## 4. Verification performed

Everything above was tested by execution, not just reading the diff:

- `python3 -m py_compile` on all three patched files — clean.
- Ran the existing regression suite against the patched `core.py`/`bank_settlement_extension.py` where fixtures were available: `REGRESSION_SETTLEMENT_BATCH_ENGINE_V18`, `REGRESSION_PROVIDER_MATCHING_FINAL`, `REGRESSION_MAIN_POS_PAGE_WIRING_V26`, `REGRESSION_STORE_614_EXACT_MATCHES`, `REGRESSION_STORE613_SALESDETAILS_BRIDGE`, `REGRESSION_ADVANCED_SETTLEMENT_EXCEPTION_V25` all still pass unchanged. (`REGRESSION_BANK_SETTLEMENT_PROPAGATION_V24` needs two real sample bank-statement files at a hardcoded `/mnt/data/...` path that were never part of the uploaded package — couldn't run it here; it's a test-data availability gap, not a code issue.)
- New `REGRESSION_SETTLEMENT_DEDUP_AND_BANK_IDENTITY_V27.py` (included) — combines a static/AST check on the page (that the dedup guard runs and `continue`s before `core.classify()`, same style as the V26 wiring test) with fully executable checks against the real functions:
  - confirms `provider_signature()` and `classify_settlement_source()` really do both fire on the same synthetic TAP payout file (proving the overlap the guard exists for) — and, post-fix, that `classify_settlement_source()` now correctly returns `TAP_PAYOUT` instead of `""`;
  - confirms the legacy `normalize_bank()` path now gives two rows with identical narration text two distinct, deterministic keys, and that row numbers reflect original position even when a zero-amount row is dropped;
  - reproduces the exact double-count scenario flagged in the V26 review (two ANB credits, same terminal/date/scheme, identical narration) and confirms both settlement batches now resolve independently to their correct, distinct bank credit, with nothing left stranded or double-reserved.

All of the above pass against the patched files.

## 5. Files delivered

- `core.py` — `normalize_bank()` signature + row stamping; `classify_settlement_source()` case-normalization fix.
- `logic/bank_settlement_extension.py` — deterministic `_bank_row_key()`; `reconcile_card_batches_to_anb()` carries Source Sheet/Row forward; `reconcile_card_batches_advanced()` reserve step rebuilt; `reconcile_provider_batches_to_rajhi()` carries Source Sheet/Row for audit trail.
- `pages/1_POS_Reconciliation.py` — dedup guard in the primary upload loop; updated `normalize_bank()` call site.
- `REGRESSION_SETTLEMENT_DEDUP_AND_BANK_IDENTITY_V27.py` — new regression test covering all four fixes above.

These were built against the V26 copies of `core.py` and `1_POS_Reconciliation.py` already on file from your uploads. `core.py` in particular was only ever sent once, at the start of this whole review (not re-sent alongside V26) — please diff it against your actual current `core.py` before applying, rather than assuming it matches. Per your note on verification going forward: everything in this document is directly diff/execution-verified against the files I have; nothing here is "assumed unchanged."

## 6. Auditability going forward

Per your instruction, `core.py`, `db.py`, and the older, unchanged pages should be included in every full release package from here on, not just the files that changed — so an external reviewer (or the next AI review pass) can diff-verify the whole package instead of relying on release notes for what's "unchanged." This review could only verify `core.py` this time because it happened to have been sent once, early; `db.py` has never been sent in this entire engagement and remains completely unverified end to end.

## 7. Explicitly out of scope for V27 (unchanged, by design)

- The documented many-POS-batches-to-one-bank-credit gap — left pending for V28, as agreed. Nothing in this patch touches the aggregate/gross-proof matching logic itself, only how already-claimed bank rows are tracked.
- `db.py`, `18_Settlement_Batch_Engine.py`, `21_Month_End_Close_Calendar.py` — not touched. Note `18_Settlement_Batch_Engine.py` calls the same now-fixed `classify_settlement_source()`, so it should start actually matching provider payouts too once this patch lands — worth a real test with it before the next full release, since it wasn't part of this patch's file list.

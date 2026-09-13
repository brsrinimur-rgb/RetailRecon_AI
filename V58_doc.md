# V58 — Bulk Adjustment JV Creation from "Missing D365" Exceptions

**Date:** 2026-09-13
**Files changed:** `pages/28_Late_Transaction_Adjustment_JV.py`
**Files added:** `logic/adjustment_bulk_extension.py`, `REGRESSION_V58_BULK_ADJUSTMENT_JV.py`
**Also included:** `Missing_D365_Bulk_Adjustment_Batch_Sep1-12_2026.xlsx` — ready-made batch file, pre-built from your real data, not code

## What you asked for

"link the data, create JV in the system" — you wanted the 32 "Missing D365" reconciliation exceptions (1–12 Sep 2026, SAR 66,280.11 total) fed directly into JV creation, instead of the follow-up-email path, and instead of retyping each one by hand.

## Why the existing pages didn't fit

- **JV Creation** (page 24) only works on transactions that are already **Matched** and **bank-settled** — a "Missing D365" exception is neither, so it can never reach that page.
- **Late Transaction Adjustment JV** (page 28) is exactly the right concept — a controlled adjustment JV for late/missing transactions after period close — but it only had a single-row form: one Store/Provider/Amount/Reason at a time. Doing 32 of them by hand would be slow and error-prone.

## What changed

Page 28 gained a **"Bulk create adjustment JVs from a file"** section, above the existing single-row form (which is completely unchanged and still works exactly as before).

- Upload an `.xlsx` or `.csv`. Two shapes are recognized automatically:
  - A simple manual template: `Store`, `Provider`, `Amount`, `Reason`.
  - Your actual reconciliation-exceptions export shape: `Store Code`, `Auth Code`, `POS Tender`, `Net Amount`, `Terminal ID`, `Status`, `Remarks` — the same columns you already get out of the app.
- Each row is normalized into Store/Provider/Amount/Reason and shown in an editable preview grid before anything is created — Finance can uncheck a row, fix an amount, or change the provider bucket first.
- Provider values are collapsed the same way the JV Creation page already does: MADA/VISA/MASTER(CARD) → **CARD**; AMEX/TABBY/TAMARA/TAP stay separate.
- When no `Reason` column is present, one is built automatically, e.g.: *"Missing D365 - Auth Code 016934 - Terminal 55610703 - Valid mapped provider transaction found but no matching D365 Store Tender transaction."*
- Clicking **"CREATE ALL INCLUDED ADJUSTMENT JVS"** writes one row per included transaction into the same `adjustments` table the single-row form already uses, with status **PENDING APPROVAL** — identical to a manually entered one. Nothing here auto-approves or posts to D365; it only raises the adjustment JV record, same control as before.
- Rows missing a Store, Amount, or Reason are skipped individually with a clear reason shown, rather than blocking the whole batch.

## The data-shaping logic lives separately

`logic/adjustment_bulk_extension.py` holds the pure normalization logic (no Streamlit) so it's independently testable — same pattern as `logic/bank_settlement_extension.py` and the other `logic/` modules already in your app.

## Your 32 transactions, ready to go

`Missing_D365_Bulk_Adjustment_Batch_Sep1-12_2026.xlsx` is built directly from the exceptions data you pasted (cross-checked against your `Reconciliation_47.xlsx` — identical 32 rows, same amounts). Once you've uploaded the two code files below, upload this file straight into the new "Bulk create adjustment JVs from a file" section on page 28 — it will parse as 32 rows totaling **SAR 66,280.11** across 12 stores, ready to review and create.

## Verification

- `py_compile` clean on both changed/new Python files.
- New `REGRESSION_V58_BULK_ADJUSTMENT_JV.py` (25 checks): simple-template normalization, real exceptions-shape normalization, the full CARD/AMEX/TABBY/TAMARA/TAP provider matrix, an unrecognized provider staying visible instead of being silently dropped, messy/blank input not crashing, an explicit Reason column always winning over the auto-built one, and empty-upload handling.
- Full round-trip smoke test against your real `db.py` (`append_adjustment`/`load_adjustments`) — confirmed rows land correctly with status PENDING APPROVAL.
- End-to-end sanity check: read `Missing_D365_Bulk_Adjustment_Batch_Sep1-12_2026.xlsx` back through the new logic exactly as the page would — 32 rows, total ties out to SAR 66,280.11 exactly.
- Re-ran your full existing regression suite (83 files) before and after this change: same 57 pass / 26 fail both times, and the 26 are pre-existing (missing sample files not in this session, stale test-path assumptions, one already-known V56 test-update gap) — none newly caused by this change.

## How to upload

Add two files (new paths) and replace nothing existing:
- `pages/28_Late_Transaction_Adjustment_JV.py` (replaces existing file — only the new upload section was added, the rest is untouched)
- `logic/adjustment_bulk_extension.py` (new file)
- `REGRESSION_V58_BULK_ADJUSTMENT_JV.py` (new file, optional but recommended)

Then, whenever ready, upload `Missing_D365_Bulk_Adjustment_Batch_Sep1-12_2026.xlsx` into the new section on page 28 to raise all 32 adjustment JVs in one pass.

# V61 — Multi-Sheet Raw Provider Fix, and a Third Recurrence of the Terminal ID Bug

**Date:** 2026-09-13
**File reviewed:** your uploaded `20_Missing_D365_Follow_Up_MULTI_SHEET_FIX 1.py`
**Fix applied:** one line, restoring the Terminal ID cleanup (again)
**File added:** `REGRESSION_V61_MISSING_D365_FOLLOWUP_MULTISHEET_FIX.py`

## What's genuinely new and good

`_read_raw_provider()` was rewritten to scan **every sheet** in an uploaded raw POS provider workbook, not just the first one. Your UNITED_LUXURY transaction exports are multi-sheet (typically `Details_mada` and `Details_CC`), and the old code only ever read the default sheet — so if the real transaction rows for a card type lived on a later sheet, Card Number / Transaction Time enrichment would silently miss them. The new version detects each sheet's own header row independently, skips cover/summary sheets that don't contain transaction columns, and combines every usable sheet before matching.

I built a synthetic 3-sheet workbook (a cover page + `Details_mada` + `Details_CC`, each with a different matching transaction) to test this end-to-end: both real sheets were found, the cover sheet was correctly skipped, and a two-row queue was correctly enriched from the two different sheets of the same file. This is a real fix for a real gap — worth keeping.

## One regression, again

**Terminal ID lost its `.0` cleanup a third time.** This upload went back to:

```python
"Terminal ID": (
    exc["Terminal ID"].fillna("").astype(str).str.strip()
    if "Terminal ID" in exc.columns else ""
),
```

— the exact same code V60 already fixed (and that your own screenshot caught live in production once before). Reproduced against your real `Reconciliation_latest.xlsx`: Terminal ID came back as `"55610703.0"` again. Fixed by routing it through `_clean_code()` the same way Store Code already is:

```python
"Terminal ID": (
    exc["Terminal ID"].map(_clean_code)
    if "Terminal ID" in exc.columns else ""
),
```

Everything else in this upload — the date fix, Store Code cleanup, Authorization Code, the raw-file enrichment matching logic, the "never guess" behavior — was carried over correctly from V60 and is unaffected.

**Worth flagging on your end:** this is the same single field regressing for the third time across three separate uploads. If different people (or different AI sessions) are patching this file independently without pulling the latest fixed version first, that's most likely why it keeps reverting. Starting each new edit from the last delivered/fixed copy of this page would prevent this recurring.

## Verification

- `py_compile` clean.
- New `REGRESSION_V61_MISSING_D365_FOLLOWUP_MULTISHEET_FIX.py` (17 checks): re-confirms the date fix, Store Code cleanup, and Terminal ID cleanup all still hold; adds new coverage for the multi-sheet read (cover sheet skipped, both data sheets combined) and enrichment matching across two different sheets of the same uploaded file; keeps the "never guess on a wrong amount" check.
- Re-confirmed against your actual `Reconciliation_latest.xlsx`: 13 real Missing D365 rows, correct 2026 dates, no `.0` on Terminal ID or Store Code.

## How to upload

Replace one file (same path):
- `pages/20_Missing_D365_Follow_Up.py`

Optional but recommended:
- `REGRESSION_V61_MISSING_D365_FOLLOWUP_MULTISHEET_FIX.py`

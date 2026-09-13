# V63 — Time-Format Rewrite Is Solid, But Terminal ID Regressed a Fourth Time

**Date:** 2026-09-13
**File:** `pages/20_Missing_D365_Follow_Up.py` ("TIME_FIX" upload)
**Fix applied:** one line, restoring Terminal ID cleanup (again)
**File added:** `REGRESSION_V63_MISSING_D365_FOLLOWUP_TIMEFIX_TERMINALID_REFIX.py`

## What's good in this upload

This upload independently rewrote the transaction-time formatter as `_format_transaction_time()`, replacing V62's version. It's a solid rewrite, and arguably better than mine in one respect: it applies the formatter in three places instead of one — when the report loads, during raw-file enrichment, **and again inside `_build_email()`** — so even if a Transaction Time value ever reaches the queue unformatted through some other path, the email text still renders it correctly rather than depending on one single call site staying correct. I tested it against the exact real case from your CSV (`131911` → `13:19:11`) plus a battery of edge cases (5-digit values, Excel time fractions, already-clean strings, invalid values) — all correct, and it never guesses on something out of range.

## The recurring regression

**Terminal ID lost its `.0` cleanup again — the fourth time now** across separate uploads of this one page. It had reverted to:

```python
"Terminal ID": (
    exc["Terminal ID"].fillna("").astype(str).str.strip()
    if "Terminal ID" in exc.columns else ""
),
```

Reproduced against your real `Reconciliation_latest.xlsx`: `"55610703.0"` again. Fixed the same way as every time before:

```python
"Terminal ID": (
    exc["Terminal ID"].map(_clean_code)
    if "Terminal ID" in exc.columns else ""
),
```

**This is worth addressing directly, not just patching again.** The same single line has now regressed four separate times, always in isolation from whatever other real improvement the upload was making (multi-sheet reading, then this time-format rewrite). That pattern strongly suggests each edit is starting from an older base copy of this file rather than the last one I delivered and verified — likely different people, or different AI sessions, editing independently without pulling the latest fixed version first. I can keep re-fixing it each time it comes back, but if whoever edits this file next starts from `deliver_v63`'s copy (or whatever I deliver after this) instead of an older one, it should stop happening.

## Verification

- `py_compile` clean.
- New `REGRESSION_V63_MISSING_D365_FOLLOWUP_TIMEFIX_TERMINALID_REFIX.py` (20 checks): the exact real HHMMSS case and edge cases for the new `_format_transaction_time()`, confirms the formatted time also appears correctly inside the generated email body, re-confirms Terminal ID/Store Code/date cleanup and multi-sheet raw-file reading all still hold, and the "never guess on a wrong amount" check.
- Re-confirmed against your actual `Reconciliation_latest.xlsx`: 13 real rows, no `.0` on Terminal ID or Store Code.

## How to upload

Replace one file (same path):
- `pages/20_Missing_D365_Follow_Up.py`

Optional but recommended:
- `REGRESSION_V63_MISSING_D365_FOLLOWUP_TIMEFIX_TERMINALID_REFIX.py`

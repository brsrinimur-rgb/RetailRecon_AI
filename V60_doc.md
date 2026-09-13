# V60 — Code Review of the Rewritten Missing D365 Follow-Up Page

**Date:** 2026-09-13
**File reviewed:** your uploaded `20_Missing_D365_Follow_Up.py` (a full rewrite of the page — not built by me, and not the file V59 fixed)
**Fix applied:** one line, restoring V59's date fix
**File added:** `REGRESSION_V60_MISSING_D365_FOLLOWUP_V3_DATE_FIX.py`

## What I checked

You (or whoever wrote this) rewrote the page from scratch after V59. It's a real improvement in several ways:

- **Header-row detection is now stricter and safer** — it requires "Store Code", "Status", *and* "POS Total" to all appear in the same row before treating it as the header, instead of my looser single-column check. Verified correct against your real report.
- **Store Code cleanup is correct** — `_clean_code()` strips the spurious ".0" the same way my V59 fix did, and I confirmed it against your real data.
- **A genuinely useful new capability**: uploading the original raw POS provider files to backfill Card Number and Transaction Time, matched by normalized Auth Code (ignoring leading zeros/punctuation) + exact Amount, with Terminal ID as a tiebreaker — and it correctly *refuses* to guess when multiple files disagree or nothing matches uniquely. I built a synthetic provider file to test this end-to-end and it worked exactly as intended, including correctly declining to match when the amount didn't line up. This is exactly the capability that was blocking the original follow-up-email task (no more needing a separate raw-file lookup step in chat).

## Two real regressions found and fixed

**1. The Excel-serial-date bug.** The rewrite didn't carry over V59's fix for it. "Transaction Date" was set directly from the report's raw `POS Date` value — a bare number like `46266.0` — and the email builder's `pd.to_datetime()` silently misreads a bare number like that as a Unix timestamp. Confirmed against your real report: the generated follow-up email showed **"01-Jan-1970"** instead of the real date. Fixed by re-adding the same `_report_date()` helper from V59 (interprets the number against Excel's real epoch) and applying it when the queue is built. Confirmed fixed: the same real data now correctly shows "01-Sep-2026".

**2. Terminal ID also had the spurious ".0" — you actually caught this one live.** Your screenshot of the deployed page showed Terminal ID as "55610703.0" / "55610701.0" instead of "55610703" / "55610701". `_clean_code()` (which correctly fixes this exact issue for Store Code) simply wasn't applied to the Terminal ID field — it used a plain `str()` instead. Beyond the display glitch, this also silently weakened the new raw-file-enrichment feature: it uses Terminal ID as a tiebreaker when an Auth Code + Amount match isn't unique, and an exact string comparison against "55610703.0" would fail against a raw file's clean "55610703". Fixed by routing Terminal ID through `_clean_code()` the same way Store Code already was. Confirmed against your real report: no more ".0" on any Terminal ID.

## Verification

- `py_compile` clean.
- Updated `REGRESSION_V60_MISSING_D365_FOLLOWUP_V3_DATE_FIX.py` (14 checks): the date fix (against a synthetic report in RetailRecon's real export shape), Store Code *and* Terminal ID cleanup, and the new raw-file enrichment feature — both a successful match and a deliberate non-match (wrong amount) to confirm it never guesses.
- Re-confirmed against your actual uploaded reconciliation report: 1 real Missing D365 row extracted correctly, real 2026 date, no 1970 artifact, no ".0" on Terminal ID.

## How to upload

Replace one file (same path):
- `pages/20_Missing_D365_Follow_Up.py`

Optional but recommended:
- `REGRESSION_V60_MISSING_D365_FOLLOWUP_V3_DATE_FIX.py`

Nothing else in your rewrite needed changing — the rest of it is solid.

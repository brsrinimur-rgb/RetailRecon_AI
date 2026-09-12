# V57 — Copilot Crash Guard + Stale Test Fix

**Date:** 2026-09-13
**File changed:** `pages/29_AI_Finance_Copilot.py`
**Also included:** an updated `REGRESSION_V53_GL_CORRECTIONS_MAPPING_DETAILS_MISROUTE.py` (a leftover in your repo that was never replaced when V56 shipped)

## What happened

You hit a crash right after uploading V56 — Streamlit showed a redacted `TypeError` at the line that hands data to the AI Copilot. I checked your live repo directly: both files were correctly in sync (that wasn't the cause), and I could not reproduce a crash by feeding the real reconciliation pipeline the same kind of data. Streamlit Cloud hides the real error message for security, so there was no way to see exactly what broke.

## What I changed

Rather than keep guessing, I wrapped that one call in a safety net: if a question ever hits an unexpected error again, the Copilot now shows the **real, unhidden error message** right in the chat instead of crashing the whole page. The page stays usable — you can keep asking other questions — and if it happens again, you can copy that exact message back to me and I'll fix the real cause immediately (Streamlit's own redaction was the main thing standing in the way of a fix before).

This only touches how errors are handled — it doesn't change any answer logic from V56.

## Also fixed

One test file in your repo (`REGRESSION_V53_...MISROUTE.py`) still expected the pre-V56 behavior for one specific question. It wasn't the cause of your crash (test files don't run inside the live app), just a leftover I noticed while checking things — included here so your test suite stays accurate.

## Verification

- Re-ran every Copilot regression test present in your repo — all pass, including the corrected V53 test.
- `py_compile` clean on both files.

## How to upload

Replace two files (same paths):
- `pages/29_AI_Finance_Copilot.py`
- `REGRESSION_V53_GL_CORRECTIONS_MAPPING_DETAILS_MISROUTE.py` (test file only, optional but recommended)

If you still see an error after this, please paste whatever the chat shows now — it'll be the real message this time, not a redacted one, and that will let me fix it directly.

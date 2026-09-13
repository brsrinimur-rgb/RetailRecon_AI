# V59 — Missing D365 Follow-Up: Blank-CSV Bug Fixed

**Date:** 2026-09-13
**File changed:** `pages/20_Missing_D365_Follow_Up.py`
**File added:** `REGRESSION_V59_MISSING_D365_FOLLOWUP_REPORT_PARSE.py`

## What you reported

You uploaded `RetailReconAI_Reconciliation - 2026-09-13T195311.652.xlsx` into the new "Missing D365 Follow-Up" page (20) and downloaded the CSV — it came back with 195 rows, every single one blank (only "Value of Sales" = 0.0 and "Follow-Up Status" populated).

## Three real bugs found and fixed, confirmed against your actual uploaded file

**1. The header-row bug (the main cause of the blank CSV).** RetailRecon's own exported reports write a title row and a "Generated ... | N row(s)" row before the real column header — the header is not row 1. The page read the sheet assuming the header was row 1, so pandas never saw real column names like "Store Code" or "Status" (they came out as "Unnamed: 1", "Unnamed: 2", etc., with the real header text buried as data three rows down). That silently broke the "Missing D365 only" filter — every exception row (all 194 of them, not just the Missing D365 ones) passed through with every field blank. Fixed by scanning the first few rows for the real header instead of assuming a fixed position, so it keeps working even if the report layout changes later.

**2. Store Code / Terminal ID silently failing to match your Store Email Master.** Once the header bug is fixed, Excel reads whole-number ID columns (Store Code, Terminal ID) as floating-point — 615 becomes 615.0. Converted to text naively, that's "615.0", which never matches the plain "615" in your Store Email Master — every row's To/CC email would still have come back blank even with bug #1 fixed. Fixed by stripping the spurious ".0" before any matching happens.

**3. Transaction Date would have shown as 1970, not 2026.** The report's date column is stored as a raw Excel serial number (e.g. 46266). The page's own email-builder runs that through a generic date parser, which reads a bare number like that as a Unix timestamp — you'd have gotten a nonsense date like 01-Jan-1970 in the actual follow-up email text, with nothing to signal it was wrong. Fixed by interpreting the number against Excel's real epoch instead.

## Confirmed against your real data

Re-running your uploaded report (13-Sep-2026 16:52 run) through the fixed page now correctly produces:
- **13 real "Missing D365" transactions** (out of 191 total exceptions — the rest are Missing POS, Review, Merchant Mapping Required, etc., correctly excluded)
- **SAR 17,511.01 total**
- Clean Store Codes (615, 640, 634, 624, 601, 643, 652, 644 — no ".0")
- Real 2026 dates (e.g. 01-Sep-2026, not 1970)

Store Code/Auth Code/amounts all match your `Reconciliation_47.xlsx`-style export exactly — the underlying reconciliation numbers were always correct; only this page's parsing of the exported report was broken.

## What's unchanged (a pre-existing, known limitation — not a bug I fixed here)

Transaction Time and full Card Number still won't populate from an uploaded reconciliation report, because that report format never carries them (confirmed earlier this engagement — the app's own POS ingestion doesn't retain them either, from either pipeline). This page still needs the raw daily POS provider file, or the live in-session path (`unmatched_pos`), to get those two fields. Everything else — Store Code, Store Name, Payment Type, Amount, Auth Code, Terminal ID, the Missing D365 filter, and the recipient match — is now correct from just the reconciliation report.

## One more thing worth flagging (not fixed, your call)

`pages/19_Store_Email_Master.py` saves to a plain local file (`data/store_email_master.csv`). On Streamlit Cloud that file lives only in the running container — it will very likely be wiped every time you push a new commit and the app redeploys (which, going by this engagement, is often). If your store email list keeps disappearing after an upload, that's why. Happy to move it into the app's existing `retailrecon.db` (same place adjustments/corrections/etc. already live) so it survives redeploys — just say the word, since that's a storage-location change I didn't want to make without checking with you first.

## Verification

- `py_compile` clean.
- New `REGRESSION_V59_MISSING_D365_FOLLOWUP_REPORT_PARSE.py` (16 checks) using a synthetic report built in RetailRecon's exact real export shape (title row, "Generated..." row, blank row, header — matching `report_export.py`'s own layout) plus your real uploaded file for end-to-end confirmation.
- Re-ran your full existing regression suite (83 files) before and after: same 58 pass / 25 fail both times (all 25 pre-existing/environmental — missing sample files not in this session, stale test-path assumptions — none newly caused by this change).

## How to upload

Replace one file (same path):
- `pages/20_Missing_D365_Follow_Up.py`

Optional but recommended:
- `REGRESSION_V59_MISSING_D365_FOLLOWUP_REPORT_PARSE.py`

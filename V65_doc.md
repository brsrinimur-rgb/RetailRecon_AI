# V65 — Bulk Send: All Stores in One Click

**Date:** 2026-09-13
**File:** `pages/20_Missing_D365_Follow_Up.py` (built on V64)
**Change:** new "6. Bulk Send: All Stores" section
**File added:** `REGRESSION_V65_MISSING_D365_FOLLOWUP_BULK_SEND.py`

## What changed

Section 5 (from V64) still sends one email at a time for whichever store you've selected in Section 4 — that stays exactly as it was. New **Section 6** sends to every store in the queue in one action, so you don't have to pick each store from the dropdown and click Send yourself.

For each distinct store: it groups that store's Missing D365 rows into one email (same grouping the single-store preview already uses), and sends it using the same Secrets-based SMTP setup from V64. A store with no recipient email is **skipped**, not treated as an error — it never blocks the rest of the batch. If a send fails for some reason (bad credentials, an SMTP rejection), that one store is recorded as **failed** with the real error message, and the batch keeps going through the remaining stores rather than stopping.

After it runs, you get a table — Store Code / Status / Detail — showing exactly what happened to each store, plus a one-line summary ("X sent, Y skipped, Z failed").

Since a bulk send is more consequential than a single email, it sits behind its own separate confirmation checkbox (naming how many stores it will attempt), on top of the same Secrets requirement from V64 — it isn't available until email sending is configured there first.

**One thing worth knowing:** bulk send always uses the auto-generated Subject/Body for each store, not any manual edits you made in Section 4's preview boxes — there's no way to hand-edit dozens of emails individually in one batch action. If a specific store's email needs manual wording, send that one individually in Section 5 instead.

## Verification

No real email was sent while building or testing this. Instead:
- `py_compile` clean.
- New `REGRESSION_V65_MISSING_D365_FOLLOWUP_BULK_SEND.py` (16 checks): a 3-store scenario (one sends fine, one has no recipient, one is made to fail) confirms sends/skips/failures are all reported correctly and that one bad store never blocks the others; re-confirms every check from V64 (message construction against a mocked SMTP server, `_parse_addrs`, `_smtp_configured` gating) and the underlying report-parsing fixes from V59–V63.

## How to upload

Replace one file (same path):
- `pages/20_Missing_D365_Follow_Up.py`

Optional but recommended:
- `REGRESSION_V65_MISSING_D365_FOLLOWUP_BULK_SEND.py`

No new Secrets needed beyond what V64 already required.

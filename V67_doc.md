# V67 — BNPL/TAP Reconciliation Page Review (New Page, First-Time Delivery)

**Date:** 2026-09-22
**Reviewed:** two new files you uploaded, neither written by me —
`21_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` and `37_BNPL_GL_Reconciliation.py1`
**Delivered:** `37_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` (fixed) +
`REGRESSION_V67_BNPL_TAP_REVIEW_FIXES.py`

## Which of your two files to use

`37_BNPL_GL_Reconciliation.py1` is an earlier draft: TABBY + TAMARA only, no TAP.
`21_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` is a strict superset — same TABBY/TAMARA
logic, plus full TAP support (parser, settlement grouping, GL tagging, UI uploader) —
confirmed line-by-line with a diff, nothing else changed between them. So `21_...TAP.py`
is the one to keep; the `.py1` draft can be discarded once this is uploaded.

## Important — don't upload it as page 21

Your live app already has a `pages/21_Month_End_Close_Calendar.py` — a real, working
"Accounting Period Control" page. Uploading the new file under the `21_` number would
collide with it (Streamlit numbers pages by this prefix). I renamed the delivered file to
`37_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` — page 37 is unused in your app, and it's
the number your own earlier draft was already using.

## What I found and fixed

**1. TABBY refunds were silently booked as sales (the real bug).**
The code that reads each row's transaction type looked only for a column named exactly
`"Type"`. But real TABBY exports use `"Order Type"` — confirmed because the file's own
header-detection logic already expects that exact column (it looks for "ORDERTYPE" when
scanning for the header row). Since `"Order Type"` and `"Type"` don't match, the lookup
silently failed every time, `Event` was always blank, "REFUND" was never detected, and
every refund's Gross Amount, Fee, VAT and Net Settlement kept a **positive** sign instead
of negative. I reproduced this directly against the original code (a refund row came out
as `Event: SALE, Gross Amount: 300.0`), then confirmed the fix (`Event: REFUND,
Gross Amount: -300.0`, and it now matches its POS refund line correctly). In production
this would have overstated TABBY sales/settlement totals by double the value of every
refund that occurred, and refund rows would never reconcile against POS.
Fix: read `"Order Type"` first, keep `"Type"` as a fallback.

**2. The Excel download would have crashed on first use.**
Section 8 built the download file with `pd.ExcelWriter(..., engine="xlsxwriter")`, but
`xlsxwriter` isn't installed in your app (`requirements.txt` only has `openpyxl`, which
every other page uses). The first click on "Download" would have raised
`ModuleNotFoundError: No module named 'xlsxwriter'`. Fixed by switching to
`engine="openpyxl"` — no xlsxwriter-only formatting was used, so nothing else changed.

**3. The page had no login/role gate and didn't match your app's look.**
Every other page in your app calls `auth.require_login({...})` and
`auth.render_user_sidebar()` at the top, plus `theme.global_css()` /
`theme.top_banner(...)` for the shared banner — login is enforced per-page in a
Streamlit multi-page app, there's no central gate. This new page skipped all of that, so
as uploaded, anyone with the link could open it with no login and no role check, and it
wouldn't show your app's sidebar/branding. Added the same wiring the rest of the app
uses, gated to Admin / Finance Manager / Finance Checker (matching your other
reconciliation-control pages).

## What I checked and did NOT find a bug in

I went carefully through a suspected `numpy.int64` issue in `parse_date()` — a whole-number
Excel date column can read back as `numpy.int64`, which fails an `isinstance(v, (int, float))`
check that only catches Python's native `int`/`float`. In isolation this does cause a
garbage 1970 date. But every parser in this file reads values through
`df.iterrows()` on a DataFrame that always mixes text columns (references, IDs) with
numeric ones — and pandas boxes each row's cells to plain Python types when it does that,
so the value `parse_date()` actually receives is always a native `int`, not `numpy.int64`.
I confirmed this directly and it holds throughout the file, so no live bug here — included
as a locked-in regression check rather than a fix.

I also checked every other column-alias list in the file (TAMARA, TAP, POS/D365, Bank, GL)
against the keyword sets used for header detection — TABBY's "Type"/"Order Type" was the
only mismatch; everything else lines up.

## Verification

- `py_compile` clean.
- New `REGRESSION_V67_BNPL_TAP_REVIEW_FIXES.py` (17 checks): TABBY refund detection via
  the real "Order Type" column (and the old bare "Type" name still works as a fallback),
  the parse_date/iterrows() behavior above, TAP settlement-ID grouping and
  payout_date-over-settlement_date preference, TAP status filtering, TAMARA unaffected,
  and an end-to-end POS↔TABBY reconciliation showing the refund now matches correctly.
- Reproduced the original bug directly against your uploaded file's own code (not a
  rewritten copy) before applying the fix, to confirm it was real.

## Still worth your attention (not fixed, needs your call)

- **GL tagging is text-substring matching** (`"TAP"`/`"TABBY"`/`"TAMARA"` found anywhere in
  the GL description/account name). The page's own caption already says this is
  conservative and meant to be confirmed against the GL Account Mapping table below it —
  I agree with that design, just flagging it's not a hard control on its own.
- **No persistence to the database** — unlike pages like Run History or GL Config, this
  page keeps everything in-session (upload → reconcile → download); nothing is saved
  automatically. If you want past BNPL/TAP reconciliation runs to be retrievable later the
  way other modules are, that would need a follow-up change — let me know if you want that.
- I did not have a real TABBY/TAMARA/TAP export to test against — everything above is
  verified against realistic synthetic files matching the shapes the code itself expects.
  If you can share a real (or scrubbed) export, I can re-verify against it directly.

## How to upload

Replace/add:
- `pages/37_BNPL_GL_Reconciliation_TABBY_TAMARA_TAP.py` (new page — do **not** use "21" as
  the filename prefix)

Optional but recommended:
- `REGRESSION_V67_BNPL_TAP_REVIEW_FIXES.py`

You can discard `37_BNPL_GL_Reconciliation.py1` (the TABBY/TAMARA-only draft) — the
delivered file supersedes it.

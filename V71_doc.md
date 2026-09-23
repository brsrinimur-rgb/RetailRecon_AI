# V71 — Wire the Existing AMEX Functions into Page 18 (Additive, ANB/Card Matching Untouched)

**Status: NOT frozen yet — implementation and regression are done; only the real-September-data run
is outstanding, and that's on you to run and send back.** Three rounds of review so far. Round 1
found 3 real problems in the regression test — fixed. Round 2 asked for two more real-data-shaped
cases (ambiguous AMEX wires, duplicate AMEX bank rows) — added, 45 checks passing. Round 3: one
trivial cleanup — line 201 was `_assert(True, ...)`, an assertion that can never fail and was only
ever acting as a pass-message after the real `assert_frame_equal()` above it. Replaced with a plain
`print("[PASS] ...")` so there's no lingering always-true assertion in the file. No behavior change,
still 45 real checks. Per your instruction, no new functionality and no V72 — this is the last
regression-quality pass. What's left is exactly what you said: deploy V71, run the real September
dataset, send back the Page 38 Excel so you can diff it against the V69 baseline (181 groups / 87
clean / 94 exceptions) yourself.

**Date:** 2026-09-23
**Scope:** `logic/bank_settlement_extension.py` (append-only — two new functions added,
nothing existing changed) and `pages/18_Settlement_Batch_Engine.py` (the AMEX-handling
branch added, the ANB card-matching call now runs on non-AMEX batches only).
**Not touched:** `core.py`, `pages/38_Bank_Reconciliation_Control_Tower.py`,
`logic/bank_reconciliation_report.py` (V69 stays frozen), `reconcile_card_batches_advanced()`,
`reconcile_amex_batches_via_statement()`, `reconcile_amex_wires_to_bank()`, `parse_anb_narration()`
— all four are called, never modified.

This is the AMEX fix identified as the safest, lowest-risk item in V70 (Finding 2), implemented
per your explicit instruction: *"verify exactly where those AMEX functions can be inserted
without disturbing the existing 87 clean matches... implement it as an additive change with a
before/after regression."*

## What I found before writing anything

Before touching page 18, I re-read it, `logic/bank_settlement_extension.py` in full, and every
existing regression file that exercises this area (`REGRESSION_SETTLEMENT_BATCH_ENGINE_V18.py`,
`REGRESSION_BANK_SETTLEMENT_PROPAGATION_V24.py`, `REGRESSION_V35/V41/V45`, and — a real surprise —
`REGRESSION_V37_AMEX_STATEMENT_PARSER.py` / `REGRESSION_V38_AMEX_WIRE_TO_BANK.py`, which prove
`core.is_amex_statement_file()`, `core.normalize_amex_statement()`, and `parse_anb_narration()`'s
AMEX tagging are already built and already proven against real files (your real July 2026 AMEX
statement and a real ANB bank excerpt — 11 of 13 real wires tie exactly). None of that was wired
into page 18's button flow, and — one more gap V70 didn't catch — `classify_settlement_source()`
also doesn't recognize the real AMEX statement's shape, so uploading it into page 18's existing
uploader today would have landed it in Quarantine as "Unsupported settlement/payout format."

**Exactly why AMEX batches go to BANK RECEIPT PENDING with zero evidence today:** page 18 calls
`reconcile_card_batches_advanced()` for every card provider including AMEX (line 499:
`if provider not in {"ANB POS","AMEX"}: continue`). That function requires a `Narration Terminal
ID` match — but AMEX's real wire narration (confirmed in V38) never carries a terminal ID; it's a
company-level Sarie/SIBC wire, not a per-terminal card credit. So AMEX batches always end up with
zero candidates and fall through to PENDING, with no reason text at all. This is a structural
mismatch, not a bug in that function — it's simply the wrong matcher for AMEX, exactly as V70
concluded.

## What changed

**1. `pages/18_Settlement_Batch_Engine.py`** now recognizes an uploaded AMEX Statement of Account
(via the existing `core.is_amex_statement_file()`) in the same file uploader used for
Tabby/Tamara/TAP, parses it with `core.normalize_amex_statement()`, and — this is the safety-critical
part — **splits AMEX batches out of `card_batches` before calling `reconcile_card_batches_advanced()`**,
so that function now only ever sees ANB POS (MADA/VISA/MASTERCARD) batches. AMEX batches are
resolved separately through two new, purely additive wrapper functions.

**2. `logic/bank_settlement_extension.py`** gets two new functions appended at the end of the file
(nothing above them changed by a single character — confirmed by diff, not just claimed):

- **`finalize_amex_batches(amex_batches, amex_submissions, tolerance)`** — calls the existing
  `reconcile_amex_batches_via_statement()` and maps its AMEX-only status vocabulary onto the same
  three statuses every other provider in this app already uses:
  - No statement uploaded, or no submission found for that terminal/date → **BANK RECEIPT
    PENDING**, but now with a real reason instead of a blank one.
  - Statement ties, all submissions paid → **BANK RECEIPT PENDING** (per the confirmed finance
    rule — "received" means landed in *our* bank account, never a provider's own confirmation —
    this is never promoted to BANK RECEIVED), with `Bank Match Rule` citing the Level-1 statement
    match so Finance can see it's evidence-backed, not just untouched.
  - A matched submission is `Paid=N` (AMEX itself hasn't paid it), or the statement sum doesn't
    tie within tolerance → **BANK REVIEW REQUIRED**, with the specific reason attached.
  - **Invariant enforced and tested:** this function can never output BANK RECEIVED. The finance
    rule is preserved by construction, not by convention.

- **`annotate_amex_wire_confirmations(bank_unmatched, amex_payments, bank, tolerance,
  settlement_lag_days)`** — calls the existing `reconcile_amex_wires_to_bank()` and tags AMEX-tagged
  unmatched bank credits that independently tie to one of AMEX's own declared wires. Purely
  informational: adds two new columns (`AMEX Wire Bank Status`, `AMEX Wire Bank Reason`), never
  removes a row from Unmatched Bank Credits or promotes any settlement batch — because linking a
  specific batch to the specific wire that paid it is the one piece that genuinely isn't built yet
  (documented in `reconcile_amex_batches_via_statement()`'s own docstring, and correctly left
  unbuilt rather than guessed at).

**3. Small on-page additions:** a caption under the batch table telling you how many AMEX batches
were built and that they need the AMEX statement uploaded to get Level-1 evidence; the file
uploader's label now mentions "AMEX Statement of Account" alongside Tabby/Tamara/TAP.

## What this does NOT do (by design, matching the finance rule you set)

An AMEX batch never reaches BANK RECEIVED through this path. What changes is the *quality of the
PENDING/REVIEW label* — from "no evidence, blank reason" to "proven against AMEX's own statement,
here's exactly what's outstanding" or "flagged for review, here's exactly why." The genuine
remaining gap — linking a specific batch's submission(s) to the specific wire that funded them —
stays open, stated plainly in the code's own docstring, for the same reason this project has
consistently left similar links open elsewhere (Tamara/TAP transaction-level linking): the SAR
244.59 gap between submissions-before-first-wire and the wire itself isn't explained by anything
in the statement, and guessing at a rule to close it would be exactly the kind of guess this
codebase has refused to make everywhere else.

## Round 2: two more regression cases added, per your review

You asked for two more cases, both shaped after real conditions rather than generic happy-paths:

- **Ambiguous AMEX wire.** `reconcile_amex_wires_to_bank()` already refuses to guess when two bank
  credits of the same amount both fall in the matching window for one declared wire (status "AMEX
  WIRE REVIEW REQUIRED", untouched behavior). Added a case proving `annotate_amex_wire_confirmations()`
  respects that refusal — neither of the two equally-valid candidates gets tagged
  `AMEX WIRE BANK CONFIRMED`. Two checks: one confirms the underlying (untouched) function's own
  refusal, one confirms the wrapper doesn't second-guess it.
- **Duplicate AMEX bank rows** — the exact real condition V70 flagged (two AMEX wire rows with
  identical amount/date/reference at different `Bank Source Row`s, observed in your real July
  statement). Modeled that directly: two duplicate-looking bank rows, one real declared wire.
  Mechanically this hits the same ambiguity path as above, but it's worth its own test because it's
  a real, observed data-quality pattern, not a hypothetical — proves neither duplicate is
  arbitrarily confirmed, both stay visible in Unmatched Bank Credits for a human to resolve, and
  nothing is silently dropped.

Also added a short comment at the hash-check section (section 0) making explicit what you pointed
out: the SHA256 hashes are a frozen-baseline tripwire ("did anyone touch this file"), not a
substitute for behavioral testing — a harmless docstring edit would fail them even with identical
behavior, which is intentional (forces a human look), but section 1's full-DataFrame comparison is
the actual behavioral protection. If these functions are ever legitimately modified, the doc now
says explicitly: update the hash AND rerun the behavioral sections, don't just refresh the hash.

`REGRESSION_V71_AMEX_PAGE18_WIRING.py` is now 45 checks (was 37), all passing, rerun both
standalone and inside a full copy of your repo.

## Regression fixes made in response to your first review

You caught 3 real problems in the first cut of `REGRESSION_V71_AMEX_PAGE18_WIRING.py`. All 3 are
fixed in the file delivered now:

1. **The "source unchanged" check was fake.** It ended in `or True`, which made the assertion
   always pass no matter what the source actually said — a check that can never fail isn't a
   check. Replaced with a real SHA256 hash comparison of each function's source
   (`reconcile_card_batches_advanced`, `reconcile_amex_batches_via_statement`,
   `reconcile_amex_wires_to_bank`, `parse_anb_narration`) against the hash computed from your
   actual pre-V71 file. If any of these four is edited in the future, even by one character, this
   now fails loudly instead of silently passing.
2. **Only MADA was tested, but the doc claimed MADA/VISA/MASTERCARD.** Fixed both ways: the test
   now builds one clean batch of each of the three schemes and asserts all three are actually
   present (`set(before_anb["Payment Type"]) == {"MADA","VISA","MASTERCARD"}`) before checking
   anything else, so the claim can't silently narrow again.
3. **"Byte-for-byte" was 5 hand-picked columns, not the whole result.** Replaced with
   `pd.testing.assert_frame_equal()` on the complete result DataFrame — every column
   `reconcile_card_batches_advanced()` produces, not a chosen subset. This full comparison
   actually caught something real and worth documenting rather than hiding: `Bank Source Row`
   comes back as `float64` when AMEX is still in the same call (its own unmatched row has
   `Bank Source Row=NaN`, which forces the whole column to float) and as `int64` once AMEX is
   excluded (no NaN left, so pandas infers int). The values themselves are identical (1, 2, 3
   either way) — only the storage dtype differs, as a direct side effect of removing the AMEX row
   from the input, not a change to any ANB POS row's matching outcome. The test asserts the
   dtype-normalized comparison passes AND separately asserts the raw numeric values are equal, so
   this distinction is proven, not asserted away.

## Verification — before/after regression, per your instruction

`REGRESSION_V71_AMEX_PAGE18_WIRING.py` — 45 checks, all passing (34 → 37 after round-1 fixes →
45 after round-2's ambiguous-wire and duplicate-row cases). The core proof, section 1:

- Built 3 clean settlement batches — one MADA, one VISA, one MASTERCARD, each on a different
  terminal — plus 1 AMEX batch, ran them through the **unmodified** `reconcile_card_batches_advanced()`
  two ways: once with AMEX included in the same call (today's behavior) and once with AMEX excluded
  first (page 18's new behavior). The complete result DataFrame for the 3 ANB POS rows — every
  column, via `pd.testing.assert_frame_equal()` — is proven identical in value between the two runs
  (see the dtype note above), and the leftover unmatched bank-credit count is identical too. This is
  the direct, executable proof that splitting AMEX out cannot disturb your existing clean ANB/card
  matches across all three schemes, for the structural reason stated in the code comment: AMEX
  batches never had a `Narration Terminal ID` to match against, so they never consumed a bank credit
  in the old flow either — removing them changes nothing about what the MADA/VISA/MASTERCARD
  batches see.
- 4 checks confirm `reconcile_card_batches_advanced`, `reconcile_amex_batches_via_statement`,
  `reconcile_amex_wires_to_bank`, and `parse_anb_narration` are byte-identical to their pre-V71
  source via real SHA256 hash comparison (not the placeholder from the first cut), plus 2 more
  confirming the two new wrapper functions genuinely call them.
- 5 checks cover every `finalize_amex_batches()` branch (no statement / tied+paid / Paid=N /
  amount mismatch), plus the never-BANK-RECEIVED invariant checked across all of them at once.
- 8 checks cover `annotate_amex_wire_confirmations()`: row count and existing columns unchanged,
  exactly 2 new columns added, the tying row tagged, an unrelated row left blank, safe on empty
  input.
- A full end-to-end simulation (5 clean MADA transactions + 3 distinct AMEX scenarios, run through
  the exact call sequence page 18 now makes) confirms the final per-batch Settlement Status is
  correct in every case and the on-page received/pending/review counts foot to 1/2/1.

I also reran every pre-existing regression file that touches `bank_settlement_extension.py` or
page 18 against the modified files: `REGRESSION_V35_GL_LAG_TERMINAL_FIXES`,
`REGRESSION_V41_MINOR_HARDENING`, `REGRESSION_ADVANCED_SETTLEMENT_EXCEPTION_V25`,
`REGRESSION_FINAL_COMPLETE_BUILD`, and `REGRESSION_SETTLEMENT_BATCH_ENGINE_V18` all still pass,
identically to how they behave against the untouched repo.

**One honest note, unrelated to this change:** two pre-existing regression files —
`REGRESSION_V45_MISMATCH_DIRECTION_LABELING.py` and `REGRESSION_PAGE_WIRING_FINAL.py` — already
fail against the current real repo *before* any of my changes (confirmed by running them against
your unmodified files too). They're checking for a `Mismatch Direction` column and a
`bank_settlement_extension` import on `pages/1_POS_Reconciliation.py` that aren't there anymore —
looks like page 1 was refactored at some point after those tests were written. Not something I
touched or investigated further (out of scope for this change), just flagging it since it's real,
pre-existing regression debt you'd want to know about.

## Real-data validation — still required, and I can't do it myself

You're right that this is the gate before freezing, and I want to be precise about why I can't
close it from my side: the only real artifact I've ever had for this app is the page-38 Excel
*output* (`RetailReconAI_Bank_Reconciliation_Report.xlsx`) — a downstream export, not page 18's
actual inputs. I don't have your real September `matched` transactions or your real ANB bank
statement file, so I can't run page 18 myself and produce a genuine before/after on your 87 clean
matches. Everything in this delivery is proven against synthetic data shaped exactly like the real
column contracts (same discipline as V68/V69, and the same limitation V68's own doc flagged as
still open).

**What I'd need from you to close this out**, in order of how useful it'd be:

1. **Simplest, and probably enough:** re-run page 18 on your real September data with the updated
   files, and tell me the same three numbers you'd see on the page's own metrics row — Bank
   Received / Bank Pending / Review Required — plus how many of those are AMEX and what status
   they land on. If Bank Received stays at 87 (or whatever the real current count is) and only the
   AMEX rows' reasons/statuses change, that's the confirmation.
2. **Stronger:** export `settlement_batches` (same way you got the page-38 Excel before) both
   *before* upgrading the files (today's build) and *after* (this V71 build), on the identical
   September input, and send me both. I can then diff them programmatically the same way the
   synthetic regression does, rather than relying on the on-screen counts.
3. If you'd rather I do the diffing myself, you could also just paste the "Settlement Batch
   Results" numbers from both runs into chat and I'll reconcile them by hand against what the
   regression predicts.

Until one of these comes back, my own status stands at what you said: **not frozen**. Everything
above this section is what changed in response to your regression review; this section is the one
thing that genuinely requires your real environment, not more work I can do alone.

## How to upload

Replace:
- `logic/bank_settlement_extension.py`
- `pages/18_Settlement_Batch_Engine.py`

Optional but recommended:
- `REGRESSION_V71_AMEX_PAGE18_WIRING.py`

No changes to `core.py`, page 38, or `bank_reconciliation_report.py` — V69 stays exactly as
delivered and frozen.

## Suggested next step (not done here, per your instruction)

Fix the small GCC NET narration-tag gap (V70 Finding 3 — SAR 5,354.98, 12 rows): one line in
`parse_anb_narration()`'s scheme regex to also recognize the `GC_` marker alongside `MD_`/`CC_`.
The ANB batch-granularity question (V70 Finding 1, the SAR 2.09M item) still needs
transaction-level evidence before any matching code is written — recommend pulling the real
`matched` data for terminal 55610716 (and a couple of others) next, per V70's own conclusion.

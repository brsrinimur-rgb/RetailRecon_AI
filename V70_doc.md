# V70 — Page 18 Real-Data Diagnostic: Why 94/181 Settlements Are Exceptions

**Date:** 2026-09-23
**Scope:** Read-only diagnosis of the real `RetailReconAI_Bank_Reconciliation_Report.xlsx` you ran through
page 38. **No code changed** — page 38, page 18, and `core.py` are all untouched. This is the findings
document the project's own convention calls for before touching a matching engine (same discipline as
V27/V30/V31).

## Where the SAR 3,724,441.00 "Unidentified Bank Credits" actually comes from

Broke down all 974 unmatched bank credit rows by the `Provider` tag the ANB narration parser already
assigned them:

| Bucket | Rows | SAR | Share |
|---|---:|---:|---:|
| Tagged `ANB POS` (card identity present, still unmatched) | 389 | 2,091,247.98 | 56% |
| No provider tag at all | 566 | 1,278,917.12 | 34% |
| Tagged `AMEX` | 9 | 185,428.52 | 5% |
| Tagged `TAMARA` | 2 | 109,241.44 | 3% |
| Tagged `TAP` | 8 | 59,605.94 | 2% |

Of the 566 untagged rows, most are not a bug: 66 rows (SAR 1,273,562.14) are genuine non-POS treasury
activity — outbound SWIFT wires, "NCB Local to RICHEMONT SAUDI ARABIA," "Intertransfer," cash deposits —
correctly outside this report's scope. 478 rows are the separate MADA/VISA fee and VAT debit sub-lines
(`MD_MR_FEE_...`, `MD_VAT_...`) that ANB posts alongside the main settlement credit; these all carry
`Credit = 0.00`, so they don't distort the SAR total, they're just noise rows in the sheet. The one real,
small, fixable gap in this bucket: **12 rows totaling SAR 5,354.98 are GCC NET scheme transactions**
(narration reads `POS GC_...`) that the ANB narration parser doesn't recognize as a scheme it should tag —
`core.py` already has `GCC NET` as a known payment type (see `_commission_master_maps`'s defaults), the
narration parser just doesn't look for the `GC_` marker the way it looks for `MD_`/`CC_`.

## Finding 1 — the dominant issue: 389 identity-tagged ANB credits still don't tie (SAR 2.09M)

This is the headline number, and I went further than the initial pass to pin down *why*, not just *that*.

**Ruled out:** a fee/VAT netting error. All 81 `BANK REVIEW REQUIRED` settlement batches have `Fee SAR`
and `VAT SAR` both exactly 0.00, so `Expected Bank SAR == Gross SAR` for every one of them — the mismatch
has nothing to do with commission calculation.

**Ruled out:** a clean multi-day settlement combination. My working theory after the first pass was that
ANB sometimes settles more than one calendar day together, so a terminal's several small daily batches
should sum to one larger bank credit. I tested this directly: for every review row, I summed all
same-store/terminal/scheme batches within ±3 days and compared that sum to the batch's candidate bank
credit. **Zero of 81 rows tied this way** — the window sums (e.g. SAR 13,916.54) are far larger than even
the candidate credit (SAR 3,620.98), so it isn't a simple N-consecutive-days sum either.

**What the data does show, concretely:** 71 of 81 review rows (88%) have a same-terminal sibling batch
within 3 days, and 35 of 61 distinct Store+Terminal+Scheme combinations produced settlement batches on
*more than one* of the 7 days in this file — some on as many as 7 different days. Several bank credit
amounts are independently proposed as the "nearest candidate" for two *different* settlement batches from
the same terminal on adjacent dates (14 distinct bank-credit amounts, each contested by exactly 2 batches —
confirmed by tracing one pair directly: Terminal 55610716's Sep 4 batch, SAR 2,930.98, and its Sep 5 batch,
SAR 534.49, both independently land on the same SAR 3,620.98 ANB credit as their only in-window candidate).

**Honest conclusion:** the per-terminal, per-calendar-day batch granularity `build_card_settlement_batches`
uses doesn't line up with how ANB is actually crediting these terminals in this real file, but the exact
mechanism (a settlement window that isn't a clean day-boundary sum, a real many-to-many relationship, or a
data quality issue further upstream in the transaction-level `matched` data that isn't visible in this
exported report) needs the transaction-level data this workbook doesn't contain — this exported report is
already an aggregate. **Confirming the exact mechanism needs either the live app's `st.session_state["ct_result"]["matched"]`
DataFrame, or the raw POS/D365 export + ANB bank statement side by side.**

## Finding 2 — AMEX settlements structurally cannot match today (SAR 185,428.52 on the bank side; SAR 116,100 expected)

All 3 AMEX settlement batches sit at `BANK RECEIPT PENDING` with zero bank candidates found. I checked
the 9 AMEX-tagged unmatched bank credits directly — they're genuine AMEX wire transfers (narration:
"Amex (Saudi Arabia) Ltd.", SIBC wire references, one exactly matching the shape `reconcile_amex_wires_to_bank()`
is built to parse). The reason they never match: **page 18 only calls `reconcile_card_batches_advanced()`
for every card provider including AMEX**, which looks for a same-store/terminal/day bank credit — but AMEX
doesn't settle that way; it arrives as a wire to the company's account, not tied to a specific terminal or
day. Your codebase already has the two functions built for exactly this
(`reconcile_amex_batches_via_statement()` and `reconcile_amex_wires_to_bank()`, in
`logic/bank_settlement_extension.py`) — they're just not wired into page 18's button flow. This is the
most clearly scoped, lowest-risk fix of everything in this document: wiring an existing, already-tested
function into the page 18 flow, not writing new matching logic.

(Note two of the AMEX wire rows appear twice, at different `Bank Source Row`s with identical amounts,
dates and references — worth a quick look at whether the bank file has genuine duplicate rows or the file
was uploaded/processed twice; low priority next to the above.)

## Finding 3 — GCC NET narration tag gap (SAR 5,354.98, 12 rows)

Small in dollar terms but a real, precisely-located parsing gap: the ANB narration parser recognizes
`MD_` (MADA) and `CC_` (Visa/Mastercard) markers but not `GC_` (GCC NET), so these settlement credits
never get a `Provider` tag and can never be considered for matching at all.

## What I'd recommend, in order

1. **AMEX wiring (Finding 2)** — smallest, safest change: call the existing AMEX-specific matchers from
   page 18 instead of (or in addition to) the generic ANB card matcher for AMEX batches. Existing, tested
   code; no new matching logic.
2. **GCC NET tag (Finding 3)** — a one-line addition to the narration parser's scheme detection.
3. **The ANB POS batch-granularity question (Finding 1)** — the big one, and the one that needs more
   evidence before writing any matching code. My recommendation is to pull the transaction-level `matched`
   data for a couple of the traced terminals (e.g. 55610716, 55610695) and manually reconstruct what ANB
   actually paid, rather than guessing at a new grouping rule from the aggregated batch data alone.

Nothing above has been implemented. Page 38 remains exactly as delivered in V69; this document is the
input for deciding what to build next, and in what order.

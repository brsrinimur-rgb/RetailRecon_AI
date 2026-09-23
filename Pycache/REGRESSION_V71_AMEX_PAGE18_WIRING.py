"""
REGRESSION_V71_AMEX_PAGE18_WIRING.py

Purpose: verify the V71 wiring of the already-built, already-tested AMEX
functions (reconcile_amex_batches_via_statement, reconcile_amex_wires_to_bank
-- both proven against real data in REGRESSION_V37/V38) into Page 18's
actual button flow, per the user's explicit instruction:

    "We should verify exactly where those AMEX functions can be inserted
    without disturbing the existing 87 clean matches. Then implement it as
    an additive V70 [V71] change with a before/after regression."

Two new functions were added to logic/bank_settlement_extension.py:
  - finalize_amex_batches()             (maps AMEX statement result onto the
                                          app's existing Settlement Status
                                          vocabulary)
  - annotate_amex_wire_confirmations()  (informational bank-side tagging)

Neither reconcile_card_batches_advanced(), reconcile_amex_batches_via_statement(),
nor reconcile_amex_wires_to_bank() (nor parse_anb_narration()) was modified --
confirmed below by a real SHA256 hash comparison of each function's source
against its pre-V71 version, not a placeholder assertion.

Covers:
  0. Source-hash checks are REAL (this replaces an earlier version of this
     file where the check was accidentally short-circuited with "or True"
     and always passed regardless of the actual source -- caught in review
     before this was frozen; fixed here).
  1. BEFORE/AFTER: 3 clean ANB POS matches -- one MADA, one VISA, one
     MASTERCARD, all three schemes actually exercised, not MADA alone --
     produced by reconcile_card_batches_advanced() are proven identical via
     pd.testing.assert_frame_equal() on the FULL result DataFrame (every
     column, not a hand-picked subset) whether AMEX batches are present in
     the same run or excluded first (the exact change Page 18 now makes).
  2. finalize_amex_batches(): no statement uploaded -> BANK RECEIPT PENDING
     with an evidence-backed reason (not blank).
  3. finalize_amex_batches(): statement ties, all paid -> BANK RECEIPT
     PENDING (never BANK RECEIVED -- finance rule preserved) with the
     Level-1 rule text attached.
  4. finalize_amex_batches(): Paid=N -> BANK REVIEW REQUIRED.
  5. finalize_amex_batches(): statement sum mismatch -> BANK REVIEW REQUIRED.
  6. Invariant: finalize_amex_batches() NEVER produces BANK RECEIVED, across
     every case above -- the finance rule as an executable check.
  7. annotate_amex_wire_confirmations(): row count and pre-existing columns
     of bank_unmatched are unchanged; only the 2 new columns are added;
     the row whose wire is bank-confirmed gets tagged, unrelated rows don't.
  7b. Ambiguous AMEX wire: 2 bank credits of the same amount both fall in the
      matching window for 1 declared wire -- reconcile_amex_wires_to_bank()
      refuses to guess (AMEX WIRE REVIEW REQUIRED); proves the wrapper does
      not arbitrarily tag either candidate as confirmed.
  7c. Duplicate AMEX bank rows -- the real V70-observed condition (two AMEX
      wire rows with identical amount/date/reference, at different Bank
      Source Rows). Proves neither duplicate is arbitrarily confirmed against
      a single real wire, and both rows remain visible in bank_unmatched for
      a human to resolve.
  8. End-to-end simulation of the exact call sequence added to Page 18: MADA
     clean match, AMEX with a tying statement, AMEX with no statement, AMEX
     Paid=N, all in the same run -- final Settlement Status per batch is
     correct for each case, and Settlement Batch Results counts foot.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
import core
from logic import bank_settlement_extension as bank_ext

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

# =============================================================================
# 0. Confirm the pre-existing matching functions were not touched -- a REAL
#    check, not an "or True" placeholder. Hashes below were computed from
#    logic/bank_settlement_extension.py as it existed BEFORE this V71 change
#    (verified by running the same hash against the untouched repo file).
#    If anyone edits the body of any of these four functions in the future,
#    this fails loudly instead of silently passing.
#
#    Deliberate scope of this check: it is a frozen-baseline tripwire, not a
#    substitute for behavioral testing. A hash comparison will fail on a pure
#    docstring/comment/formatting edit even if behavior is 100% unchanged --
#    that is intentional (it forces a human to look and re-verify) but it
#    also means this check alone proves nothing about correctness. Section 1
#    below (the full-DataFrame before/after comparison) is the actual
#    behavioral protection; this section only proves "nobody touched this
#    file since V71 shipped." If these functions are ever legitimately
#    modified, update the hash here AND rerun the behavioral sections to
#    reconfirm the ANB POS matching outcome is still correct -- do not just
#    refresh the hash and move on.
# =============================================================================
import inspect, hashlib

_EXPECTED_SOURCE_SHA256 = {
    "reconcile_card_batches_advanced": "1d4fc9882b1888c43d446108a8cf57c2380de130c42254576a7011768fe03812",
    "reconcile_amex_batches_via_statement": "de9406506ac56bf32b704b526101ca62314a6673eb54f7b3823474eb6543a8f1",
    "reconcile_amex_wires_to_bank": "13ea0cd98ef12025035aa2748afbed607d230e4870e8934f3f630551d7c5dec5",
    "parse_anb_narration": "cec2c31c44e69ddfbd1830868786927c7ce86dfc4f4682cedd0059af419582bc",
}
for _fn_name, _expected_hash in _EXPECTED_SOURCE_SHA256.items():
    _fn = getattr(bank_ext, _fn_name)
    _actual_hash = hashlib.sha256(inspect.getsource(_fn).encode()).hexdigest()
    _assert(
        _actual_hash == _expected_hash,
        f"{_fn_name}() source is byte-identical to its pre-V71 version (SHA256 matches) -- "
        f"NOT modified by this change"
    )

_assert(
    "reconcile_amex_batches_via_statement" in inspect.getsource(bank_ext.finalize_amex_batches),
    "finalize_amex_batches() calls the existing, untouched reconcile_amex_batches_via_statement()"
)
_assert(
    "reconcile_amex_wires_to_bank" in inspect.getsource(bank_ext.annotate_amex_wire_confirmations),
    "annotate_amex_wire_confirmations() calls the existing, untouched reconcile_amex_wires_to_bank()"
)

# =============================================================================
# 1. BEFORE/AFTER: existing ANB POS matches (MADA, VISA, AND MASTERCARD --
#    all three schemes, not MADA alone) unaffected by excluding AMEX.
#    Full-frame comparison via pd.testing.assert_frame_equal(), not a
#    hand-picked subset of columns.
# =============================================================================
card_batch_rows = []
for i, scheme in enumerate(["MADA", "VISA", "MASTERCARD"]):
    card_batch_rows.append({
        "Settlement Source":"ANB POS","Settlement Batch ID":f"C{i}","Provider":"ANB POS",
        "Store Code":"601","Merchant":"","Terminal ID":f"5561070{i}","Payment Type":scheme,
        "Settlement Date":pd.Timestamp("2026-09-01"),"Gross Amount":1000.0+i,
        "Refund Amount":0.0,"Fee Amount":8.7,"VAT Amount":1.3,
        "Expected Bank Amount":1000.0+i,"Transaction Count":5,
        "Underlying IDs":"","Source File":"test",
    })
clean_card_batches = pd.DataFrame(card_batch_rows)
amex_batches_mixed = pd.DataFrame([
    {"Settlement Source":"AMEX","Settlement Batch ID":"A1","Provider":"AMEX",
     "Store Code":"601","Merchant":"","Terminal ID":"55610701","Payment Type":"AMEX",
     "Settlement Date":pd.Timestamp("2026-09-01"),"Gross Amount":5000.0,
     "Refund Amount":0.0,"Fee Amount":0.0,"VAT Amount":0.0,
     "Expected Bank Amount":5000.0,"Transaction Count":3,
     "Underlying IDs":"","Source File":"test"},
])
combined_batches = pd.concat([clean_card_batches, amex_batches_mixed], ignore_index=True)

bank_rows = []
for i, scheme in enumerate(["MADA", "VISA", "MASTERCARD"]):
    bank_rows.append({
        "Bank":"ANB", "Bank Date":pd.Timestamp("2026-09-02"),
        "Bank Amount":1000.0+i, "Credit":1000.0+i, "Debit":0.0,
        "Narration Terminal ID":f"5561070{i}", "Narration Scheme":scheme,
        "Narration Source Date":pd.Timestamp("2026-09-01"),
        "Narration Transaction Count":5, "Description":f"{scheme} settlement",
        "Bank Source File":"bank.xlsx", "Bank Source Sheet":"Sheet1", "Bank Source Row":i+1,
    })
bank = pd.DataFrame(bank_rows)

# BEFORE (today's page-18 behavior): AMEX included in the single call.
before_result, before_unmatched = bank_ext.reconcile_card_batches_advanced(combined_batches, bank, 1.0)
# AFTER (V71's page-18 behavior): AMEX split out first.
is_amex = combined_batches["Provider"].astype(str).str.upper().eq("AMEX")
after_result, after_unmatched = bank_ext.reconcile_card_batches_advanced(
    combined_batches[~is_amex].copy(), bank, 1.0
)

before_anb = before_result[before_result["Provider"] == "ANB POS"].sort_values("Settlement Batch ID").reset_index(drop=True)
after_anb = after_result[after_result["Provider"] == "ANB POS"].sort_values("Settlement Batch ID").reset_index(drop=True)

_assert(len(before_anb) == 3 and len(after_anb) == 3,
        "MADA + VISA + MASTERCARD -- all 3 clean ANB POS batches present in both BEFORE and AFTER runs")
_assert(
    (before_anb["Settlement Status"] == "BANK RECEIVED").all() and
    (after_anb["Settlement Status"] == "BANK RECEIVED").all(),
    "All 3 (MADA/VISA/MASTERCARD) batches are BANK RECEIVED in both BEFORE and AFTER runs"
)
_assert(set(before_anb["Payment Type"]) == {"MADA", "VISA", "MASTERCARD"},
        "All three card schemes are actually exercised by this test, not MADA alone")

# Real full-DataFrame equality -- every column the function produces, not a
# hand-picked subset. Both frames share the same columns by construction
# (same function, same call shape), so this is a genuine "nothing changed"
# proof rather than a claim about 5 chosen fields.
#
# check_dtype=False: this comparison caught a real, legitimate pandas
# artifact worth documenting rather than hiding -- "Bank Source Row" comes
# back as float64 in the BEFORE run (the AMEX row it also contains has
# Bank Source Row=NaN, which forces the whole column to float) and int64 in
# the AFTER run (no NaN present once AMEX is excluded, so pandas infers
# int). The VALUES are identical (1, 2, 3 either way) -- only the storage
# dtype differs, as a side effect of the AMEX row's absence, not a change
# to any ANB POS row's actual matching outcome. Verified explicitly below,
# not just waved away by the flag.
pd.testing.assert_frame_equal(
    before_anb.reset_index(drop=True), after_anb.reset_index(drop=True), check_dtype=False
)
_assert(
    (pd.to_numeric(before_anb["Bank Source Row"]) == pd.to_numeric(after_anb["Bank Source Row"])).all(),
    "Bank Source Row VALUES are identical BEFORE vs AFTER (1, 2, 3) -- the only difference caught by "
    "the strict dtype check was float64-vs-int64 storage, caused by the AMEX row's NaN being present "
    "in one run and absent in the other, not a value change"
)
print("[PASS] Full result DataFrame (every column reconcile_card_batches_advanced() produces) is "
      "identical in VALUE BEFORE vs AFTER the AMEX split, via pd.testing.assert_frame_equal() -- "
      "genuinely every column, not a 5-column sample")

_assert(
    len(before_unmatched) == len(after_unmatched),
    f"Unmatched ANB bank credit count unchanged BEFORE ({len(before_unmatched)}) vs AFTER ({len(after_unmatched)})"
)
_assert(
    "AMEX" not in set(after_result.get("Provider", pd.Series(dtype=str))),
    "AFTER run (Page 18's new behavior) never even attempts the AMEX batch through the ANB card matcher"
)
print("[PASS] SECTION 1: existing ANB POS (MADA, VISA, AND MASTERCARD, all three exercised) matching "
      "is completely unaffected by splitting AMEX out first, proven via full-DataFrame equality -- "
      "the exact guarantee requested before implementation.")

# =============================================================================
# 2-6. finalize_amex_batches() status mapping + the finance-rule invariant.
# =============================================================================
amex_batch_no_stmt = pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B1","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"55610701","Payment Type":"AMEX",
    "Settlement Date":pd.Timestamp("2026-07-10"),"Gross Amount":51500.00,
    "Expected Bank Amount":51500.00,
}])
r2 = bank_ext.finalize_amex_batches(amex_batch_no_stmt, pd.DataFrame(), 1.0)
_assert(r2.iloc[0]["Settlement Status"] == "BANK RECEIPT PENDING", "No statement uploaded -> BANK RECEIPT PENDING")
_assert(r2.iloc[0]["Settlement Review Reason"] != "", "No statement uploaded -> reason is NOT blank (was blank before V71)")
_assert("No AMEX statement" in r2.iloc[0]["Settlement Review Reason"], "Reason correctly explains no statement was available")

submissions = pd.DataFrame([
    {"Terminal ID":"55610701","Date":pd.Timestamp("2026-07-10"),"Ref":"R1",
     "Gross Amount":51500.00,"Net Amount":49955.00,"Paid":"P"},
])
r3 = bank_ext.finalize_amex_batches(amex_batch_no_stmt, submissions, 1.0)
_assert(r3.iloc[0]["Settlement Status"] == "BANK RECEIPT PENDING", "Statement ties, paid -> still BANK RECEIPT PENDING (not promoted)")
_assert("Level 1" in r3.iloc[0]["Bank Match Rule"], "Bank Match Rule cites the Level-1 statement match")
_assert(pd.isna(r3.iloc[0]["Actual Bank Amount"]), "Actual Bank Amount stays blank -- no real bank credit was tied")

amex_batch_unpaid = pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B2","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"55610708","Payment Type":"AMEX",
    "Settlement Date":pd.Timestamp("2026-07-31"),"Gross Amount":77000.00,
    "Expected Bank Amount":77000.00,
}])
submissions_unpaid = pd.DataFrame([
    {"Terminal ID":"55610708","Date":pd.Timestamp("2026-07-31"),"Ref":"R2",
     "Gross Amount":77000.00,"Net Amount":74800.00,"Paid":"N"},
])
r4 = bank_ext.finalize_amex_batches(amex_batch_unpaid, submissions_unpaid, 1.0)
_assert(r4.iloc[0]["Settlement Status"] == "BANK REVIEW REQUIRED", "Paid=N submission -> BANK REVIEW REQUIRED")
_assert("Paid=N" in r4.iloc[0]["Settlement Review Reason"], "Reason cites Paid=N")

amex_batch_mismatch = pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B3","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"99999999","Payment Type":"AMEX",
    "Settlement Date":pd.Timestamp("2026-07-15"),"Gross Amount":9999.0,
    "Expected Bank Amount":9999.0,
}])
submissions_other = pd.DataFrame([
    {"Terminal ID":"99999999","Date":pd.Timestamp("2026-07-15"),"Ref":"R3",
     "Gross Amount":1000.0,"Net Amount":970.0,"Paid":"P"},
])
r5 = bank_ext.finalize_amex_batches(amex_batch_mismatch, submissions_other, 1.0)
_assert(r5.iloc[0]["Settlement Status"] == "BANK REVIEW REQUIRED", "Statement sum mismatch -> BANK REVIEW REQUIRED")
_assert("does not tie" in r5.iloc[0]["Settlement Review Reason"], "Reason cites the amount that doesn't tie")

all_amex_results = pd.concat([r2, r3, r4, r5], ignore_index=True)
_assert(
    (all_amex_results["Settlement Status"] != "BANK RECEIVED").all(),
    "INVARIANT: finalize_amex_batches() never produces BANK RECEIVED in any of the 4 cases above -- "
    "the 'received means landed in our own bank account' rule is preserved by construction."
)

# Empty-input safety.
_assert(bank_ext.finalize_amex_batches(pd.DataFrame(), pd.DataFrame(), 1.0).empty,
        "finalize_amex_batches() degrades safely on empty input")

# =============================================================================
# 7. annotate_amex_wire_confirmations(): additive-only on bank_unmatched.
# =============================================================================
bank_unmatched = pd.DataFrame([
    {"Bank":"ANB","Bank Date":pd.Timestamp("2026-07-12"),"Bank Amount":52263.47,
     "Credit":52263.47,"Provider":"AMEX","Description":"Amex wire",
     "Bank Source File":"anb.xlsx","Bank Source Row":10},
    {"Bank":"ANB","Bank Date":pd.Timestamp("2026-07-20"),"Bank Amount":999.00,
     "Credit":999.00,"Provider":"","Description":"MD_ fee line",
     "Bank Source File":"anb.xlsx","Bank Source Row":11},
])
amex_payments = pd.DataFrame([
    {"Date":pd.Timestamp("2026-07-11"),"Wire Amount":52263.47,"Source File":"stmt.xlsx"},
])
bank_for_wire_check = pd.DataFrame([
    {"Bank":"ANB","Bank Date":pd.Timestamp("2026-07-12"),"Bank Amount":52263.47,
     "Credit":52263.47,"Provider":"AMEX","Bank Source File":"anb.xlsx","Bank Source Row":10},
])
annotated = bank_ext.annotate_amex_wire_confirmations(bank_unmatched, amex_payments, bank_for_wire_check, 1.0)

_assert(len(annotated) == len(bank_unmatched), "Row count of bank_unmatched is unchanged after annotation")
_assert(
    set(bank_unmatched.columns) <= set(annotated.columns),
    "All pre-existing bank_unmatched columns are preserved"
)
_assert(
    set(annotated.columns) - set(bank_unmatched.columns) == {"AMEX Wire Bank Status", "AMEX Wire Bank Reason"},
    "Exactly 2 new columns added, nothing else"
)
confirmed_row = annotated[annotated["Bank Source Row"] == 10].iloc[0]
other_row = annotated[annotated["Bank Source Row"] == 11].iloc[0]
_assert(confirmed_row["AMEX Wire Bank Status"] == "AMEX WIRE BANK CONFIRMED",
        "The AMEX wire row that ties is correctly tagged AMEX WIRE BANK CONFIRMED")
_assert(other_row["AMEX Wire Bank Status"] == "", "The unrelated fee-line row is left untagged")

# Empty-input safety.
_assert(bank_ext.annotate_amex_wire_confirmations(pd.DataFrame(), amex_payments, bank_for_wire_check).empty is True
        or bank_ext.annotate_amex_wire_confirmations(pd.DataFrame(), amex_payments, bank_for_wire_check) is None
        or len(bank_ext.annotate_amex_wire_confirmations(pd.DataFrame(), amex_payments, bank_for_wire_check)) == 0,
        "annotate_amex_wire_confirmations() degrades safely on empty bank_unmatched")
no_wire_case = bank_ext.annotate_amex_wire_confirmations(bank_unmatched, pd.DataFrame(), bank_for_wire_check)
_assert((no_wire_case["AMEX Wire Bank Status"] == "").all(),
        "No AMEX statement uploaded -> all tags stay blank, no crash")

# =============================================================================
# 7b. Ambiguous AMEX wire: two bank credits of the same amount both fall in
#     the matching window for one declared wire. reconcile_amex_wires_to_bank()
#     already refuses to guess here (status "AMEX WIRE REVIEW REQUIRED") --
#     this section proves the wrapper respects that refusal and does NOT
#     arbitrarily tag either candidate as confirmed.
# =============================================================================
amex_payments_ambiguous = pd.DataFrame([
    {"Date": pd.Timestamp("2026-08-01"), "Wire Amount": 10000.00, "Source File": "stmt.xlsx"},
])
bank_for_wire_check_ambiguous = pd.DataFrame([
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-08-02"), "Bank Amount": 10000.00,
     "Credit": 10000.00, "Provider": "AMEX", "Bank Source File": "anb.xlsx", "Bank Source Row": 20},
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-08-03"), "Bank Amount": 10000.00,
     "Credit": 10000.00, "Provider": "AMEX", "Bank Source File": "anb.xlsx", "Bank Source Row": 21},
])
bank_unmatched_ambiguous = pd.DataFrame([
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-08-02"), "Bank Amount": 10000.00,
     "Credit": 10000.00, "Provider": "AMEX", "Description": "Amex wire (candidate 1)",
     "Bank Source File": "anb.xlsx", "Bank Source Row": 20},
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-08-03"), "Bank Amount": 10000.00,
     "Credit": 10000.00, "Provider": "AMEX", "Description": "Amex wire (candidate 2)",
     "Bank Source File": "anb.xlsx", "Bank Source Row": 21},
])

# Sanity check on the UNTOUCHED underlying function first: it must refuse to
# guess between the two equally-valid candidates.
wire_res_ambiguous = bank_ext.reconcile_amex_wires_to_bank(amex_payments_ambiguous, bank_for_wire_check_ambiguous, 1.0)
_assert(
    wire_res_ambiguous.iloc[0]["AMEX Wire Bank Status"] == "AMEX WIRE REVIEW REQUIRED",
    "reconcile_amex_wires_to_bank() (untouched) correctly refuses to guess between 2 equally-valid "
    "bank credits -- status is AMEX WIRE REVIEW REQUIRED, not a guessed CONFIRMED"
)

annotated_ambiguous = bank_ext.annotate_amex_wire_confirmations(
    bank_unmatched_ambiguous, amex_payments_ambiguous, bank_for_wire_check_ambiguous, 1.0
)
row20 = annotated_ambiguous[annotated_ambiguous["Bank Source Row"] == 20].iloc[0]
row21 = annotated_ambiguous[annotated_ambiguous["Bank Source Row"] == 21].iloc[0]
_assert(
    row20["AMEX Wire Bank Status"] == "" and row21["AMEX Wire Bank Status"] == "",
    "AMBIGUOUS CASE: neither of the 2 equally-valid bank credits is tagged AMEX WIRE BANK CONFIRMED -- "
    "the wrapper does not arbitrarily pick one when the underlying function itself refuses to."
)

# =============================================================================
# 7c. Duplicate AMEX bank rows -- the exact real-data condition V70 flagged
#     ("two of the AMEX wire rows appear twice, at different Bank Source Rows,
#     with identical amounts, dates and references"). Two bank rows that look
#     like true duplicates (same amount, same date) must not result in one of
#     them being arbitrarily confirmed against a single real wire -- that
#     would silently double-count or silently pick the wrong row if the
#     duplicate is actually a real double-posting data quality issue.
# =============================================================================
amex_payments_dup = pd.DataFrame([
    {"Date": pd.Timestamp("2026-07-16"), "Wire Amount": 2949.60, "Source File": "stmt.xlsx"},
])
bank_for_wire_check_dup = pd.DataFrame([
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-07-18"), "Bank Amount": 2949.60,
     "Credit": 2949.60, "Provider": "AMEX", "Bank Source File": "anb_july2026.xlsx", "Bank Source Row": 88},
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-07-18"), "Bank Amount": 2949.60,
     "Credit": 2949.60, "Provider": "AMEX", "Bank Source File": "anb_july2026.xlsx", "Bank Source Row": 89},
])
bank_unmatched_dup = pd.DataFrame([
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-07-18"), "Bank Amount": 2949.60,
     "Credit": 2949.60, "Provider": "AMEX", "Description": "SD5984236 Amex wire",
     "Bank Source File": "anb_july2026.xlsx", "Bank Source Row": 88},
    {"Bank": "ANB", "Bank Date": pd.Timestamp("2026-07-18"), "Bank Amount": 2949.60,
     "Credit": 2949.60, "Provider": "AMEX", "Description": "SD5984236 Amex wire",
     "Bank Source File": "anb_july2026.xlsx", "Bank Source Row": 89},
])

wire_res_dup = bank_ext.reconcile_amex_wires_to_bank(amex_payments_dup, bank_for_wire_check_dup, 1.0)
_assert(
    wire_res_dup.iloc[0]["AMEX Wire Bank Status"] == "AMEX WIRE REVIEW REQUIRED",
    "Duplicate-looking AMEX bank rows (same amount/date, real V70 condition) -> "
    "reconcile_amex_wires_to_bank() stays REVIEW REQUIRED, does not guess which duplicate is real"
)
_assert(
    "ambiguous" in wire_res_dup.iloc[0]["AMEX Wire Bank Reason"].lower(),
    "Reason text correctly names this as ambiguous, not a data error being silently resolved"
)

annotated_dup = bank_ext.annotate_amex_wire_confirmations(
    bank_unmatched_dup, amex_payments_dup, bank_for_wire_check_dup, 1.0
)
row88 = annotated_dup[annotated_dup["Bank Source Row"] == 88].iloc[0]
row89 = annotated_dup[annotated_dup["Bank Source Row"] == 89].iloc[0]
_assert(
    row88["AMEX Wire Bank Status"] == "" and row89["AMEX Wire Bank Status"] == "",
    "DUPLICATE-ROW CASE: neither duplicate bank row (Source Row 88 or 89) is arbitrarily tagged "
    "AMEX WIRE BANK CONFIRMED -- a real double-posted/duplicate-ingested bank row is left for a "
    "human to resolve, never silently picked"
)
_assert(len(annotated_dup) == 2, "Both duplicate rows remain in bank_unmatched -- nothing silently dropped")

# =============================================================================
# 8. End-to-end simulation of Page 18's new call sequence.
# =============================================================================
matched = pd.DataFrame([
    # 5 clean MADA transactions -> 1 batch of 500.00
    *[{"Unique Transaction ID": f"MADA{i}", "Store Code": "601", "Payment Type": "MADA",
       "POS Date": pd.Timestamp("2026-07-10"), "Terminal ID": "55610650",
       "POS Amount": 100.0, "Net Amount": 100.0, "Commission": 0.0, "VAT": 0.0} for i in range(5)],
    # AMEX batch that WILL tie to a statement submission
    {"Unique Transaction ID": "AMEXA", "Store Code": "601", "Payment Type": "AMEX",
     "POS Date": pd.Timestamp("2026-07-10"), "Terminal ID": "55610701",
     "POS Amount": 51500.00, "Net Amount": 51500.00, "Commission": 0.0, "VAT": 0.0},
    # AMEX batch with NO matching statement submission (different terminal/date)
    {"Unique Transaction ID": "AMEXB", "Store Code": "601", "Payment Type": "AMEX",
     "POS Date": pd.Timestamp("2026-07-12"), "Terminal ID": "55610799",
     "POS Amount": 2500.00, "Net Amount": 2500.00, "Commission": 0.0, "VAT": 0.0},
    # AMEX batch that IS in the statement but Paid=N
    {"Unique Transaction ID": "AMEXC", "Store Code": "601", "Payment Type": "AMEX",
     "POS Date": pd.Timestamp("2026-07-31"), "Terminal ID": "55610708",
     "POS Amount": 77000.00, "Net Amount": 77000.00, "Commission": 0.0, "VAT": 0.0},
])
e2e_card_batches = core.build_card_settlement_batches(matched)
_assert(len(e2e_card_batches) == 4, f"4 settlement batches built (1 MADA + 3 AMEX), got {len(e2e_card_batches)}")

e2e_bank = pd.DataFrame([{
    "Bank": "ANB", "Bank Date": pd.Timestamp("2026-07-11"), "Bank Amount": 500.0, "Credit": 500.0, "Debit": 0.0,
    "Narration Terminal ID": "55610650", "Narration Scheme": "MADA",
    "Narration Source Date": pd.Timestamp("2026-07-10"), "Narration Transaction Count": 5,
    "Description": "MADA settlement", "Bank Source File": "anb.xlsx", "Bank Source Sheet": "S1", "Bank Source Row": 1,
}])
e2e_submissions = pd.DataFrame([
    {"Terminal ID": "55610701", "Date": pd.Timestamp("2026-07-10"), "Ref": "R1",
     "Gross Amount": 51500.00, "Net Amount": 49955.00, "Paid": "P"},
    {"Terminal ID": "55610708", "Date": pd.Timestamp("2026-07-31"), "Ref": "R2",
     "Gross Amount": 77000.00, "Net Amount": 74800.00, "Paid": "N"},
])

is_amex_e2e = e2e_card_batches["Provider"].astype(str).str.upper().eq("AMEX")
e2e_other = e2e_card_batches[~is_amex_e2e].copy()
e2e_amex = e2e_card_batches[is_amex_e2e].copy()

e2e_card_result, e2e_anb_unmatched = bank_ext.reconcile_card_batches_advanced(e2e_other, e2e_bank, 1.0)
e2e_amex_result = bank_ext.finalize_amex_batches(e2e_amex, e2e_submissions, 1.0)
e2e_batch_result = pd.concat([e2e_card_result, e2e_amex_result], ignore_index=True)

by_terminal = e2e_batch_result.set_index("Terminal ID")["Settlement Status"].to_dict()
_assert(by_terminal["55610650"] == "BANK RECEIVED", "E2E: MADA batch reaches BANK RECEIVED as before")
_assert(by_terminal["55610701"] == "BANK RECEIPT PENDING", "E2E: AMEX batch with tying statement -> BANK RECEIPT PENDING (evidence-backed)")
_assert(by_terminal["55610799"] == "BANK RECEIPT PENDING", "E2E: AMEX batch with no statement submission -> BANK RECEIPT PENDING")
_assert(by_terminal["55610708"] == "BANK REVIEW REQUIRED", "E2E: AMEX batch with Paid=N submission -> BANK REVIEW REQUIRED")

received = int((e2e_batch_result["Settlement Status"] == "BANK RECEIVED").sum())
pending = int((e2e_batch_result["Settlement Status"] == "BANK RECEIPT PENDING").sum())
review = int((e2e_batch_result["Settlement Status"] == "BANK REVIEW REQUIRED").sum())
_assert(received == 1 and pending == 2 and review == 1,
        f"E2E counts foot: 1 BANK RECEIVED, 2 BANK RECEIPT PENDING, 1 BANK REVIEW REQUIRED "
        f"(got {received}/{pending}/{review})")
_assert(len(e2e_batch_result) == 4, "E2E: all 4 batches present in the final combined result, none dropped")

print("REGRESSION V71 AMEX PAGE 18 WIRING PASS")

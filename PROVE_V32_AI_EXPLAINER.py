"""
PROVE_V32_AI_EXPLAINER.py

Runs the verification steps from the V32 spec that are actually possible
WITHOUT real core.py / bank_settlement_extension.py / a live model
endpoint:

  - Step 4 (structural no-write check) — fully runnable now.
  - Steps 1-2 (known-good / known-ambiguous replay) — runnable against
    build_candidates()/parse_and_validate() using synthetic fixtures
    modeled on the real ANB example worked through by hand in this
    conversation (terminal 55610694, 2026-07-07/08, SAR 13,052.02, fee
    -71.80, VAT -10.76), and a synthetic ambiguous two-candidate case.
    The MODEL CALL ITSELF is stubbed (see logic/ai_settlement_explainer's
    call_model_stub in the page) — this script tests the parsing/guardrail
    layer by feeding it hand-written JSON that a model *would* plausibly
    return, not a real model response.
  - Step 3 (real Review Required queue) and Step 5 (cost/latency) —
    CANNOT run here; need a live st.session_state.ct_result and a wired
    model endpoint. Left as explicit TODOs, not silently skipped.

Run: python3 PROVE_V32_AI_EXPLAINER.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from logic import ai_settlement_explainer as explainer


def test_structural_no_write():
    ok = explainer.assert_no_write_paths()
    assert ok is True
    print("[PASS] Structural no-write check: module contains no Settlement "
          "Status / Bank Settled / Underlying IDs / JV mutation patterns.")


def test_known_good_replay():
    """Modeled on the SD1173489 / terminal 55610694 example worked through
    by hand earlier in this conversation. Field names below are the
    CONFIRMED real schema from core.py/bank_settlement_extension.py (Payment
    Type, not Scheme; Narration Terminal ID on bank rows, not Terminal ID;
    Description as the primary narration text) -- deliberately NOT the
    earlier guessed names, so this test actually exercises the real alias
    fix rather than just re-confirming its own prior wrong assumption."""
    batch_row = {
        "Settlement Status": "BANK REVIEW REQUIRED",
        "Settlement Batch ID": "BATCH-55610694-20260707",
        "Terminal ID": "55610694",
        "Settlement Date": "2026-07-07",
        "Payment Type": "MADA",
        "Provider": "ANB POS",
        "Gross Amount": 13052.02,
    }
    bank_row = {
        "Narration Terminal ID": "55610694",
        "Bank Source File": "anb_statement_jul2026.xlsx",
        "Bank Source Sheet": "Sheet1",
        "Bank Source Row": 42,
        "Bank Date": "2026-07-08",
        "Bank Amount": 13052.02,
        "Description": "POS MD_88077230_UNITED LUXURY | 301128607314_55610694_080726 | Mada_10.76_71.80_TX_17",
    }

    requests = explainer.build_candidates(
        settlement_batches_rows=[batch_row],
        settlement_bank_unmatched_rows=[bank_row],
        settlement_lag_days=1,
    )
    assert len(requests) == 1
    req = requests[0]
    assert len(req.candidates) == 1, "known-good case should shortlist exactly one candidate"

    prompt = explainer.build_prompt(req)
    assert "55610694" in prompt
    assert "13052.02" in prompt

    # Simulate a plausible model response (hand-written, not from a live call)
    model_response = """{
        "verdict": "Ties",
        "confidence": "High",
        "candidate_bank_amount": 13052.02,
        "computed_net": 12969.46,
        "narration_decode": "Retailer 301128607314, Terminal 55610694, date 08/07/26, Mada scheme, gross 13052.02, 17 transactions",
        "explanation": "Batch gross ties exactly to the bank credit; fee -71.80 and VAT -10.76 explain the net.",
        "cited_rows": ["anb_statement_jul2026.xlsx::Sheet1::42"]
    }"""

    result = explainer.parse_and_validate(req.batch_id, req.gross_pos_amount, model_response)
    assert result.verdict == "Ties"
    assert result.confidence == "High"
    assert result.cited_rows == ["anb_statement_jul2026.xlsx::Sheet1::42"]
    print("[PASS] Known-good replay: single candidate, Ties/High, cited_rows populated.")


def test_known_ambiguous_replay():
    """Two same-day, same-narration bank credits — the V26 §3(a) scenario
    _bank_row_key() hardening was meant to address at the identity level;
    this tests that the EXPLAINER layer also refuses to silently pick one.
    Uses the CONFIRMED real field names, same reasoning as the known-good
    test above."""
    batch_row = {
        "Settlement Status": "BANK REVIEW REQUIRED",
        "Settlement Batch ID": "BATCH-99999999-20260710",
        "Terminal ID": "99999999",
        "Settlement Date": "2026-07-10",
        "Payment Type": "VISA",
        "Provider": "ANB POS",
        "Gross Amount": 5000.00,
    }
    bank_row_1 = {
        "Narration Terminal ID": "99999999",
        "Bank Source File": "anb_statement_jul2026.xlsx",
        "Bank Source Sheet": "Sheet1",
        "Bank Source Row": 10,
        "Bank Date": "2026-07-11",
        "Bank Amount": 5000.00,
        "Description": "POS VC_GENERIC | SAMETEXT",
    }
    bank_row_2 = dict(bank_row_1)
    bank_row_2["Bank Source Row"] = 11  # different row, identical narration/amount/date

    requests = explainer.build_candidates(
        settlement_batches_rows=[batch_row],
        settlement_bank_unmatched_rows=[bank_row_1, bank_row_2],
        settlement_lag_days=1,
    )
    req = requests[0]
    assert len(req.candidates) == 2, "ambiguous case should shortlist both candidates"

    # Simulate a model response that (correctly, per the prompt's rules)
    # reports both candidates and low confidence.
    model_response = """{
        "verdict": "Partial / Gap Unexplained",
        "confidence": "Low",
        "candidate_bank_amount": 5000.00,
        "computed_net": null,
        "narration_decode": "Identical narration on two rows, cannot distinguish",
        "explanation": "Two bank credits share the same amount, date, and narration text; cannot determine which one this batch actually settled against.",
        "cited_rows": ["anb_statement_jul2026.xlsx::Sheet1::10", "anb_statement_jul2026.xlsx::Sheet1::11"]
    }"""

    result = explainer.parse_and_validate(req.batch_id, req.gross_pos_amount, model_response)
    assert result.confidence == "Low", "ambiguous multi-candidate case must never report above Low confidence"
    assert len(result.cited_rows) == 2
    print("[PASS] Known-ambiguous replay: two candidates surfaced, confidence forced to Low.")

    # Also test the guardrail itself: what if a (hypothetical, non-compliant)
    # model response tried to claim High confidence despite two cited rows?
    non_compliant_response = model_response.replace('"confidence": "Low"', '"confidence": "High"')
    guarded_result = explainer.parse_and_validate(req.batch_id, req.gross_pos_amount, non_compliant_response)
    assert guarded_result.confidence == "Low", (
        "GUARDRAIL FAILURE: parse_and_validate() must force confidence to Low "
        "when more than one row is cited, regardless of what the model claims."
    )
    print("[PASS] Guardrail enforced independently of model compliance: "
          "multi-citation response forced to Low confidence even when model said High.")


def test_missing_cited_rows_guardrail():
    """A 'Ties' verdict with no cited_rows must never pass through as-is —
    that's an unverifiable claim, treated as a bug per V32 spec §6."""
    model_response = """{
        "verdict": "Ties",
        "confidence": "High",
        "candidate_bank_amount": 100.0,
        "computed_net": 100.0,
        "narration_decode": "",
        "explanation": "Looks like a match.",
        "cited_rows": []
    }"""
    result = explainer.parse_and_validate("BATCH-X", 100.0, model_response)
    assert result.cited_rows == []
    assert result.verdict != "Ties", "a Ties verdict with empty cited_rows must be downgraded"
    assert result.confidence == "Low"
    print("[PASS] Missing-citation guardrail: 'Ties' with no cited_rows is downgraded, not trusted.")


def test_unparseable_response_fails_closed():
    result = explainer.parse_and_validate("BATCH-Y", 100.0, "not valid json at all")
    assert result.verdict == "No Plausible Candidate"
    assert result.confidence == "Low"
    print("[PASS] Unparseable model response fails closed (Low confidence, no candidate), not silently dropped.")


def test_schema_bug_confirmed_fixed():
    """
    Directly proves the schema bug flagged in review: on REAL field names
    (Narration Terminal ID on bank rows, not a bare Terminal ID), the OLD
    alias ("terminal_id" only mapping to "Terminal ID"/"Terminal") would
    have found zero candidates for every batch. The FIXED alias
    ("bank_terminal_id" -> "Narration Terminal ID") must find the real
    candidate.
    """
    batch_row = {
        "Settlement Status": "BANK REVIEW REQUIRED",
        "Settlement Batch ID": "BATCH-1",
        "Terminal ID": "12345678",
        "Provider": "ANB POS",
        "Gross Amount": 500.0,
    }
    # Bank row with ONLY the real field name -- no "Terminal ID" at all,
    # exactly as core.py/bank_settlement_extension.py actually produce it.
    bank_row_real_shape = {
        "Narration Terminal ID": "12345678",
        "Bank Source File": "f.xlsx", "Bank Source Sheet": "s", "Bank Source Row": 1,
        "Bank Date": "2026-07-01", "Bank Amount": 500.0,
        "Description": "some narration text",
    }

    reqs = explainer.build_candidates(
        settlement_batches_rows=[batch_row],
        settlement_bank_unmatched_rows=[bank_row_real_shape],
    )
    assert len(reqs) == 1
    # This is the assertion that would have FAILED before the fix (0
    # candidates, because the old code looked for "terminal_id" -> "Terminal
    # ID"/"Terminal", neither of which exists on a real bank row).
    assert len(reqs[0].candidates) == 1, (
        "REGRESSION: real-shaped bank row (Narration Terminal ID only) produced "
        "zero candidates -- the schema-alias bug is back."
    )
    assert reqs[0].candidates[0].narration == "some narration text", (
        "narration should read from 'Description' (confirmed real field), not a missing Narration/1/2/3"
    )
    print("[PASS] Schema bug confirmed fixed: real-shaped bank rows (Narration Terminal ID, Description) "
          "now produce correct candidates end-to-end.")


def test_prompt_matches_real_accounting_rule():
    """The prompt must state gross_pos_amount == candidate_bank_amount as the
    tie criterion, and must explicitly warn against the old, incorrect
    gross-fee-vat=net assumption -- otherwise the AI explainer can contradict
    the deterministic engine's actual rule."""
    req = explainer.ExplainerRequest(
        batch_id="X", provider="ANB POS", terminal_id="1", source_date="2026-07-01",
        scheme="MADA", gross_pos_amount=100.0, settlement_lag_days=0, candidates=[],
    )
    prompt = explainer.build_prompt(req)
    assert "gross_pos_amount == candidate_bank_amount" in prompt
    assert "since-corrected assumption" in prompt or "does not match how this engine actually" in prompt
    assert "not the tie criterion" in prompt
    print("[PASS] Prompt states the confirmed real accounting rule (gross == bank credit, "
          "fee/VAT informational only) and explicitly warns against the old wrong assumption.")


if __name__ == "__main__":
    print("=" * 70)
    print("PROVE_V32_AI_EXPLAINER.py")
    print("=" * 70)
    test_structural_no_write()
    test_known_good_replay()
    test_known_ambiguous_replay()
    test_missing_cited_rows_guardrail()
    test_unparseable_response_fails_closed()
    test_schema_bug_confirmed_fixed()
    test_prompt_matches_real_accounting_rule()
    print("=" * 70)
    print("All runnable checks passed, including schema-fix and prompt-correction proofs.")
    print("COLUMN_ALIASES is now CONFIRMED against the real core.py /")
    print("bank_settlement_extension.py source -- that step is done.")
    print("STILL NEEDED before production use (per V32 spec §7, NOT covered by this script):")
    print("  - Step 3: run against the REAL Review Required queue from a live")
    print("    st.session_state.ct_result (real data, not synthetic fixtures).")
    print("  - Step 5: cost/latency check once call_model_stub() is wired to")
    print("    an actual model endpoint -- it still raises NotImplementedError.")
    print("=" * 70)

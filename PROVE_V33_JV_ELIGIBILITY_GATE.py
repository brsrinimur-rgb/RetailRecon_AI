"""
PROVE_V33_JV_ELIGIBILITY_GATE.py

Tests logic/jv_eligibility_gate.py against synthetic fixtures modeled on
real scenarios from this conversation:
  - The 55610694 ANB example (BANK RECEIVED -> eligible).
  - A TABBY batch with Bank Settled=True at transaction level -> eligible.
  - A TAP batch still BANK RECEIPT PENDING (real state from the July 2026
    run before it was ever resolved) -> held.
  - A mixed TABBY (eligible) + TAP (held) case -> proves provider-split
    holds TAP independently while TABBY proceeds (§1a).
  - §1c: a row with only payout-side "Paid" info and no bank-side
    confirmation must NOT be treated as eligible.

Run: python3 PROVE_V33_JV_ELIGIBILITY_GATE.py
"""

import os
import tempfile

from logic import jv_eligibility_gate as gate


def test_bank_received_is_eligible():
    """The 55610694 / SAR 13,052.02 example — real bank credit, real gross-up proof."""
    row = {
        "Settlement Status": "BANK RECEIVED",
        "Unique Transaction ID": "BATCH-55610694-20260707",
        "Provider": "ANB POS",
        "Gross Amount": 13052.02,
        "Bank Source File": "anb_statement_jul2026.xlsx",
        "Bank Source Row": 42,
    }
    decisions = gate.evaluate_batches([row])
    assert len(decisions) == 1
    assert decisions[0].eligible is True
    assert "confirmed received against a bank statement row" in decisions[0].reason
    print("[PASS] BANK RECEIVED -> eligible, with correct reason.")


def test_review_required_is_held():
    row = {
        "Settlement Status": "BANK REVIEW REQUIRED",
        "Unique Transaction ID": "BATCH-XYZ",
        "Provider": "ANB POS",
        "Gross Amount": 1000.00,
    }
    decisions = gate.evaluate_batches([row])
    assert decisions[0].eligible is False
    assert "did not tie" in decisions[0].reason
    print("[PASS] BANK REVIEW REQUIRED -> held, with correct reason (§1a).")


def test_transaction_matched_only_is_held():
    """§1b: a POS/D365 match alone is never sufficient."""
    row = {
        "Settlement Status": "TRANSACTION MATCHED",
        "Unique Transaction ID": "TAP-1",
        "Provider": "TAP",
        "Gross Amount": 384.0,
    }
    decisions = gate.evaluate_batches([row])
    assert decisions[0].eligible is False
    assert "sale only" in decisions[0].reason
    print("[PASS] TRANSACTION MATCHED (no bank evidence) -> held (§1b).")


def test_receipt_pending_is_held():
    """Real state from the July 2026 run before AMEX/lag fixes: batches
    sitting at BANK RECEIPT PENDING must not qualify."""
    row = {
        "Settlement Status": "BANK RECEIPT PENDING",
        "Unique Transaction ID": "AMEX-BATCH-1",
        "Provider": "AMEX",
        "Gross Amount": 19676.88,
    }
    decisions = gate.evaluate_batches([row])
    assert decisions[0].eligible is False
    print("[PASS] BANK RECEIPT PENDING -> held (§1a).")


def test_tabby_transaction_level_bank_settled_is_eligible():
    """V27 §2: TABBY can have Bank Settled=True at transaction level even
    if inspected independent of a batch-level 'BANK RECEIVED' status."""
    row = {
        "Settlement Status": "BANK RECEIVED",  # batch-level, per V27 proof output
        "Bank Settled": True,
        "Unique Transaction ID": "TABBY-1",
        "Provider": "TABBY",
        "Gross Amount": 727.0,
    }
    decisions = gate.evaluate_batches([row])
    assert decisions[0].eligible is True
    print("[PASS] TABBY transaction-level Bank Settled=True -> eligible.")


def test_payout_confirmation_alone_is_not_eligible():
    """
    §1c: a row that only carries payout-side info (e.g. a provider's own
    'Paid' flag from its payout file) and has NOT reached a bank-confirmed
    Settlement Status must NOT be treated as eligible. This test
    deliberately does NOT set Settlement Status to BANK RECEIVED and does
    NOT set Bank Settled=True, simulating a payout file claiming payment
    while the bank-side match hasn't actually happened yet.
    """
    row = {
        "Settlement Status": "BANK RECEIPT PENDING",
        "Provider": "TAMARA",
        "Gross Amount": 5000.0,
        "Unique Transaction ID": "TAMARA-BATCH-9",
        # Simulated payout-side field that a naive implementation might be
        # tempted to trust on its own. This module must ignore it.
        "Payout File Paid Flag": True,
    }
    decisions = gate.evaluate_batches([row])
    assert decisions[0].eligible is False, (
        "GUARDRAIL FAILURE: a payout-side 'Paid' flag must never make an item "
        "eligible on its own — only a bank-side confirmed status can (§1c)."
    )
    print("[PASS] Payout-side confirmation alone does NOT satisfy §1c — held correctly.")


def test_provider_split_holds_independently():
    """Mixed TABBY (eligible) + TAP (held) — proves per-provider mode lets
    TABBY proceed while TAP is held, per §1a's provider-split clarification."""
    rows = [
        {"Settlement Status": "BANK RECEIVED", "Bank Settled": True,
         "Unique Transaction ID": "TABBY-1", "Provider": "TABBY", "Gross Amount": 727.0},
        {"Settlement Status": "BANK RECEIPT PENDING",
         "Unique Transaction ID": "TAP-1", "Provider": "TAP", "Gross Amount": 384.0},
    ]
    decisions = gate.evaluate_batches(rows)

    tmpdir = tempfile.mkdtemp()
    gl_path = os.path.join(tmpdir, "gl_config.json")
    gl_config = gate.GLConfig(path=gl_path)

    proposals = gate.group_for_jv(decisions, gl_config, mode="per_provider")
    by_provider = {p.provider: p for p in proposals}

    assert by_provider["TABBY"].line_count == 1
    assert by_provider["TABBY"].total_amount == 727.0
    assert by_provider["TABBY"].held_count == 0

    assert by_provider["TAP"].line_count == 0
    assert by_provider["TAP"].total_amount == 0
    assert by_provider["TAP"].held_count == 1
    assert "TAP-1" in by_provider["TAP"].held_batch_ids

    print("[PASS] Provider-split: TABBY proceeds (SAR 727.00), TAP held independently — §1a confirmed.")


def test_combined_mode_still_excludes_held_items():
    rows = [
        {"Settlement Status": "BANK RECEIVED", "Bank Settled": True,
         "Unique Transaction ID": "TABBY-1", "Provider": "TABBY", "Gross Amount": 727.0},
        {"Settlement Status": "BANK RECEIPT PENDING",
         "Unique Transaction ID": "TAP-1", "Provider": "TAP", "Gross Amount": 384.0},
    ]
    decisions = gate.evaluate_batches(rows)
    tmpdir = tempfile.mkdtemp()
    gl_config = gate.GLConfig(path=os.path.join(tmpdir, "gl_config.json"))
    proposals = gate.group_for_jv(decisions, gl_config, mode="combined")

    assert len(proposals) == 1
    combined = proposals[0]
    assert combined.total_amount == 727.0, "held TAP-1 must not be included in the combined total"
    assert combined.held_count == 1
    assert "TAP-1" in combined.held_batch_ids
    assert "TAP-1" not in combined.batch_ids
    print("[PASS] Combined mode: held items excluded from total but still visible in held_batch_ids.")


def test_gl_config_editable_and_persists():
    """§3a: GL codes must be editable and not hardcoded into the logic."""
    tmpdir = tempfile.mkdtemp()
    gl_path = os.path.join(tmpdir, "gl_config.json")

    gl_config = gate.GLConfig(path=gl_path)
    assert gl_config.get("TABBY")["bank_gl"] == "1010", "default should be 1010 per confirmed GL code"

    gl_config.set_bank_gl("TABBY", "2020")
    assert gl_config.get("TABBY")["bank_gl"] == "2020"

    # Reload from disk to prove the edit persisted, not just in-memory.
    reloaded = gate.GLConfig(path=gl_path)
    assert reloaded.get("TABBY")["bank_gl"] == "2020", "edit must persist to disk"
    print("[PASS] GL code is editable at runtime and the edit persists across reloads (§3a).")


def test_mixed_gl_flagged_in_combined_mode():
    """If combined mode somehow spans providers with different bank GLs,
    that must be surfaced, not silently averaged/guessed."""
    rows = [
        {"Settlement Status": "BANK RECEIVED", "Bank Settled": True,
         "Unique Transaction ID": "TABBY-1", "Provider": "TABBY", "Gross Amount": 100.0},
        {"Settlement Status": "BANK RECEIVED",
         "Unique Transaction ID": "ANB-1", "Provider": "ANB POS", "Gross Amount": 200.0},
    ]
    decisions = gate.evaluate_batches(rows)
    tmpdir = tempfile.mkdtemp()
    gl_config = gate.GLConfig(path=os.path.join(tmpdir, "gl_config.json"))
    # TABBY defaults to 1010, ANB POS defaults to TBD-ANB -- different GLs.
    proposals = gate.group_for_jv(decisions, gl_config, mode="combined")
    assert proposals[0].bank_gl == "MIXED-GL-NEEDS-SPLIT", (
        "combined mode spanning different bank GLs must flag itself, not pick one silently"
    )
    print("[PASS] Combined mode across mismatched GL codes is flagged, not silently resolved.")


if __name__ == "__main__":
    print("=" * 70)
    print("PROVE_V33_JV_ELIGIBILITY_GATE.py")
    print("=" * 70)
    test_bank_received_is_eligible()
    test_review_required_is_held()
    test_transaction_matched_only_is_held()
    test_receipt_pending_is_held()
    test_tabby_transaction_level_bank_settled_is_eligible()
    test_payout_confirmation_alone_is_not_eligible()
    test_provider_split_holds_independently()
    test_combined_mode_still_excludes_held_items()
    test_gl_config_editable_and_persists()
    test_mixed_gl_flagged_in_combined_mode()
    print("=" * 70)
    print("All runnable checks passed.")
    print("STILL NEEDED before this drives real JV creation:")
    print("  - The actual JV creation source + db.py, to wire eligible")
    print("    JVProposal objects into a real posted JV rather than a dict.")
    print("  - Confirm real column names against live core.py output")
    print("    (COLUMN_ALIASES in jv_eligibility_gate.py).")
    print("  - Confirm clearing_gl codes per provider (currently TBD-* ")
    print("    placeholders) against the real chart of accounts.")
    print("  - Confirm whether the hold/pass grain is per-batch or")
    print("    per-transaction for TABBY specifically (V33 spec §1a).")
    print("=" * 70)

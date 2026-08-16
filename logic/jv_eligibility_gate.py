"""
logic/jv_eligibility_gate.py
V33 — JV eligibility gate.

This module decides WHICH already-reconciled items are eligible to be
proposed for JV creation, and produces per-provider or combined JV
proposals with GL codes attached. It does NOT create, post, or write a JV
anywhere — there is no db.py write path in this file at all. It's a
pre-JV decision/staging layer, built to be wired into the real JV
creation code once that source is available (see module-level caveat).

Implements, precisely:
  §1a — hold JV eligibility if bank settlement evidence is missing.
  §1b — pass condition is "amount actually received in the bank"
        (BANK RECEIVED / transaction-level Bank Settled=True), never a
        POS/D365-only match and never an unresolved Review Required
        candidate.
  §1c — "received" means landed in OUR OWN bank account (matched to a
        real Al Rajhi/ANB statement row), never just a provider's own
        payout-file confirmation. This module never treats a
        Provider Payout Batches row as sufficient on its own — see
        _is_bank_confirmed() below, which requires the settlement-side
        status field, not the payout-side one.
  §1 (provider-split) — group_for_jv() supports "combined" or
        "per_provider" output.
  §3a — GL codes are read from an editable mapping (JSON-backed), never
        hardcoded into the eligibility/grouping logic itself.

------------------------------------------------------------------------------
HONESTY NOTE (same caveat as ai_settlement_explainer.py):

Written against the *documented* shape of st.session_state.ct_result
(V25-V33 project specs), not against real core.py/db.py source, which has
never been provided in this engagement. Column names live in
COLUMN_ALIASES below - update them once the real Settlement Batches /
matched DataFrame schema is confirmed.

This module produces JV PROPOSALS (dicts). Turning a proposal into an
actual posted JV still requires the real db.py write path and JV
creation UI, which this module deliberately does not guess at.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


COLUMN_ALIASES = {
    "settlement_status": ["Settlement Status"],
    "bank_settled": ["Bank Settled"],
    "batch_id": ["Unique Transaction ID", "Batch ID", "Settlement Batch ID"],
    "provider": ["Provider"],
    "gross_amount": ["Gross Amount", "Expected Bank Amount", "Net Amount", "Amount"],
    "terminal_id": ["Terminal ID", "Terminal"],
    "source_date": ["Source Date", "Settlement Date", "Date"],
    "bank_source_file": ["Bank Source File"],
    "bank_source_row": ["Bank Source Row"],
}

# States that satisfy §1b/§1c — matched to a real bank-statement row, not
# just a provider payout confirmation and not just a POS/D365 match.
BANK_CONFIRMED_STATES = {"BANK RECEIVED"}

# States that must always be held, with a human-readable reason.
HOLD_REASONS = {
    "TRANSACTION MATCHED": "Matched to sale only — no bank settlement evidence yet.",
    "BANK REVIEW REQUIRED": "Bank candidate found but amount did not tie — unresolved.",
    "BANK RECEIPT PENDING": "No bank credit matched yet.",
}


def _get(row: dict, key: str, default=None):
    for candidate in COLUMN_ALIASES.get(key, [key]):
        if candidate in row and row[candidate] not in (None, ""):
            return row[candidate]
    return default


# ------------------------------------------------------------------------
# §3a — editable GL code mapping. Backed by a small JSON file so it can be
# edited without a code change. Falls back to sensible in-memory defaults
# if the file doesn't exist yet (first run).
# ------------------------------------------------------------------------
DEFAULT_GL_CONFIG = {
    # provider -> {"bank_gl": ..., "clearing_gl": ...}
    # bank_gl = the shared Al Rajhi bank account leg (confirmed code: 1010).
    # clearing_gl is left as a placeholder ("TBD-<provider>") deliberately —
    # V33 spec §1 open question 3 flags that provider-specific
    # revenue/clearing GL mapping is NOT yet confirmed. Do not treat these
    # placeholders as real GL codes.
    "TABBY": {"bank_gl": "1010", "clearing_gl": "TBD-TABBY"},
    "TAMARA": {"bank_gl": "1010", "clearing_gl": "TBD-TAMARA"},
    "TAP": {"bank_gl": "1010", "clearing_gl": "TBD-TAP"},
    # ANB/AMEX not part of this request's scope (they settle via ANB, not
    # Al Rajhi) but included as an explicit "not 1010" reminder rather than
    # silently omitted.
    "ANB POS": {"bank_gl": "TBD-ANB", "clearing_gl": "TBD-ANB-CLEARING"},
    "AMEX": {"bank_gl": "TBD-AMEX", "clearing_gl": "TBD-AMEX-CLEARING"},
}


class GLConfig:
    """Editable GL code mapping, persisted to a JSON file so edits survive
    beyond one session. Never hardcode a GL code anywhere else — read it
    through this class."""

    def __init__(self, path: str = "gl_config.json"):
        self.path = path
        self._config = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                return json.load(f)
        return json.loads(json.dumps(DEFAULT_GL_CONFIG))  # deep copy

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self._config, f, indent=2)

    def get(self, provider: str) -> dict:
        return self._config.get(provider, {"bank_gl": "UNMAPPED", "clearing_gl": "UNMAPPED"})

    def set_bank_gl(self, provider: str, gl_code: str, persist: bool = True):
        self._config.setdefault(provider, {})["bank_gl"] = gl_code
        if persist:
            self.save()

    def set_clearing_gl(self, provider: str, gl_code: str, persist: bool = True):
        self._config.setdefault(provider, {})["clearing_gl"] = gl_code
        if persist:
            self.save()

    def as_dict(self) -> dict:
        return json.loads(json.dumps(self._config))


@dataclass
class EligibilityDecision:
    batch_id: str
    provider: str
    amount: Optional[float]
    eligible: bool
    reason: str
    settlement_status: str
    source_ref: str = ""  # bank_source_file::bank_source_row, for traceability

    def to_dict(self) -> dict:
        return asdict(self)


def _is_bank_confirmed(row: dict) -> bool:
    """
    §1c enforcement point: this checks ONLY the settlement-side status
    field (Settlement Status / Bank Settled), which per every V24-V31 spec
    is set from a match against a real bank-statement row. It deliberately
    never reads a Provider Payout Batches "Paid" flag or similar as a
    substitute — a payout file's own confirmation is not bank evidence.
    If the real schema turns out to have a payout-side flag that some
    other code path treats as sufficient, that is exactly the shortcut
    §1c says must be corrected, not replicated here.
    """
    status = _get(row, "settlement_status", "")
    if status in BANK_CONFIRMED_STATES:
        return True
    # Transaction-level TABBY case (V27 §2): Bank Settled=True can be set
    # on a matched transaction even if inspected independently of the
    # batch-level Settlement Status column.
    bank_settled = _get(row, "bank_settled", None)
    if bank_settled is True or str(bank_settled).strip().lower() == "true":
        return True
    return False


def evaluate_batches(rows: list[dict]) -> list[EligibilityDecision]:
    """
    §1a/§1b/§1c: decide, per row (batch or transaction — whichever grain
    the caller passes in), whether it's eligible for JV creation.

    This function does not care whether `rows` are Settlement Batches or
    individual matched transactions — the same rule applies at either
    grain (see V33 spec §1a's open question about which grain the real
    system needs; this function is grain-agnostic on purpose so it can be
    called either way once that's confirmed).
    """
    decisions = []
    for row in rows:
        batch_id = str(_get(row, "batch_id", "UNKNOWN"))
        provider = str(_get(row, "provider", "UNKNOWN"))
        amount = _get(row, "gross_amount")
        status = str(_get(row, "settlement_status", "UNKNOWN"))
        source_file = _get(row, "bank_source_file", "")
        source_row = _get(row, "bank_source_row", "")
        source_ref = f"{source_file}::{source_row}" if source_file else ""

        if _is_bank_confirmed(row):
            decisions.append(EligibilityDecision(
                batch_id=batch_id, provider=provider, amount=amount,
                eligible=True,
                reason="Amount confirmed received against a bank statement row.",
                settlement_status=status, source_ref=source_ref,
            ))
        else:
            reason = HOLD_REASONS.get(status, f"Not yet bank-confirmed (status: {status}).")
            decisions.append(EligibilityDecision(
                batch_id=batch_id, provider=provider, amount=amount,
                eligible=False, reason=reason,
                settlement_status=status, source_ref=source_ref,
            ))
    return decisions


@dataclass
class JVProposal:
    mode: str  # "combined" | "per_provider"
    provider: str  # "ALL" for combined mode
    bank_gl: str
    clearing_gl: str
    total_amount: float
    line_count: int
    batch_ids: list = field(default_factory=list)
    held_count: int = 0
    held_batch_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def group_for_jv(
    decisions: list[EligibilityDecision],
    gl_config: GLConfig,
    mode: str = "per_provider",
) -> list[JVProposal]:
    """
    §1 (provider-split): builds JV proposals from eligible decisions only.
    Held (ineligible) items are reported alongside for visibility (per
    V33 spec §4 open question 6: held items should be visible, not
    silently dropped) but are never included in total_amount or
    batch_ids.

    mode="combined": one proposal across all providers.
    mode="per_provider": one proposal per provider, independently gated —
        a provider with zero eligible items still gets a proposal entry
        with total_amount=0 and its held items listed, so it's visible
        that the provider was considered and excluded, not forgotten.
    """
    if mode not in ("combined", "per_provider"):
        raise ValueError(f"mode must be 'combined' or 'per_provider', got {mode!r}")

    eligible = [d for d in decisions if d.eligible]
    held = [d for d in decisions if not d.eligible]

    if mode == "combined":
        total = sum(d.amount for d in eligible if d.amount is not None)
        # Combined mode still needs a GL leg; without a single provider,
        # bank_gl is only meaningful if all eligible providers share one
        # (true for TABBY/Tamara/TAP under 1010) — flag if not.
        providers_in_scope = {d.provider for d in eligible}
        bank_gls = {gl_config.get(p)["bank_gl"] for p in providers_in_scope} if providers_in_scope else set()
        bank_gl = bank_gls.pop() if len(bank_gls) == 1 else "MIXED-GL-NEEDS-SPLIT"
        return [JVProposal(
            mode="combined", provider="ALL",
            bank_gl=bank_gl, clearing_gl="MIXED" if len(providers_in_scope) != 1 else gl_config.get(next(iter(providers_in_scope)))["clearing_gl"],
            total_amount=round(total, 2), line_count=len(eligible),
            batch_ids=[d.batch_id for d in eligible],
            held_count=len(held), held_batch_ids=[d.batch_id for d in held],
        )]

    # per_provider
    all_providers = sorted({d.provider for d in decisions})
    proposals = []
    for provider in all_providers:
        prov_eligible = [d for d in eligible if d.provider == provider]
        prov_held = [d for d in held if d.provider == provider]
        gl = gl_config.get(provider)
        total = sum(d.amount for d in prov_eligible if d.amount is not None)
        proposals.append(JVProposal(
            mode="per_provider", provider=provider,
            bank_gl=gl["bank_gl"], clearing_gl=gl["clearing_gl"],
            total_amount=round(total, 2), line_count=len(prov_eligible),
            batch_ids=[d.batch_id for d in prov_eligible],
            held_count=len(prov_held), held_batch_ids=[d.batch_id for d in prov_held],
        ))
    return proposals

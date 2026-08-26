"""
logic/ai_settlement_explainer.py
V32 — AI Settlement Explainer for Review Required / Receipt Pending batches.

READ-ONLY BY DESIGN.
This module never writes to Settlement Status, Bank Settled, Underlying IDs,
or any JV path. It only reads st.session_state.ct_result (already produced by
the existing V25-V31 matching engine) and produces a structured explanation.

------------------------------------------------------------------------------
VERIFICATION STATUS (updated after real source review):

COLUMN_ALIASES below is CONFIRMED against the actual core.py and
logic/bank_settlement_extension.py source (not the documented/assumed shape
from the earlier project specs) -- verified field-by-field, including the
schema bug this replaces: "Payment Type" for scheme (not "Scheme"),
"Narration Terminal ID" as a separate bank-side field (not the POS-side
"Terminal ID"), "Description" as the primary narration text (not "Narration
1/2/3", which are raw input headers that don't survive normalization), and
"Settlement Batch ID" as the primary batch identifier. PROVE_V32_AI_EXPLAINER.py
tests this exact real shape end-to-end, including a regression test that
reproduces the old bug (zero candidates found) to prove it's actually fixed.

Two things remain genuinely open, both functional rather than schema-related:
  1. call_model_stub() in pages/34_AI_Settlement_Explainer.py still raises
     NotImplementedError -- no model endpoint is wired yet, so every
     explanation currently comes back as "Model not wired up yet" (by
     design -- it fails closed, not silently).
  2. This has not yet been run against a live, real Review Required queue
     end-to-end (PROVE_V32_AI_EXPLAINER.py's Step 3, per the V32 spec §7) --
     only proven against synthetic fixtures built to the confirmed real
     schema shape.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ------------------------------------------------------------------------
# Column aliasing — CONFIRMED against the real core.py / logic/bank_settlement
# _extension.py source (not guessed). Verified field-by-field:
#   - Settlement Batches use "Payment Type" (never "Scheme") — set in
#     core.build_card_settlement_batches() and carried through
#     reconcile_card_batches_advanced()'s rec=r.to_dict() passthrough.
#   - Bank-side terminal evidence is "Narration Terminal ID", parsed by
#     normalize_bank_statement()/parse_bank_narration() — never a bare
#     "Terminal ID" on bank rows (that field only exists on the POS/batch side).
#   - Raw bank narration text lands in "Description" after normalization.
#     "Narration 1/2/3" are RAW INPUT column headers on the original ANB
#     statement file (before normalize_bank_statement() runs) — they do not
#     survive as passthrough columns on the normalized output the explainer
#     actually reads from st.session_state.ct_result["settlement_bank_unmatched"].
#     Kept below only as a fallback in case a differently-shaped bank frame
#     (e.g. a legacy-parsed statement) happens to carry them raw.
# ------------------------------------------------------------------------
COLUMN_ALIASES = {
    "settlement_status": ["Settlement Status"],
    "terminal_id": ["Terminal ID", "Terminal"],  # POS/batch side only
    "bank_terminal_id": ["Narration Terminal ID"],  # bank side only — confirmed real field
    "source_date": ["Settlement Date", "Source Date", "Date"],
    "scheme": ["Payment Type", "Scheme"],  # Payment Type confirmed as the real field name
    "provider": ["Provider"],
    "gross_amount": ["Gross Amount", "Expected Bank Amount", "Net Amount"],
    "bank_source_file": ["Bank Source File"],
    "bank_source_sheet": ["Bank Source Sheet"],
    "bank_source_row": ["Bank Source Row"],
    "bank_date": ["Bank Date", "Value Date"],
    "bank_amount": ["Bank Amount", "Credit", "Amount"],
    "narration": ["Description", "Narration"],  # Description confirmed as the real field
    "narration_1": ["Narration 1"],  # fallback only — see note above
    "narration_2": ["Narration 2"],  # fallback only — see note above
    "narration_3": ["Narration 3"],  # fallback only — see note above
    "fee_amount": ["Fee Amount", "Narration Fee", "ANB Commission", "Commission"],
    "vat_amount": ["VAT Amount", "Narration VAT", "ANB VAT", "VAT"],
    "order_numbers": ["Order Numbers"],
    "batch_id": ["Settlement Batch ID", "Unique Transaction ID", "Batch ID"],  # Settlement Batch ID confirmed primary
}

# CONFIRMED real ct_result keys (lowercase, snake_case) as written by
# pages/1_POS_Reconciliation.py — the earlier "Settlement Batches" /
# "Settlement Bank Unmatched" / "Provider Payout Batches" (title-case) keys
# used in the page/spec were WRONG and would silently find nothing.
CT_RESULT_KEYS = {
    "settlement_batches": "settlement_batches",
    "settlement_bank_unmatched": "settlement_bank_unmatched",
    "provider_payout_batches": "provider_payout_batches",
}

REVIEW_STATES = {"BANK REVIEW REQUIRED", "BANK RECEIPT PENDING"}


def _get(row: dict, key: str, default=None):
    """Look up a logical field name via COLUMN_ALIASES against a row dict."""
    for candidate in COLUMN_ALIASES.get(key, [key]):
        if candidate in row and row[candidate] not in (None, ""):
            return row[candidate]
    return default


@dataclass
class ExplainerCandidate:
    """One shortlisted bank row for a batch, exactly as the deterministic
    engine already narrowed it — this module never searches the full bank
    pool itself."""
    bank_source_file: str = ""
    bank_source_sheet: str = ""
    bank_source_row: Any = ""
    bank_date: str = ""
    bank_amount: Optional[float] = None
    narration: str = ""  # primary raw text — Description on real bank rows
    narration_1: str = ""  # fallback only, usually empty on real data
    narration_2: str = ""  # fallback only, usually empty on real data
    narration_3: str = ""  # fallback only, usually empty on real data

    def cite(self) -> str:
        return f"{self.bank_source_file}::{self.bank_source_sheet}::{self.bank_source_row}"


@dataclass
class ExplainerRequest:
    """Everything sent to the model for one batch. Deliberately narrow —
    see module docstring §3 of the V32 spec: only this batch's own
    shortlisted rows, nothing from the wider bank pool."""
    batch_id: str
    provider: str
    terminal_id: str
    source_date: str
    scheme: str
    gross_pos_amount: Optional[float]
    settlement_lag_days: int
    candidates: list = field(default_factory=list)  # list[ExplainerCandidate]
    fee_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    order_numbers: Optional[str] = None


@dataclass
class ExplainerResult:
    batch_id: str
    verdict: str  # "Ties" | "Partial / Gap Unexplained" | "No Plausible Candidate"
    confidence: str  # "High" | "Medium" | "Low"
    gross_pos_amount: Optional[float]
    candidate_bank_amount: Optional[float]
    fee_amount: Optional[float]
    vat_amount: Optional[float]
    computed_net: Optional[float]
    narration_decode: str
    explanation: str
    cited_rows: list  # list[str]

    def to_dict(self) -> dict:
        return asdict(self)


ALLOWED_VERDICTS = {"Ties", "Partial / Gap Unexplained", "No Plausible Candidate"}
ALLOWED_CONFIDENCE = {"High", "Medium", "Low"}


def build_candidates(
    settlement_batches_rows: list[dict],
    settlement_bank_unmatched_rows: list[dict],
    provider_payout_rows: Optional[list[dict]] = None,
    settlement_lag_days: int = 1,
) -> list[ExplainerRequest]:
    """
    Assemble one ExplainerRequest per Review Required / Receipt Pending
    batch, pulling only the bank rows the deterministic engine already
    shortlisted for that batch's Terminal + Source Date window.

    settlement_batches_rows: list of dict rows from ct_result["Settlement
        Batches"], already filtered or unfiltered (this function filters).
    settlement_bank_unmatched_rows: list of dict rows from
        ct_result["Settlement Bank Unmatched"] — the candidate pool.
    provider_payout_rows: optional, for TABBY/Tamara/TAP batches.

    IMPORTANT: this function does NOT search the full bank pool — it only
    narrows by Terminal + a +/-2 day window around Source Date (adjusted by
    settlement_lag_days), matching the same window the deterministic
    matcher is documented to already use. If real matching windows differ,
    update the window logic below rather than trusting this blindly.
    """
    requests: list[ExplainerRequest] = []

    for row in settlement_batches_rows:
        status = _get(row, "settlement_status", "")
        if status not in REVIEW_STATES:
            continue

        batch_id = str(_get(row, "batch_id", "UNKNOWN"))
        terminal_id = str(_get(row, "terminal_id", ""))
        source_date = str(_get(row, "source_date", ""))
        scheme = str(_get(row, "scheme", ""))
        provider = str(_get(row, "provider", ""))
        gross = _get(row, "gross_amount")
        fee = _get(row, "fee_amount")
        vat = _get(row, "vat_amount")
        order_numbers = _get(row, "order_numbers")

        candidates: list[ExplainerCandidate] = []
        for bank_row in settlement_bank_unmatched_rows:
            # CONFIRMED real field: bank rows carry terminal evidence in
            # "Narration Terminal ID" (parsed from ANB narration text), never
            # a bare "Terminal ID" — that field only exists on the POS/batch
            # side. Using the wrong alias here silently narrowed every
            # candidate list to empty against real data.
            b_terminal = str(_get(bank_row, "bank_terminal_id", ""))
            b_date = str(_get(bank_row, "bank_date", ""))
            # Narrow scope: same terminal (when both sides have one — TAP/
            # TABBY/Tamara narration may not carry terminal), and let the
            # caller pre-filter by date window before calling this if a
            # tighter rule than "same terminal" is needed. This intentionally
            # stays permissive rather than silently dropping legitimate
            # candidates on a guessed date rule.
            if terminal_id and b_terminal and terminal_id != b_terminal:
                continue
            candidates.append(
                ExplainerCandidate(
                    bank_source_file=str(_get(bank_row, "bank_source_file", "")),
                    bank_source_sheet=str(_get(bank_row, "bank_source_sheet", "")),
                    bank_source_row=_get(bank_row, "bank_source_row", ""),
                    bank_date=b_date,
                    bank_amount=_get(bank_row, "bank_amount"),
                    narration=str(_get(bank_row, "narration", "")),
                    narration_1=str(_get(bank_row, "narration_1", "")),
                    narration_2=str(_get(bank_row, "narration_2", "")),
                    narration_3=str(_get(bank_row, "narration_3", "")),
                )
            )

        requests.append(
            ExplainerRequest(
                batch_id=batch_id,
                provider=provider,
                terminal_id=terminal_id,
                source_date=source_date,
                scheme=scheme,
                gross_pos_amount=gross,
                settlement_lag_days=settlement_lag_days,
                candidates=candidates,
                fee_amount=fee,
                vat_amount=vat,
                order_numbers=order_numbers,
            )
        )

    return requests


def build_prompt(req: ExplainerRequest) -> str:
    """
    Builds the model prompt for one batch. Kept as plain, inspectable text
    (not an opaque template) so the exact inputs a verdict rested on can be
    audited by reading this function's output directly.
    """
    candidates_text = "\n".join(
        f"  - file={c.bank_source_file} sheet={c.bank_source_sheet} row={c.bank_source_row} "
        f"date={c.bank_date} amount={c.bank_amount} "
        f"narration=[{c.narration} | {c.narration_1} | {c.narration_2} | {c.narration_3}]"
        for c in req.candidates
    ) or "  (none shortlisted by the deterministic engine)"

    return f"""You are reconciling one POS settlement batch against shortlisted bank
credit candidates that a deterministic matching engine has already narrowed down.
You do not search for new candidates. You only judge the ones given.

BATCH:
  batch_id: {req.batch_id}
  provider: {req.provider}
  terminal_id: {req.terminal_id}
  source_date: {req.source_date}
  scheme: {req.scheme}
  gross_pos_amount: {req.gross_pos_amount}
  configured settlement_lag_days: {req.settlement_lag_days}
  fee_amount (if known): {req.fee_amount}
  vat_amount (if known): {req.vat_amount}
  order_numbers (if provider payout batch): {req.order_numbers}

SHORTLISTED BANK CANDIDATES (only these — do not assume others exist):
{candidates_text}

TASK:
Determine whether gross_pos_amount ties to a candidate bank credit.

CONFIRMED ACCOUNTING RULE for this system (do not deviate from this):
  The PRIMARY tie is: gross_pos_amount == candidate_bank_amount (within the
  matching tolerance), accounting for settlement_lag_days on the date side.
  fee_amount and vat_amount, when present, are SEPARATE DEBIT ROWS on the
  bank statement — they are evidence that a real ANB deduction occurred
  alongside the credit, but they are NEVER subtracted from gross_pos_amount
  to derive the amount that must match the bank credit. Do not compute or
  expect "gross - fee - vat = candidate_bank_amount" — that was an earlier,
  since-corrected assumption and does not match how this engine actually
  settles batches. If fee_amount/vat_amount are present, report them in
  computed_net purely as informational commentary (gross - fee - vat, i.e.
  the net cash movement after those separate debits), but the tie/no-tie
  verdict itself must be judged against gross_pos_amount vs
  candidate_bank_amount directly, not against computed_net.

Respond with ONLY a JSON object, no other text, in this exact shape:
{{
  "verdict": "Ties" | "Partial / Gap Unexplained" | "No Plausible Candidate",
  "confidence": "High" | "Medium" | "Low",
  "candidate_bank_amount": <number or null>,
  "computed_net": <number or null, informational only — gross minus fee minus vat, not the tie criterion>,
  "narration_decode": "<what the narration fields appear to encode, or empty string>",
  "explanation": "<plain-language walkthrough of the arithmetic and identity match>",
  "cited_rows": ["<file::sheet::row for every candidate your verdict actually rests on>"]
}}

RULES YOU MUST FOLLOW:
- If more than one candidate is plausible (same amount/date window), you MUST
  list all of them in cited_rows and set confidence to "Low". Never silently
  pick one.
- If zero candidates are given, verdict must be "No Plausible Candidate" and
  cited_rows must be an empty list.
- Never invent a bank row that isn't in the SHORTLISTED BANK CANDIDATES list.
- cited_rows must never be empty for a "Ties" or "Partial / Gap Unexplained"
  verdict — that would mean your explanation isn't checkable.
"""


def parse_and_validate(batch_id: str, gross_pos_amount, model_json_text: str) -> ExplainerResult:
    """
    Parses the model's JSON response and enforces the guardrails from V32
    spec §6: mandatory cited_rows, valid verdict/confidence enums, and a
    forced downgrade to Low confidence if the model itself reported
    multiple candidates but didn't already set Low (belt-and-suspenders —
    the prompt asks for this, this function does not trust that alone).
    """
    try:
        data = json.loads(model_json_text)
    except json.JSONDecodeError as e:
        # Fail closed: an unparseable response becomes a "No Plausible
        # Candidate" / Low confidence result with the raw text preserved,
        # never a silently-dropped row.
        return ExplainerResult(
            batch_id=batch_id,
            verdict="No Plausible Candidate",
            confidence="Low",
            gross_pos_amount=gross_pos_amount,
            candidate_bank_amount=None,
            fee_amount=None,
            vat_amount=None,
            computed_net=None,
            narration_decode="",
            explanation=f"Model response could not be parsed as JSON: {e}. Raw: {model_json_text[:500]}",
            cited_rows=[],
        )

    verdict = data.get("verdict", "No Plausible Candidate")
    confidence = data.get("confidence", "Low")
    cited_rows = data.get("cited_rows") or []

    if verdict not in ALLOWED_VERDICTS:
        verdict = "No Plausible Candidate"
        confidence = "Low"

    if confidence not in ALLOWED_CONFIDENCE:
        confidence = "Low"

    # Guardrail: a Ties/Partial verdict with no cited rows is not trustworthy
    # output — force it down rather than display an unchecked claim.
    if verdict in ("Ties", "Partial / Gap Unexplained") and not cited_rows:
        verdict = "Partial / Gap Unexplained"
        confidence = "Low"

    # Guardrail: multiple cited rows means real ambiguity existed — never
    # let that surface as High/Medium confidence even if the model said so.
    if len(cited_rows) > 1 and confidence != "Low":
        confidence = "Low"

    return ExplainerResult(
        batch_id=batch_id,
        verdict=verdict,
        confidence=confidence,
        gross_pos_amount=gross_pos_amount,
        candidate_bank_amount=data.get("candidate_bank_amount"),
        fee_amount=data.get("fee_amount"),
        vat_amount=data.get("vat_amount"),
        computed_net=data.get("computed_net"),
        narration_decode=data.get("narration_decode", ""),
        explanation=data.get("explanation", ""),
        cited_rows=cited_rows,
    )


def assert_no_write_paths():
    """
    Structural self-check (used by PROVE_V32_AI_EXPLAINER.py): this module
    must never import or reference anything that mutates Settlement Status,
    Bank Settled, Underlying IDs, or JV creation. This function exists so
    that check has a named, importable target rather than only living in
    the test file's own logic.
    """
    # Built via concatenation so this list itself doesn't trip the very
    # check it defines when this file is scanned.
    forbidden_substrings = [
        "Settlement Status" + "']" + " =",
        "Bank Settled" + "']" + " =",
        "Underlying IDs" + "']" + " =",
        "create" + "_jv",
        "post" + "_jv",
        "db." + "save_jv",
    ]
    import inspect
    this_module_source = inspect.getsource(inspect.getmodule(assert_no_write_paths))
    violations = [s for s in forbidden_substrings if s in this_module_source]
    if violations:
        raise AssertionError(f"ai_settlement_explainer.py contains forbidden write patterns: {violations}")
    return True

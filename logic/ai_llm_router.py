"""
logic/ai_llm_router.py -- V46, additive, OPTIONAL.

WHY THIS EXISTS
----------------
ai_copilot.py's question understanding (interpret_query()) is a hand-written
keyword/regex classifier: it can only recognize the exact phrasings someone
has already thought to code for. That's why every previous Copilot fix in
this engagement was "add one more pattern for one more phrasing" -- accurate
and free, but never able to handle a genuinely novel way of asking something.

This module adds an OPTIONAL real-AI understanding layer on top of that,
using the Anthropic API, so a much wider range of natural phrasings can be
understood correctly. It is deliberately scoped to UNDERSTANDING ONLY:

  * This module NEVER computes or states a single financial number itself.
  * It NEVER writes the answer text the user sees.
  * Its entire job is: read the free-form question and return which of the
    ALREADY-IMPLEMENTED report types it's asking for, and which store(s) /
    payment method it's scoped to -- a small, strictly-enumerated structured
    result (via Anthropic's tool-use / structured output, not free text).
  * Every actual number, table, and answer sentence is still produced by
    the exact same, already-tested calculation functions in ai_copilot.py
    (_sales_answer, _cash_report, _risk_answer, etc.) that run today without
    this module. This module only decides WHICH of those functions to call
    and with WHAT scope -- it can misroute a question, but it can never
    invent or alter a number, because it never touches the data itself.

GRACEFUL DEGRADATION -- READ THIS BEFORE CHANGING ANYTHING
------------------------------------------------------------
Every public function in this module returns None on ANY failure: no API
key configured, the `anthropic` package not installed, a network error, a
timeout, an unexpected response shape, anything. It never raises out to the
caller. ai_copilot.py treats None exactly like "this feature isn't turned on
right now" and falls straight back to its original, fully-tested
keyword/regex classifier -- so:

  * If you never add an API key: nothing about the app changes. Every
    existing behavior and every existing regression test is unaffected.
  * If the API key is added but a call fails or times out on some question:
    that one question falls back to the regex classifier silently, the user
    still gets an answer, just via the older path for that turn.

SETUP (see the accompanying V46 doc for full instructions)
------------------------------------------------------------
1. `pip install anthropic` (already added to requirements.txt).
2. Get an API key at https://console.anthropic.com and set it as either:
     - an environment variable ANTHROPIC_API_KEY, or
     - a Streamlit secret: add ANTHROPIC_API_KEY = "sk-ant-..." under
       .streamlit/secrets.toml (Streamlit Cloud: Settings -> Secrets).
3. Optionally set ANTHROPIC_COPILOT_MODEL to override the default model
   (see _DEFAULT_MODEL below) -- e.g. to use a more powerful model if you
   want higher accuracy on ambiguous questions at higher per-question cost.
   Check https://docs.claude.com for the current list of available models
   before changing this -- model names/availability change over time.
4. That's it. No other code change is required to turn this on or off.
"""
from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
_DEFAULT_MODEL = "claude-3-5-haiku-20241022"  # fast + cheap; verify still current at docs.claude.com
_DEFAULT_TIMEOUT_SECONDS = 8
_DEFAULT_MAX_TOKENS = 400

# Must exactly match every `intent=="..."` value ai_copilot.answer_question()
# actually handles, plus the implicit "summary" fallback. "unknown" is a
# deliberate escape hatch: the model is instructed to use it whenever a
# question doesn't confidently fit one of the real categories, so the
# caller falls back to the deterministic keyword classifier instead of a
# forced, possibly-wrong guess.
VALID_INTENTS = [
    "greeting", "corrections", "jv", "close", "mapping", "commission",
    "unsettled", "missing_pos", "missing_d365", "settlement_batch",
    "gl_control", "risk", "store_performance", "provider_performance",
    "reconciliation_status", "close_readiness", "management_brief",
    "settlement_intelligence", "commission_intelligence", "refund_intelligence",
    "data_quality", "source_evidence", "copilot_help", "exceptions",
    "date_range", "cash_report", "refunds", "compare", "lookup",
    "transactions", "sales", "summary", "unknown",
]

_INTENT_DESCRIPTIONS = {
    "greeting": "A simple hello/greeting, not a real question.",
    "corrections": "Status of pending correction requests awaiting approval.",
    "jv": "JV/journal voucher readiness, status, or posting progress.",
    "close": "Month-end / period close calendar status.",
    "mapping": "Store, terminal, or merchant mapping exceptions needing setup.",
    "commission": "Commission, fees, VAT, or net-amount deduction questions.",
    "unsettled": "Transactions not yet received/settled in the bank, or settlement delay.",
    "missing_pos": "D365 transactions with no matching POS/provider settlement.",
    "missing_d365": "POS/provider transactions with no matching D365 record.",
    "settlement_batch": "Settlement batch status -- which batches are bank-received, pending, or provider-settled.",
    "gl_control": "GL posting status, GL mismatches/exceptions, unexplained GL, or clearing account movement.",
    "risk": "Biggest/top risks, anomalies, or what needs attention today.",
    "store_performance": "Comparing store performance or control scores.",
    "provider_performance": "Comparing payment provider performance or settlement delay.",
    "reconciliation_status": "Overall matched vs unmatched amount or rate.",
    "close_readiness": "Whether the period/month is ready to close.",
    "management_brief": "A CFO-style finance briefing/summary.",
    "settlement_intelligence": "How much is bank-settled vs awaiting, or the oldest unsettled item.",
    "commission_intelligence": "Commission validation errors or differences (deeper than a plain commission lookup).",
    "refund_intelligence": "Refund totals, ratios, or largest refunds (analytical, not a plain refunds count).",
    "data_quality": "Duplicate files, missing dates, unmapped terminals/merchants, or today's upload data quality.",
    "source_evidence": "Which source file/row a number came from.",
    "copilot_help": "What this assistant can answer / its capabilities.",
    "exceptions": "A general 'what's wrong / unmatched / issues' question.",
    "date_range": "What date range or period is currently in scope for this conversation.",
    "cash_report": "A question specifically and literally about CASH sales/refunds analytics -- choose this ONLY when the question is genuinely about cash, never merely because a prior turn was about cash.",
    "refunds": "A simple refunds question (count/list), not the deeper refund_intelligence analytics.",
    "compare": "Comparing two specific things against each other.",
    "lookup": "Looking up one specific transaction by receipt/auth/authorization number.",
    "transactions": "Requesting transaction-level detail/drill-down, not a summary.",
    "sales": "A general sales/revenue/tender question -- the right default for 'how much did we sell'.",
    "summary": "A generic overview/briefing/dashboard request, or anything that doesn't clearly fit a category above.",
    "unknown": "Doesn't confidently match any category above -- let the deterministic fallback classifier decide instead of guessing.",
}


def _payment_enum():
    # Imported lazily to avoid a hard circular import at module load time;
    # ai_copilot.py imports this module, so this module must not import
    # ai_copilot.py at the top level.
    try:
        from ai_copilot import PAYMENT_ALIASES
        return list(PAYMENT_ALIASES.keys())
    except Exception:
        # Safe, small hardcoded fallback matching ai_copilot.PAYMENT_ALIASES
        # as of this fix -- only used if that import ever fails.
        return ["MADA", "VISA", "MASTERCARD", "AMEX", "TABBY", "TAMARA", "TAP", "CASH", "FLOOSS", "PAYLATER", "DEEMA"]


def is_configured() -> bool:
    """True if an Anthropic API key is available AND the `anthropic`
    package can be imported. Never raises."""
    if not _get_api_key():
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def _get_api_key():
    try:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    try:
        import streamlit as st
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return None


def _build_tool_schema():
    return {
        "name": "extract_finance_query",
        "description": (
            "Classify a finance/reconciliation question into exactly one of a fixed set of "
            "already-implemented report types, and extract which store(s) and payment method "
            "(if any) THIS question itself names. Never compute or estimate any financial figure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": VALID_INTENTS,
                    "description": "The single best-matching report type. Use 'unknown' if none confidently fits.",
                },
                "store_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "3-digit store codes explicitly named or clearly identified by store name in THIS "
                        "question only (use the known store list provided, if any). Empty list if this "
                        "question does not itself name a store -- do NOT carry over a store from earlier "
                        "conversation turns; that is handled separately."
                    ),
                },
                "all_stores_explicit": {
                    "type": "boolean",
                    "description": "True ONLY if this question explicitly asks for ALL stores / every store / every location.",
                },
                "payment_type": {
                    "type": "string",
                    "enum": _payment_enum() + ["NONE"],
                    "description": "The single payment method explicitly named in THIS question, or 'NONE' if this question does not itself name one.",
                },
                "all_payment_types_explicit": {
                    "type": "boolean",
                    "description": "True ONLY if this question explicitly asks to clear/reset the payment filter (e.g. 'all payment types', 'any payment method').",
                },
            },
            "required": ["intent", "store_codes", "all_stores_explicit", "payment_type", "all_payment_types_explicit"],
        },
    }


def _build_system_prompt(store_hint: str) -> str:
    intent_lines = "\n".join(f"- {name}: {desc}" for name, desc in _INTENT_DESCRIPTIONS.items())
    parts = [
        "You are a routing classifier for a retail POS-to-bank reconciliation finance application.",
        "You do not answer the user's question and you must never state, compute, or guess any "
        "financial number, date, or amount -- a separate, exact calculation engine does that. "
        "Your only job is to call the extract_finance_query tool with a structured classification "
        "of the CURRENT question.",
        "",
        "Report types you may choose as `intent` (choose exactly one):",
        intent_lines,
        "",
        "Only extract a store or payment method if THIS question's own text actually names or "
        "clearly implies one -- never infer one from earlier conversation turns; the calling "
        "application handles carrying scope forward across turns on its own.",
    ]
    if store_hint:
        parts += ["", store_hint]
    return "\n".join(parts)


def llm_interpret(
    question: str,
    prior_store_codes=None,
    prior_payment=None,
    prior_last_intent: str = "",
    known_store_names: dict | None = None,
    model: str | None = None,
    timeout: float | None = None,
):
    """
    Returns a dict:
      {
        "intent": one of VALID_INTENTS (including possibly "unknown"),
        "store_codes": [...],                  # this turn's own explicit stores
        "all_stores_explicit": bool,
        "payment_type": one of the payment aliases' keys, or None,
        "all_payment_types_explicit": bool,
      }
    or None if the LLM is unavailable, unconfigured, or anything at all goes
    wrong. Callers MUST treat None as "fall back to the deterministic
    classifier" -- this function is designed to never raise.
    """
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        import anthropic
    except Exception:
        return None

    model = model or os.environ.get("ANTHROPIC_COPILOT_MODEL") or _DEFAULT_MODEL
    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    store_hint = ""
    if known_store_names:
        try:
            lines = [f"{code}: {', '.join(sorted(names))}" for code, names in sorted(known_store_names.items())]
            if lines:
                store_hint = "Known store codes and their names (match by either):\n" + "\n".join(lines[:400])
        except Exception:
            store_hint = ""

    system_prompt = _build_system_prompt(store_hint)
    user_prompt = (
        f"Prior conversation scope (for context ONLY -- do not re-extract these unless THIS "
        f"question repeats them): store_codes={list(prior_store_codes or [])}, "
        f"payment={prior_payment or 'ALL'}, last_report_type={prior_last_intent or 'none'}.\n\n"
        f"Current question: {question!r}"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        resp = client.messages.create(
            model=model,
            max_tokens=_DEFAULT_MAX_TOKENS,
            system=system_prompt,
            tools=[_build_tool_schema()],
            tool_choice={"type": "tool", "name": "extract_finance_query"},
            messages=[{"role": "user", "content": user_prompt}],
        )
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "extract_finance_query":
                return _normalize(block.input)
        return None
    except Exception:
        # Network error, timeout, auth failure, rate limit, malformed
        # response -- any of these silently fall back to the deterministic
        # classifier rather than breaking the user's question.
        return None


def _normalize(data):
    try:
        if not isinstance(data, dict):
            return None
        intent = data.get("intent", "unknown")
        if intent not in VALID_INTENTS:
            intent = "unknown"

        stores = []
        for s in (data.get("store_codes") or []):
            s = str(s).strip()
            if s.endswith(".0"):
                s = s[:-2]
            m = re.search(r"(\d{3})", s)
            if m:
                stores.append(m.group(1))
        stores = sorted(set(stores))

        payment = data.get("payment_type", "NONE")
        if not payment or payment == "NONE" or payment not in _payment_enum():
            payment = None

        return {
            "intent": intent,
            "store_codes": stores,
            "all_stores_explicit": bool(data.get("all_stores_explicit", False)),
            "payment_type": payment,
            "all_payment_types_explicit": bool(data.get("all_payment_types_explicit", False)),
        }
    except Exception:
        return None

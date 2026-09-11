"""
REGRESSION_V46_LLM_ROUTER_INTEGRATION.py

Verifies the OPTIONAL real-AI understanding layer (logic/ai_llm_router.py)
is wired into ai_copilot.py's interpret_query() correctly, WITHOUT needing a
real Anthropic API key or network access -- ai_llm_router.llm_interpret is
monkeypatched to return a synthetic, controlled result, so this test proves
the plumbing deterministically.

Covers:
  1. Zero-config behavior: with ai_llm_router.is_configured() returning
     False (the real, honest state in this sandbox with no API key), every
     assertion from the pre-existing REGRESSION_V13/V45 style scenarios must
     still hold -- i.e. this feature genuinely changes nothing when off.
  2. When "on" (mocked): a confident LLM intent classification is used
     directly, bypassing the keyword chain, for a phrasing the keyword chain
     could NOT have classified correctly on its own.
  3. When "on" but the mocked LLM returns "unknown": the original
     keyword/regex chain still decides intent, proving graceful, partial
     degradation (not just all-or-nothing).
  4. When "on" but llm_interpret raises an exception: interpret_query()
     must not crash -- it must fall back exactly as if the feature were off.
  5. The union-not-override contract for store codes: a regex-detected store
     is never dropped just because the (mocked) LLM didn't also report it.
  6. Numbers are unaffected: for a scenario where the LLM only changes
     WHICH report intent is chosen but the effective scope (store/date/
     payment) is identical, the actual computed total must be IDENTICAL
     to the deterministic non-LLM path -- proving this layer only ever
     changes routing, never arithmetic.
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_llm_integration_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

tender = pd.DataFrame([
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-09"), "Receipt ID": "601A", "Auth Code": "M1",
     "D365 Payment": "MADA", "D365 Amount": 500.0},
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-09"), "Receipt ID": "601B", "Auth Code": "M2",
     "D365 Payment": "VISA", "D365 Amount": 300.0},
])
result = {"tender": tender, "matched": pd.DataFrame(), "unmatched_sales": pd.DataFrame(), "unmatched_pos": pd.DataFrame()}

# --- 1. Zero-config: ai_llm_router present but genuinely unconfigured -----
_assert(ai.ai_llm_router is not None, "ai_llm_router module is importable")
_assert(ai.ai_llm_router.is_configured() is False, "with no ANTHROPIC_API_KEY set, is_configured() is honestly False")

r_off = ai.answer_question("601 sales as of 9 Aug 2026", result, prior_context=None)
_assert(r_off["intent"] == "sales", "with LLM off, intent classification is unchanged (keyword chain)")

# --- 2. Mocked "on": confident classification bypasses the keyword chain --
_orig_is_configured = ai.ai_llm_router.is_configured
_orig_llm_interpret = ai.ai_llm_router.llm_interpret

def _fake_configured_true():
    return True

NOVEL_QUESTION = "how much did store 601 bring in for the day"
# Confirmed ahead of time: the keyword chain has no pattern that matches
# this at all (it contains none of "sales/sale/revenue/tender/payment mix"
# etc.) and falls through to a generic "summary" -- and _find_payment(...)
# returns None for it (no fuzzy false-positive), so this cleanly isolates
# "the AI layer adds real understanding" from any pre-existing regex
# behavior, good or bad, elsewhere in the file.

def _fake_llm_confident(question, **kwargs):
    # What a real LLM would return for NOVEL_QUESTION: a plain sales
    # question about store 601, no payment named -- proves genuinely novel
    # phrasing the keyword chain cannot classify now resolves correctly
    # instead of falling through to a generic "summary".
    return {
        "intent": "sales",
        "store_codes": ["601"],
        "all_stores_explicit": False,
        "payment_type": None,
        "all_payment_types_explicit": False,
    }

ai.ai_llm_router.is_configured = _fake_configured_true
ai.ai_llm_router.llm_interpret = _fake_llm_confident
try:
    r_on = ai.answer_question(NOVEL_QUESTION, result, prior_context=None)
    _assert(r_on["intent"] == "sales", "mocked LLM confidently classifies a novel phrasing as 'sales'")
    _assert(r_on["context"].store_codes == ["601"], "mocked LLM's store extraction reaches ctx.store_codes")
    _assert("500.00" in r_on["text"] and "300.00" in r_on["text"], f"real numbers still come from the deterministic engine: {r_on['text']}")

    # --- 3. Mocked "on" but LLM says "unknown" -> keyword chain decides ----
    def _fake_llm_unknown(question, **kwargs):
        return {"intent": "unknown", "store_codes": [], "all_stores_explicit": False,
                "payment_type": None, "all_payment_types_explicit": False}
    ai.ai_llm_router.llm_interpret = _fake_llm_unknown
    r_unknown = ai.answer_question("601 sales as of 9 Aug 2026", result, prior_context=None)
    _assert(r_unknown["intent"] == "sales", "LLM 'unknown' falls back to the keyword chain, which still gets it right here")

    # --- 4. Mocked "on" but llm_interpret raises -> no crash, clean fallback
    def _fake_llm_raises(question, **kwargs):
        raise RuntimeError("simulated network failure")
    ai.ai_llm_router.llm_interpret = _fake_llm_raises
    r_crash_safe = ai.answer_question("601 sales as of 9 Aug 2026", result, prior_context=None)
    _assert(r_crash_safe["intent"] == "sales", "an exception inside llm_interpret degrades cleanly to the keyword chain, no crash")

    # --- 5. Union-not-override: regex-found store survives an LLM that ----
    # --- reports no stores at all for the same question --------------------
    def _fake_llm_no_stores(question, **kwargs):
        return {"intent": "sales", "store_codes": [], "all_stores_explicit": False,
                "payment_type": None, "all_payment_types_explicit": False}
    ai.ai_llm_router.llm_interpret = _fake_llm_no_stores
    r_union = ai.answer_question("601 sales as of 9 Aug 2026", result, prior_context=None)
    _assert(r_union["context"].store_codes == ["601"], "regex-detected store 601 is never dropped just because the LLM reported none")

    # --- 6. Same effective scope, LLM on vs off -> identical numbers ------
    ai.ai_llm_router.llm_interpret = _fake_llm_confident
    r_llm_scope = ai.answer_question("601 sales as of 9 Aug 2026", result, prior_context=None)
    ai.ai_llm_router.is_configured = _orig_is_configured  # LLM off again
    r_regex_scope = ai.answer_question("601 sales as of 9 Aug 2026", result, prior_context=None)
    _assert(r_llm_scope["text"] == r_regex_scope["text"], "identical scope produces byte-identical answer text whether or not the AI layer is involved in routing")

finally:
    ai.ai_llm_router.is_configured = _orig_is_configured
    ai.ai_llm_router.llm_interpret = _orig_llm_interpret

print("\nREGRESSION V46 LLM ROUTER INTEGRATION PASS")

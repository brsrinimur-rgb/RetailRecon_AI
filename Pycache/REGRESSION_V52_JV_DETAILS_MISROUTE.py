"""
REGRESSION_V52_JV_DETAILS_MISROUTE.py

Same bug class as V51's "i need bank details" fix, this time reported by
the user for JV: "i this JV detail ALOS ADDED" -- asking whether "JV
details" is also covered by the same class of fix.

It was not, until now: "i need jv details" contained the bare substring
"details" and matched the generic "show transactions/details" catch-all
before anything checked for a bare "jv" mention -- so on a follow-up turn
it silently re-ran whatever report was already active (e.g. a TAMARA sales
summary) instead of ever showing JV status, exactly like "bank details" did
before V51.

Fix: a bare, otherwise-unmatched mention of "jv" (not already handled by a
more specific phrase, and NOT also mentioning "gl" -- which belongs to
gl_control's own "jv to gl"/"source to gl" phrases) now routes to the JV
status report instead of falling through to the generic details catch-all.

Covers:
  1. The exact reported shape: a JV-detail follow-up after an unrelated
     report must change the answer, not silently repeat the prior turn.
  2. "jv details" as a fresh, first question also resolves to "jv".
  3. Pre-existing exact JV phrases ("jv status","posting status",...)
     still resolve correctly.
  4. gl_control's own "jv to gl"/"source to gl" phrases are unaffected --
     proving the "gl" guard works.
  5. An unrelated "show details" follow-up (no "jv") is unaffected.
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_v52_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

tender = pd.DataFrame([
    {"Store Code":"603","Store Name":"Aigner Red Sea Mall","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"603A","Auth Code":"B1","D365 Payment":"TAMARA","D365 Amount":300.0},
])
result = {"tender":tender,"matched":pd.DataFrame(),"unmatched_sales":pd.DataFrame(),"unmatched_pos":pd.DataFrame()}

# --- 1. exact reported shape ---------------------------------------------
r1 = ai.answer_question("you can details tamara all stores", result, prior_context=None)
r2 = ai.answer_question("i need jv details", result, prior_context=r1["context"])
_assert(r2["intent"]=="jv", f"'i need jv details' now resolves to jv, got {r2['intent']}")
_assert(r2["text"]!=r1["text"], "the answer must actually change, not silently repeat the prior TAMARA sales summary verbatim")

# --- 2. fresh, first question --------------------------------------------
r3 = ai.answer_question("jv details", result, prior_context=None)
_assert(r3["intent"]=="jv", f"'jv details' as a first question resolves to jv, got {r3['intent']}")

# --- 3. pre-existing exact phrases unaffected -----------------------------
for q,expect in [("jv status","jv"),("journal status","jv"),("ready to post","jv"),("posting status","jv")]:
    intent,_ = ai.interpret_query(q, result, None)
    _assert(intent==expect, f"{q!r} still resolves to {expect}, got {intent}")

# --- 4. gl_control's own jv/gl phrases unaffected -------------------------
intent,_ = ai.interpret_query("jv to gl", result, None)
_assert(intent=="gl_control", f"'jv to gl' still resolves to gl_control, got {intent}")
intent,_ = ai.interpret_query("source to gl", result, None)
_assert(intent=="gl_control", f"'source to gl' still resolves to gl_control, got {intent}")

# --- 5. unrelated details follow-up unaffected ----------------------------
r4 = ai.answer_question("show details", result, prior_context=r1["context"])
_assert(r4["intent"] in {"transactions","sales"}, f"'show details' (no 'jv') still uses the generic catch-all, got {r4['intent']}")

print("\nREGRESSION V52 JV DETAILS MISROUTE PASS")

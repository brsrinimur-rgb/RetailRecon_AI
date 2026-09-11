"""
REGRESSION_V48_DATE_QUESTION_TYPO_FALLBACK.py

Reproduces a real reported bug: after "601 sales", the follow-up "tell me
date whihc date" (a typo'd "tell me date, which date") matched NONE of the
exact date_range phrases ("whihc" breaks "which date"; "tell me date" isn't
"tell date" or "tell me the date"), so it fell through the entire intent
classification chain to the blind final fallback
(intent=prior.last_intent or "summary") and silently re-ran and repeated
the PREVIOUS turn's entire sales answer verbatim, instead of ever answering
the date question.

Fix: two additional regex fallbacks in the date_range branch, anchored to
the end of the question so they only fire when "date(s)" is genuinely the
last real word being asked about.

This test proves the exact reported conversation is fixed, that the
existing exact-phrase cases still work, and that a same-topic sales/other
question is never accidentally rerouted to date_range just because it also
contains a date.
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_date_typo_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

tender = pd.DataFrame([
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-09"), "Receipt ID": "601A", "Auth Code": "M1",
     "D365 Payment": "MADA", "D365 Amount": 500.0},
])
result = {"tender": tender, "matched": pd.DataFrame(), "unmatched_sales": pd.DataFrame(), "unmatched_pos": pd.DataFrame()}

# --- Exact reported conversation --------------------------------------
r1 = ai.answer_question("601 sales", result, prior_context=None)
_assert(r1["intent"] == "sales", "turn 1 classifies as sales")

r2 = ai.answer_question("tell me date whihc date", result, prior_context=r1["context"])
_assert(r2["intent"] == "date_range", f"turn 2 ('tell me date whihc date') now classifies as date_range, got {r2['intent']}")
_assert("500.00" not in r2["text"], "turn 2 no longer silently repeats the previous sales answer")
_assert("09-Aug-2026" in r2["text"], f"turn 2 actually answers the date question: {r2['text']}")

# --- Existing exact-phrase cases must still work unchanged -------------
for q in ["tell date", "tell me the date", "what date", "which date", "whats the date", "what's the date"]:
    intent, _ = ai.interpret_query(q, result, None)
    _assert(intent == "date_range", f"pre-existing exact phrase {q!r} still classifies as date_range")

# --- A same-topic question with its own date must NOT be hijacked ------
intent, _ = ai.interpret_query("603 sales 2 sep 2026", result, None)
_assert(intent == "sales", f"a genuine sales question with a date is never rerouted to date_range, got {intent}")

print("\nREGRESSION V48 DATE QUESTION TYPO FALLBACK PASS")

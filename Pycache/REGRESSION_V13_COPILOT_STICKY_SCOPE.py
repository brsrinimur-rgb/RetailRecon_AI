"""
REGRESSION_V13_COPILOT_STICKY_SCOPE.py

Reproduces the exact broken conversation the user reported against the live
AI Finance Copilot: after one real "cash sales" question, every later,
completely unrelated question ("total sales", "i need mada card", "show top
10 risks", "show settlement status") kept getting rerouted into the cash
report using a stale Store/CASH/date scope from many turns earlier.

Root causes fixed in ai_copilot.py's interpret_query()/answer_question():
  1. The CASH-sticky intent branch fired on ANY of a long list of ordinary
     finance words ("sales","top","highest","details",...) whenever
     ctx.payment happened to be CASH, with no regard for how many turns ago
     that was set or whether the current question has anything to do with
     cash. Now it requires the word "cash" in the CURRENT question.
  2. "need all store cash sales" -- "all store(s)" was not recognized as an
     explicit instruction to clear store scope, so it silently kept
     whatever single store an earlier (often accidentally-misrouted)
     question had pinned.
  3. The blind final fallback ("nothing else matched -> just reuse whatever
     intent the LAST turn resolved to") could reactivate cash_report even
     when the current question named a clearly different payment method
     ("mada"), and the cash_report handler then forced ctx.payment back to
     CASH, discarding the payment the user just typed entirely.
  4. "show top 10 risks" (the app's own "Top 10 risks" quick-question
     button) never matched the "top risk(s)" phrase check because of the
     inserted "10".

Run: python3 REGRESSION_V13_COPILOT_STICKY_SCOPE.py
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_sticky_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

tender = pd.DataFrame([
    {"Store Code": "628", "Date": pd.Timestamp("2026-09-02"), "Receipt ID": "628A", "Auth Code": "",
     "D365 Payment": "CASH", "D365 Amount": 9990.0, "Cash Amount": 9990.0},
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-09"), "Receipt ID": "601A", "Auth Code": "M1",
     "D365 Payment": "MADA", "D365 Amount": 500.0},
    {"Store Code": "603", "Date": pd.Timestamp("2026-09-02"), "Receipt ID": "603A", "Auth Code": "M2",
     "D365 Payment": "MADA", "D365 Amount": 300.0},
])
result = {"tender": tender, "matched": pd.DataFrame(), "unmatched_sales": pd.DataFrame(), "unmatched_pos": pd.DataFrame()}

ctx = None

def ask(q):
    global ctx
    r = ai.answer_question(q, result, prior_context=ctx)
    ctx = r["context"]
    return r

# Turn 1: a real cash question.
r1 = ask("need all store cash sales")
assert r1["intent"] == "cash_report", r1["intent"]
assert ctx.store_codes == [], ctx.store_codes  # "all store" clears scope, not just leaves it at default-empty

# Turn 2: "603 sales 2 sep 2026" -- a plain sales question with no "cash"
# word at all. Must NOT be forced into the cash report just because payment
# is still sticky-CASH from turn 1.
r2 = ask("603 sales 2 sep 2026")
assert r2["intent"] == "sales", r2["intent"]
assert "I couldn't find Cash transactions" not in r2["text"], r2["text"]

# Turn 3: "need all store cash sales" again, this time with a store (603)
# pinned from turn 2 -- "all store(s)" must clear it back to no store filter.
r3 = ask("need all store cash sales")
assert r3["intent"] == "cash_report"
assert ctx.store_codes == [], ctx.store_codes
assert "628" in r3["text"]  # the real highest-cash store, not silently filtered to 603

# Turn 4: an explicit, different payment method after a cash-flavored
# conversation must be honored, not silently discarded back to CASH.
r4 = ask("i need mada card")
assert ctx.payment == "MADA", ctx.payment
assert "I couldn't find Cash transactions" not in r4["text"], r4["text"]

# Turn 5: "show top 10 risks" -- the exact text the app's own "Top 10 risks"
# quick-question button sends -- must classify as risk, not fall through to
# a stale cash/store scope.
r5 = ask("show top 10 risks")
assert r5["intent"] == "risk", r5["intent"]
assert "I couldn't find Cash transactions" not in r5["text"], r5["text"]

# Turn 6: a direct, explicit cash question must still work correctly at any
# point in the conversation -- this fix must not make cash detection worse.
r6 = ask("show me cash sales for store 601")
assert r6["intent"] == "cash_report", r6["intent"]
assert ctx.store_codes == ["601"], ctx.store_codes

print("REGRESSION V13 COPILOT STICKY SCOPE PASS")

from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_routing_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

tender = pd.DataFrame([
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-01"), "Receipt ID": "601A", "Auth Code": "",
     "D365 Payment": "CASH", "D365 Amount": 100.0, "Cash Amount": 100.0, "Cash Classification": "Cash Sales"},
    {"Store Code": "609", "Date": pd.Timestamp("2026-08-03"), "Receipt ID": "609A", "Auth Code": "",
     "D365 Payment": "CASH", "D365 Amount": 400.0, "Cash Amount": 400.0, "Cash Classification": "Cash Sales"},
])
result = {"tender": tender, "matched": pd.DataFrame(), "unmatched_sales": pd.DataFrame(), "unmatched_pos": pd.DataFrame()}

# 1. A cash query must always route to the Advanced Cash Report, not the old
#    single-line tender-total summary, for realistic free-text phrasing.
r1 = ai.answer_question("all stores cash sale", result, prior_context=None)
assert r1["intent"] == "cash_report", r1["intent"]
assert "across" not in r1["text"] or "cash transaction(s)" in r1["text"]  # not the old "X across Y transaction line(s)" wording
assert len(r1["table"]) == 2
assert {"Cash Sales", "Cash Refunds", "Net Cash"}.issubset(r1["table"].columns)

# 2. Even a generic "summary"-classified question must redirect to the Advanced
#    Cash Report when the resolved scope is CASH (covers ambient/background
#    callers - e.g. a fixed "daily briefing" prompt - that pass along a sticky
#    CASH context from a prior turn without literally asking about cash).
briefing_sticky = ai.answer_question("give me a finance summary", result, prior_context=r1["context"])
assert briefing_sticky["intent"] == "summary"
assert "Here is the cash analysis for" in briefing_sticky["text"]
assert "CASH total is" not in briefing_sticky["text"]  # old broken one-liner must never appear

# 3. The SAME fixed prompt with NO sticky context (the corrected Daily Briefing
#    call site) must give a true neutral overview, not a stale cash-only view.
briefing_neutral = ai.answer_question("give me a finance summary", result, prior_context=None)
assert briefing_neutral["context"].payment is None
assert "cash analysis" not in briefing_neutral["text"].lower()

# 4. "tell date" is a follow-up: it must report the current analysis date range,
#    retain the prior Cash/store/date context, and NOT repeat the cash totals.
r2 = ai.answer_question("tell date", result, prior_context=r1["context"])
assert r2["intent"] == "date_range"
assert r2["context"].payment == "CASH"  # context retained
assert "01-Aug-2026 to 03-Aug-2026" in r2["text"]
assert "Cash Sales are" not in r2["text"]  # must not repeat totals
assert "Net Cash" not in r2["text"]

# 5. "tell date" also retains store scope from a prior store-drill-down follow-up.
store_ctx = ai.answer_question("show 609 transaction details", result, prior_context=r1["context"])
r3 = ai.answer_question("what date", result, prior_context=store_ctx["context"])
assert r3["context"].store_codes == ["609"]
assert r3["context"].payment == "CASH"
assert "03-Aug-2026" in r3["text"]

print("AI CASH ROUTING FOLLOW-UP REGRESSION PASS")

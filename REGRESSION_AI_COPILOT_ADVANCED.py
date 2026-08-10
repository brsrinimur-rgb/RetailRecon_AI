from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_advanced_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

tender = pd.DataFrame([
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-01"), "Receipt ID": "601A", "Auth Code": "A1",
     "D365 Payment": "MASTERCARD", "D365 Amount": 100.0},
    {"Store Code": "606", "Date": pd.Timestamp("2026-08-05"), "Receipt ID": "606A", "Auth Code": "A2",
     "D365 Payment": "VISA", "D365 Amount": 200.0},
])
result = {"tender": tender, "matched": pd.DataFrame(), "unmatched_sales": pd.DataFrame(), "unmatched_pos": pd.DataFrame()}

class FakeDB:
    """Minimal stand-in for db.py's load_store_mapping_master(), used to
    prove provider-name resolution works even when a store isn't in the
    confirmed D365_STORE_DISPLAY table."""
    @staticmethod
    def load_store_mapping_master():
        return pd.DataFrame([{"Store Code": "606", "Provider Store Name": "Riyadh Park Branch", "Active": "Yes"}])

# 1. Store-name lookup against the confirmed D365 display names (no db_module needed).
r = ai.answer_question("Aigner Tahlia Mall sales", result)
assert r["context"].store_codes == ["601"], r["context"].store_codes

# 2. Store-name lookup against a provider-mapped name via db_module.
r2 = ai.answer_question("Riyadh Park Branch sales", result, db_module=FakeDB())
assert r2["context"].store_codes == ["606"], r2["context"].store_codes

# 3. A generic word must NOT falsely resolve to a store (no false positives).
r3 = ai.answer_question("mall sales", result)
assert r3["context"].store_codes == [], r3["context"].store_codes

# 4. Typo-tolerant payment matching.
r4 = ai.answer_question("601 mastercart sales", result)
assert r4["context"].payment == "MASTERCARD", r4["context"].payment
r5 = ai.answer_question("606 vise sales", result)
assert r5["context"].payment == "VISA", r5["context"].payment

# 5. Ordinary finance vocabulary must never be mistaken for a payment type.
r6 = ai.answer_question("show settlement details", result)
assert r6["context"].payment is None, r6["context"].payment

# 6. Relative date phrases resolve to real ranges anchored on "today".
today = pd.Timestamp.today().normalize()
_, ctx_mtd = ai.interpret_query("sales mtd", result)
assert ctx_mtd.date_from == today.replace(day=1) and ctx_mtd.date_to == today
_, ctx_ytd = ai.interpret_query("sales ytd", result)
assert ctx_ytd.date_from == today.replace(month=1, day=1)
_, ctx_lastmonth = ai.interpret_query("sales last month", result)
first_this_month = today.replace(day=1)
assert ctx_lastmonth.date_to == first_this_month - pd.Timedelta(days=1)
assert ctx_lastmonth.date_from == ctx_lastmonth.date_to.replace(day=1)

print("AI COPILOT ADVANCED FEATURES REGRESSION PASS")

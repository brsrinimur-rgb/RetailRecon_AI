from pathlib import Path
import importlib.util, sys, os
import pandas as pd

root = Path(__file__).resolve().parent

def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, root / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

auth = load("auth_test_su", "auth.py")
ai = load("ai_test_su", "ai_copilot.py")
db = load("db_test_su", "db.py")

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

# 1. Existing finance roles are untouched.
for u, pw, role in [
    ("admin", "admin123", "Admin"),
    ("finance", "finance123", "Finance Manager"),
    ("maker", "maker123", "Finance Maker"),
    ("checker", "checker123", "Finance Checker"),
]:
    rec = auth.USERS[u]
    assert rec["password"] == pw and rec["role"] == role and "store_codes" not in rec

# 2. New Store User accounts exist, additive, with assigned store_codes.
su601 = auth.USERS["store601"]
assert su601["role"] == "Store User"
assert su601["store_codes"] == ["601"]
su606 = auth.USERS["store606"]
assert su606["store_codes"] == ["606"]

# 3. End-to-end: a real auth.USERS record used as user_context correctly
#    scopes AI Copilot answers to the assigned store only.
tender = pd.DataFrame([
    {"Store Code": "601", "Date": pd.Timestamp("2026-08-01"), "Receipt ID": "601A",
     "Auth Code": "A1", "D365 Payment": "MADA", "D365 Amount": 1000.0},
    {"Store Code": "606", "Date": pd.Timestamp("2026-08-01"), "Receipt ID": "606A",
     "Auth Code": "B1", "D365 Payment": "VISA", "D365 Amount": 2000.0},
])
result = {"tender": tender, "matched": pd.DataFrame(), "unmatched_sales": pd.DataFrame(),
          "unmatched_pos": pd.DataFrame(), "pos": pd.DataFrame()}

user_ctx = {"username": "store601", **su601}
sp = ai.answer_question("show store performance", result, db_module=db, user_context=user_ctx)
assert set(sp["table"]["Store Code"].astype(str)) <= {"601"}

# 4. A Store User's login record carries no db_module bypass: jv/corrections/
#    close intents must not leak cross-store or firm-wide data.
jv_rows = pd.DataFrame([
    {"Journal Batch": "J-601-1", "Journal batch number": "J-601-1", "Line number": 1,
     "Store Code": "601", "Account": "1015", "Debit": 100.0, "Credit": 100.0,
     "Balanced": True, "Validation Passed": True, "Approval Status": "PENDING", "D365 Status": "NOT POSTED", "Voucher": ""},
    {"Journal Batch": "J-606-1", "Journal batch number": "J-606-1", "Line number": 1,
     "Store Code": "606", "Account": "1015", "Debit": 200.0, "Credit": 200.0,
     "Balanced": True, "Validation Passed": True, "Approval Status": "PENDING", "D365 Status": "NOT POSTED", "Voucher": ""},
])
db.replace_jv(jv_rows)

jv_answer = ai.answer_question("jv status", result, db_module=db, user_context=user_ctx)
assert jv_answer["intent"] == "jv"
assert set(jv_answer["table"]["Store Code"].astype(str)) <= {"601"}, "Store User must not see other stores' JV rows"

corr_answer = ai.answer_question("show pending corrections", result, db_module=db, user_context=user_ctx)
assert corr_answer["intent"] == "corrections"
assert corr_answer["table"].empty, "Store User must not receive firm-wide correction log data"

close_answer = ai.answer_question("close status", result, db_module=db, user_context=user_ctx)
assert close_answer["intent"] == "close"
assert close_answer["table"].empty, "Store User must not receive firm-wide close calendar data"

# 5. An unrestricted finance role (no store_codes) is completely unaffected:
#    still sees both stores' JV rows and the correction log normally.
finance_ctx = {"username": "finance", **auth.USERS["finance"]}
jv_finance = ai.answer_question("jv status", result, db_module=db, user_context=finance_ctx)
assert set(jv_finance["table"]["Store Code"].astype(str)) == {"601", "606"}

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)

print("STORE USER ROLE REGRESSION PASS")

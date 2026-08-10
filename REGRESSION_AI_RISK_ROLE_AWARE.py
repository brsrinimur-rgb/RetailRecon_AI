from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
name="ai_risk_role"
spec=importlib.util.spec_from_file_location(name,root/"ai_copilot.py")
ai=importlib.util.module_from_spec(spec)
sys.modules[name]=ai
spec.loader.exec_module(ai)

tender=pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","D365 Payment":"MADA","D365 Amount":1000.0},
    {"Store Code":"603","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"603A","Auth Code":"B1","D365 Payment":"VISA","D365 Amount":2000.0},
])
matched=pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","Payment Type":"MADA","D365 Amount":1000.0,"Net Amount":990.0,"Commission":8.7,"VAT":1.3,"Bank Settled":False,"Posting Date":pd.Timestamp("2026-08-02"),"Settlement Delay Days":1},
    {"Store Code":"603","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"603A","Auth Code":"B1","Payment Type":"VISA","D365 Amount":2000.0,"Net Amount":1960.0,"Commission":34.8,"VAT":5.2,"Bank Settled":True,"Posting Date":pd.Timestamp("2026-08-02"),"Settlement Delay Days":1},
])
us=pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601X","Auth Code":"X1","D365 Payment":"MADA","D365 Amount":500.0,"Reason":"Missing settlement"},
])
up=pd.DataFrame([
    {"POS Store":"603","POS Date":pd.Timestamp("2026-08-02"),"Auth Code":"Y1","POS Payment":"VISA","POS Amount":750.0,"Exception Status":"Missing D365","Reason":"No D365"},
])
result={"tender":tender,"matched":matched,"unmatched_sales":us,"unmatched_pos":up,"pos":pd.DataFrame()}

risk=ai.answer_question("what needs attention?",result)
assert risk["intent"]=="risk"
assert not risk["table"].empty
assert {"Priority","Priority Score","Risk Type","Amount"}.issubset(risk["table"].columns)

sp=ai.answer_question("show store performance",result)
assert sp["intent"]=="store_performance"
assert set(sp["table"]["Store Code"])=={"601","603"}

pp=ai.answer_question("show provider performance",result)
assert pp["intent"]=="provider_performance"
assert not pp["table"].empty

# Optional store-scoped user sees only assigned store.
user={"role":"Store User","store_codes":["601"]}
scoped=ai.answer_question("what needs attention?",result,user_context=user)
assert set(scoped["table"]["Store Code"].astype(str)) <= {"601"}

print("AI RISK + ROLE-AWARE REGRESSION PASS")

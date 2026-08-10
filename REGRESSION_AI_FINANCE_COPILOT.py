from pathlib import Path
import importlib.util
import pandas as pd

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("ai_test",root/"ai_copilot.py")
ai=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

tender=pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"R1","Auth Code":"A1","D365 Payment":"MADA","D365 Amount":100.0},
    {"Store Code":"601","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"R2","Auth Code":"A2","D365 Payment":"VISA","D365 Amount":200.0},
    {"Store Code":"601","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"R3","Auth Code":"","D365 Payment":"CASH","D365 Amount":460.0,"Cash Classification":"Cash Sales","Cash Amount":460.0},
    {"Store Code":"603","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"R4","Auth Code":"B1","D365 Payment":"MADA","D365 Amount":300.0},
])
matched=pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"R1","Auth Code":"A1","Payment Type":"MADA","Sales Amount":100.0,"Commission":1.0,"VAT":0.15,"Net Amount":98.85,"Bank Settled":True},
    {"Store Code":"601","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"R2","Auth Code":"A2","Payment Type":"VISA","Sales Amount":200.0,"Commission":2.0,"VAT":0.30,"Net Amount":197.70,"Bank Settled":False},
])
result={"tender":tender,"matched":matched,"unmatched_sales":pd.DataFrame(),"unmatched_pos":pd.DataFrame()}

# Store/date sales
p=ai.answer_question("601 sales as of 9 Aug 2026",result)
assert p["context"].store_codes==["601"]
assert p["context"].date_to==pd.Timestamp("2026-08-09")
assert "760.00" in p["text"],p["text"]

# Human follow-up context
p2=ai.answer_question("only MADA",result,prior_context=p["context"])
assert p2["context"].store_codes==["601"]
assert p2["context"].payment=="MADA"
assert "100.00" in p2["text"],p2["text"]

p3=ai.answer_question("which are not settled?",result,prior_context=p2["context"])
assert p3["intent"]=="unsettled"
assert len(p3["table"])==0  # Store 601 MADA is settled.

# Change payment in follow-up
p4=ai.answer_question("VISA",result,prior_context=p["context"])
p5=ai.answer_question("which are not settled?",result,prior_context=p4["context"])
assert len(p5["table"])==1
assert p5["table"].iloc[0]["Auth Code"]=="A2"

# Compare stores
pc=ai.answer_question("compare 601 and 603 sales on 9 Aug 2026",result)
assert len(pc["table"])==2

# Receipt/auth lookup
pl=ai.answer_question("find receipt R2",result)
assert not pl["table"].empty

print("AI FINANCE COPILOT REGRESSION PASS")

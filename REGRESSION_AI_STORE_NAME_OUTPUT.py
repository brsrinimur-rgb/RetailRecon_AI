from pathlib import Path
import importlib.util,sys,pandas as pd
root=Path(__file__).resolve().parent
if str(root) not in sys.path: sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location("ai_store_name",root/"ai_copilot.py"); ai=importlib.util.module_from_spec(spec); sys.modules["ai_store_name"]=ai; spec.loader.exec_module(ai)
class FakeDB:
 @staticmethod
 def load_store_mapping_master(): return pd.DataFrame([{"Store Code":"641","Provider Store Name":"TEST STORE NAME","Active":"Yes"}])
tender=pd.DataFrame([{"Store Code":"641","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"R641","Auth Code":"A641","D365 Payment":"VISA","D365 Amount":6398.0}])
result={"tender":tender,"matched":pd.DataFrame(),"unmatched_sales":pd.DataFrame(),"unmatched_pos":pd.DataFrame()}
r=ai.answer_question("641 sales",result,db_module=FakeDB())
assert "TEST STORE NAME" in r["text"],r["text"]
assert r["table"].iloc[0]["Store Name"]=="TEST STORE NAME"
assert float(r["table"].iloc[0]["Amount"])==6398.0
r2=ai.answer_question("show transaction details",result,db_module=FakeDB(),prior_context=r["context"])
assert r2["table"].iloc[0]["Store Name"]=="TEST STORE NAME"
print("AI STORE NAME OUTPUT REGRESSION PASS")

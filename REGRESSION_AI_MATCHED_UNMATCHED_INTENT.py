from pathlib import Path
import importlib.util,sys,pandas as pd
root=Path(__file__).resolve().parent;sys.path.insert(0,str(root))
s=importlib.util.spec_from_file_location("ai_mu",root/"ai_copilot.py");ai=importlib.util.module_from_spec(s);sys.modules["ai_mu"]=ai;s.loader.exec_module(ai)
class DB:
 @staticmethod
 def load_store_mapping_master():return pd.DataFrame([{"Store Code":"601","Provider Store Name":"Aigner Tahlia","Active":"Yes"}])
data={"tender":pd.DataFrame(),"matched":pd.DataFrame([{"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Payment Type":"MADA","D365 Amount":800}]),"unmatched_sales":pd.DataFrame([{"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"D365 Payment":"MADA","D365 Amount":200}]),"unmatched_pos":pd.DataFrame([{"POS Store":"601","POS Date":pd.Timestamp("2026-08-01"),"POS Payment":"MADA","POS Amount":50}])}
r=ai.answer_question("pls store 601 how much matched and unmatched",data,db_module=DB())
assert r["intent"]=="reconciliation_status",r["intent"]
assert "Aigner Tahlia" in r["text"]
assert "SAR 800.00" in r["text"] and "SAR 200.00" in r["text"] and "SAR 50.00" in r["text"]
print("MATCHED/UNMATCHED INTENT PASS")

from pathlib import Path
import importlib.util,sys,pandas as pd
root=Path(__file__).resolve().parent;sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("ai_v12",root/"ai_copilot.py");ai=importlib.util.module_from_spec(sp);sys.modules["ai_v12"]=ai;sp.loader.exec_module(ai)
class DB:
 @staticmethod
 def load_store_mapping_master():return pd.DataFrame([{"Store Code":"601","Provider Store Name":"Aigner Tahlia","Active":"Yes"}])
 @staticmethod
 def load_corrections():return pd.DataFrame([{"Status":"PENDING"}])
 @staticmethod
 def load_jv_batches():return pd.DataFrame([{"Store Code":"601","D365 Status":"POSTED"},{"Store Code":"601","D365 Status":"READY"}])
result={
"tender":pd.DataFrame([{"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"R1","Auth Code":"A1","D365 Payment":"MADA","D365 Amount":1000},{"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"R2","Auth Code":"C1","D365 Payment":"CASH","D365 Amount":-100}]),
"matched":pd.DataFrame([{"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Auth Code":"A1","Payment Type":"MADA","D365 Amount":800,"Net Amount":790,"Commission":8.7,"VAT":1.3,"Bank Settled":False,"Settlement Delay Days":2}]),
"unmatched_sales":pd.DataFrame([{"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Auth Code":"X1","D365 Payment":"MADA","D365 Amount":200}]),
"unmatched_pos":pd.DataFrame([{"POS Store":"601","POS Date":pd.Timestamp("2026-08-01"),"Auth Code":"Y1","POS Payment":"MADA","POS Amount":50}]),
"pos":pd.DataFrame([{"POS Store":"601","POS Date":pd.Timestamp("2026-08-01"),"Auth Code":"Y1","POS Payment":"MADA","POS Amount":50,"Terminal ID":"","Merchant ID":""}])
}
tests={"settlement status":"settlement_intelligence","show refunds":"refund_intelligence","check data quality":"data_quality","can I close the period?":"close_readiness","give me a finance briefing":"management_brief","show source files":"source_evidence","what can you answer":"copilot_help"}
for q,intent in tests.items():
 r=ai.answer_question(q,result,db_module=DB());assert r["intent"]==intent,(q,r["intent"])
assert "NOT READY" in ai.answer_question("can I close the period?",result,db_module=DB())["text"]
print("FINANCE CONTROL V12 PASS")

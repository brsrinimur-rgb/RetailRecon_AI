
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from logic.pos_gl_reconciliation import reconcile_pos_to_gl
p=pd.DataFrame([{"merchant_id":"M123","store_code":"601","provider":"TABBY","reference":"TX100","auth_code":"","pos_date":pd.Timestamp("2026-08-01"),"pos_amount":100.0,"source_row":2,"source_file":"p"}])
g=pd.DataFrame([{"merchant_id":"M123","store_code":"601","provider":"TABBY","reference":"TX100","auth_code":"","gl_date":pd.Timestamp("2026-08-01"),"gl_amount":100.0,"main_account":"1102","voucher":"V1","journal":"J1","source_row":2,"source_file":"g"}])
r=reconcile_pos_to_gl(p,g,.50); assert r["detail"].iloc[0].Status=="GL MATCHED"; print("[PASS] POS amount = GL amount")
g["gl_amount"]=100.40; r=reconcile_pos_to_gl(p,g,.50); assert r["detail"].iloc[0].Status=="GL MATCHED"; print("[PASS] tolerance")
g["gl_amount"]=99.0; r=reconcile_pos_to_gl(p,g,.50); assert r["detail"].iloc[0].Status=="GL AMOUNT EXCEPTION"; print("[PASS] amount exception")
g["gl_amount"]=float("nan"); r=reconcile_pos_to_gl(p,g,.50); assert r["detail"].iloc[0].Status=="GL NOT POSTED"; print("[PASS] missing GL")
g=pd.concat([g.assign(gl_amount=100.0),g.assign(gl_amount=100.0)],ignore_index=True); r=reconcile_pos_to_gl(p,g,.50); assert r["detail"].iloc[0].Status=="GL REVIEW REQUIRED"; print("[PASS] multiple candidates")
print("REGRESSION V47 POS TO GL RECON PASS")

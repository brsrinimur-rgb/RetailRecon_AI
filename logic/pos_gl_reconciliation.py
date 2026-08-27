
from __future__ import annotations
import re, pandas as pd

def norm(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return ""
    return re.sub(r"\s+"," ",str(v).strip()).upper()

def col(df,names):
    m={norm(c).replace("_"," "):c for c in df.columns}
    for n in names:
        if norm(n).replace("_"," ") in m: return m[norm(n).replace("_"," ")]
    return None

def normalize_pos(df,source_file=""):
    names={"merchant_id":["Merchant ID","MerchantID"],"store_code":["Store Code","Store","Store ID","POS Store"],
    "provider":["Provider","Payment Provider","Payment Type","POS Payment"],"reference":["Transaction ID","Unique Transaction ID","Reference","Receipt ID","Order ID"],
    "auth_code":["Auth Code","Authorization Code","Approval Code"],"pos_date":["POS Date","Date","Transaction Date","Business Date"],
    "pos_amount":["POS Amount","Amount","Transaction Amount","Gross Amount"]}
    o=pd.DataFrame(index=df.index)
    for k,v in names.items():
        c=col(df,v); o[k]=df[c] if c else ""
    o["source_file"]=source_file; o["source_row"]=range(2,len(o)+2)
    o["pos_amount"]=pd.to_numeric(o["pos_amount"],errors="coerce"); o["pos_date"]=pd.to_datetime(o["pos_date"],errors="coerce")
    for c in ["merchant_id","store_code","provider","reference","auth_code"]: o[c]=o[c].map(norm)
    return o

def normalize_gl(df,source_file=""):
    names={"merchant_id":["Merchant ID","MerchantID"],"store_code":["Store Code","Store","Store ID"],
    "provider":["Provider","Payment Provider","Payment Type"],"reference":["Transaction ID","Unique Transaction ID","Reference","Receipt ID","Sales Order"],
    "auth_code":["Auth Code","Authorization Code"],"gl_date":["GL Date","Date","Posting Date"],
    "gl_amount":["Actual GL Amount","GL Amount","Signed Amount","Absolute Amount","Amount"],
    "main_account":["Main Account","Ledger Account"],"voucher":["Voucher"],"journal":["Journal Number","GL Journal Number"]}
    o=pd.DataFrame(index=df.index)
    for k,v in names.items():
        c=col(df,v); o[k]=df[c] if c else ""
    o["source_file"]=source_file; o["source_row"]=range(2,len(o)+2)
    o["gl_amount"]=pd.to_numeric(o["gl_amount"],errors="coerce"); o["gl_date"]=pd.to_datetime(o["gl_date"],errors="coerce")
    for c in ["merchant_id","store_code","provider","reference","auth_code","main_account","voucher","journal"]: o[c]=o[c].map(norm)
    return o

def reconcile_pos_to_gl(pos,gl,tolerance=0.50):
    pos=pos.reset_index(drop=True); gl=gl.reset_index(drop=True)
    used=set(); rows=[]
    for _,p in pos.iterrows():
        pool=gl.loc[~gl.index.isin(used)].copy()
        # Identity first. Merchant ID is strongest, then reference/auth/store/provider/date.
        filters=[]
        for field in ["merchant_id","reference","auth_code","store_code","provider"]:
            val=p[field]
            if val:
                x=pool[pool[field].eq(val)]
                if not x.empty: pool=x; filters.append(field.replace("_"," ").title())
        if pd.notna(p["pos_date"]):
            x=pool[pd.to_datetime(pool["gl_date"],errors="coerce").dt.normalize()==p["pos_date"].normalize()]
            if not x.empty: pool=x; filters.append("Date")
        # Never use amount to choose the GL row.
        if len(pool)==1 and filters:
            g=pool.iloc[0]; used.add(g.name)
            pa=pd.to_numeric(pd.Series([p["pos_amount"]]),errors="coerce").iloc[0]
            ga=pd.to_numeric(pd.Series([g["gl_amount"]]),errors="coerce").iloc[0]
            if pd.isna(pa): status="POS DATA INCOMPLETE"
            elif pd.isna(ga): status="GL NOT POSTED"
            elif abs(float(pa)-float(ga))<=tolerance: status="GL MATCHED"
            else: status="GL AMOUNT EXCEPTION"
            reason=("POS Statement Amount equals D365 GL Amount within tolerance." if status=="GL MATCHED"
                    else "POS Statement Amount does not equal D365 GL Amount within tolerance." if status=="GL AMOUNT EXCEPTION"
                    else "GL evidence row identified but GL amount is blank." if status=="GL NOT POSTED"
                    else "POS statement amount is blank/non-numeric.")
            rows.append({"POS Row":p["source_row"],"Merchant ID":p["merchant_id"],"Store Code":p["store_code"],
            "Provider":p["provider"],"POS Reference":p["reference"],"POS Date":p["pos_date"],"POS Amount":p["pos_amount"],
            "GL Row":g["source_row"],"GL Main Account":g["main_account"],"GL Voucher":g["voucher"],"GL Journal":g["journal"],
            "GL Date":g["gl_date"],"GL Amount":ga,"Difference":float(pa-ga) if pd.notna(pa) and pd.notna(ga) else float("nan"),
            "Status":status,"Match Rule":" + ".join(filters),"Reason":reason,"GL Source File":g["source_file"]})
        elif pool.empty:
            rows.append({"POS Row":p["source_row"],"Merchant ID":p["merchant_id"],"Store Code":p["store_code"],"Provider":p["provider"],
            "POS Reference":p["reference"],"POS Date":p["pos_date"],"POS Amount":p["pos_amount"],"GL Row":"","GL Main Account":"",
            "GL Voucher":"","GL Journal":"","GL Date":pd.NaT,"GL Amount":float("nan"),"Difference":float("nan"),
            "Status":"IDENTIFIER MISMATCH","Match Rule":"","Reason":"No GL evidence matched the available identifiers.","GL Source File":""})
        else:
            rows.append({"POS Row":p["source_row"],"Merchant ID":p["merchant_id"],"Store Code":p["store_code"],"Provider":p["provider"],
            "POS Reference":p["reference"],"POS Date":p["pos_date"],"POS Amount":p["pos_amount"],"GL Row":"","GL Main Account":"",
            "GL Voucher":"","GL Journal":"","GL Date":pd.NaT,"GL Amount":float("nan"),"Difference":float("nan"),
            "Status":"GL REVIEW REQUIRED","Match Rule":" + ".join(filters),
            "Reason":"Multiple GL candidates; no deterministic evidence selected.","GL Source File":""})
    d=pd.DataFrame(rows); matched=d[d.Status=="GL MATCHED"].copy(); exc=d[d.Status!="GL MATCHED"].copy()
    summary=pd.DataFrame([{"POS Rows":len(pos),"GL Rows":len(gl),"GL Matched":len(matched),
    "GL Amount Exceptions":int((d.Status=="GL AMOUNT EXCEPTION").sum()),"GL Not Posted":int((d.Status=="GL NOT POSTED").sum()),
    "Review Required":int((d.Status=="GL REVIEW REQUIRED").sum()),"Identifier Mismatch":int((d.Status=="IDENTIFIER MISMATCH").sum()),
    "POS Data Incomplete":int((d.Status=="POS DATA INCOMPLETE").sum()),"Unmatched GL Rows":len(gl)-len(used),
    "Tolerance SAR":tolerance,"Overall Status":"RECONCILED" if exc.empty else "EXCEPTIONS REQUIRE REVIEW"}])
    return {"detail":d,"matched":matched,"exceptions":exc,"unmatched_gl":gl.loc[~gl.index.isin(used)].copy(),"summary":summary}

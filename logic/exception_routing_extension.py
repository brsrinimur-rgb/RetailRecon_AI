
from __future__ import annotations
import pandas as pd
import numpy as np
import re

def _txt(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return ""
    return str(v).strip()

def _auth(v):
    return re.sub(r"[^0-9A-Za-z]","",_txt(v)).upper()

def _norm_payment(v):
    s=_txt(v).upper().replace(" ","")
    if s in {"MADA","P","P1"}: return "MADA"
    if s in {"VISA","VC","VISACARD"}: return "VISA"
    if s in {"MASTER","MC","MASTERCARD"}: return "MASTERCARD"
    if s in {"AMEX","AX"}: return "AMEX"
    if s in {"TABBY","TAMARA","TAP"}: return s
    return _txt(v).upper()

def _pick_col(df,names):
    norm={str(c).strip().lower():c for c in df.columns}
    for n in names:
        if n.lower() in norm:return norm[n.lower()]
    return None

def route_auth_correction_candidates(unmatched_sales, unmatched_pos, sales_details=None, tolerance=1.0):
    if unmatched_sales is None or unmatched_sales.empty:
        return pd.DataFrame()
    u=unmatched_sales.copy()
    p=unmatched_pos.copy() if unmatched_pos is not None else pd.DataFrame()
    sd=sales_details.copy() if sales_details is not None else pd.DataFrame()
    routed=[]

    for _,r in u.iterrows():
        reason=_txt(r.get("Reason")).lower()
        current=_auth(r.get("Auth Code"))
        if "duplicate" in reason:
            continue

        suggested=evidence=source=confidence=""
        amt_diff=np.nan
        store=_txt(r.get("Store Code"))
        so=_txt(r.get("Sales Order"))

        if so and not sd.empty and {"Store Code","Sales Order","Auth Code"}.issubset(sd.columns):
            sdc=sd[
                sd["Store Code"].astype(str).str.strip().eq(store)
                & sd["Sales Order"].astype(str).str.strip().eq(so)
            ]
            auths=sorted({_auth(x) for x in sdc["Auth Code"] if _auth(x)})
            if len(auths)==1 and auths[0]!=current:
                suggested=auths[0]
                evidence=f"SalesDetails exact Store + Sales Order {so}"
                source="SalesDetails"
                confidence="DETERMINISTIC"

        if not suggested and not p.empty:
            pc=p.copy()
            store_col=_pick_col(pc,["POS Store","Store Code","Store"])
            pay_col=_pick_col(pc,["POS Payment","Payment Type","payment_scheme"])
            amt_col=_pick_col(pc,["POS Amount","Amount","Transaction Amount"])
            date_col=_pick_col(pc,["POS Date","Transaction Date","Date"])
            auth_col=_pick_col(pc,["Auth Code","POS Auth Code","authorization_id","reference_order"])

            if store_col:
                pc=pc[pc[store_col].astype(str).str.strip().eq(store)]
            d365_pay=_norm_payment(r.get("D365 Payment",r.get("Payment Type","")))
            if pay_col and d365_pay:
                pc=pc[pc[pay_col].apply(_norm_payment).eq(d365_pay)]
            d365_amt=pd.to_numeric(pd.Series([r.get("D365 Amount",np.nan)]),errors="coerce").iloc[0]
            if amt_col and pd.notna(d365_amt):
                pc["_Amt"]=pd.to_numeric(pc[amt_col],errors="coerce")
                pc["_Diff"]=(pc["_Amt"]-float(d365_amt)).abs()
                pc=pc[pc["_Diff"]<=float(tolerance)]
            d365_date=pd.to_datetime(r.get("Date"),errors="coerce")
            if date_col and pd.notna(d365_date):
                pdte=pd.to_datetime(pc[date_col],errors="coerce")
                daydiff=(pdte.dt.normalize()-d365_date.normalize()).dt.days.abs()
                pc=pc[daydiff<=2]
            if auth_col and len(pc)==1:
                ca=_auth(pc.iloc[0][auth_col])
                if ca and ca!=current:
                    suggested=ca
                    evidence="Unique POS/provider candidate: Store + Payment + Amount + Date"
                    source=_txt(pc.iloc[0].get("Source File","POS/Provider"))
                    confidence="HIGH"
                    if "_Diff" in pc.columns: amt_diff=float(pc.iloc[0]["_Diff"])

        if suggested and suggested!=current:
            rr=r.to_dict()
            rr["Suggested Auth Code"]=suggested
            rr["Correction Evidence"]=evidence
            rr["Evidence Source"]=source
            rr["Correction Confidence"]=confidence
            rr["Candidate Amount Difference"]=amt_diff
            rr["Correction Routing Status"]="AUTH CORRECTION CANDIDATE"
            routed.append(rr)
    return pd.DataFrame(routed)

def unresolved_non_auth_exceptions(unmatched_sales, auth_candidates):
    if unmatched_sales is None or unmatched_sales.empty:
        return pd.DataFrame()
    u=unmatched_sales.copy()
    if auth_candidates is None or auth_candidates.empty or "D365 Row" not in u.columns:
        u["Correction Routing Status"]="RECONCILIATION EXCEPTION - NOT AUTH CORRECTION"
        return u
    ids=set(pd.to_numeric(auth_candidates["D365 Row"],errors="coerce").dropna().astype(int))
    mask=~pd.to_numeric(u["D365 Row"],errors="coerce").fillna(-1).astype(int).isin(ids)
    out=u[mask].copy()
    out["Correction Routing Status"]="RECONCILIATION EXCEPTION - NOT AUTH CORRECTION"
    return out

def engine_health():
    return {"module":"exception_routing_extension","legacy_preserved":True,"extension_mode":"strict manual-correction routing"}

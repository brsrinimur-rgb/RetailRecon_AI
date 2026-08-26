
from __future__ import annotations
import pandas as pd
import core

def _num(v):
    x=pd.to_numeric(pd.Series([v]),errors="coerce").iloc[0]
    return float(x) if pd.notna(x) else None

def _build_gl_evidence(tender, gl, tolerance):
    """Find one GL evidence row using identity/account/date first; amount is
    deliberately NOT part of candidate selection. Amount is tested afterward
    as the POS->GL accounting control."""
    if gl is None or gl.empty:
        return pd.DataFrame(), pd.DataFrame()

    g=gl[gl["Controlled Clearing Account"].fillna(False)].copy()
    used=set()
    rows=[]

    for _,s in tender.reset_index(drop=True).iterrows():
        store=str(s.get("Store Code","")).strip()
        pay=core._norm_payment(s.get("D365 Payment",""))
        so=str(s.get("Sales Order","")).strip().upper()
        src_date=pd.to_datetime(s.get("Date"),errors="coerce")
        expected=core._gl_expected_account_for_tender(pay,store)

        pool=g[~g.index.isin(used)].copy()
        # Cash has no provider clearing account. For cash control, identify
        # the GL evidence by Store + Date and compare the amount afterward.
        if pay != "CASH" and expected:
            pool=pool[pool["Main Account"].isin(expected)].copy()
        if store:
            store_pool=pool[pool["Store Code"].astype(str).str.strip().eq(store)].copy()
        else:
            store_pool=pool

        sel=None; status="GL NOT FOUND"; rule=""; reason=""

        # Store 613: Sales Order is the strongest identity evidence.
        if store=="613" and so:
            x=pool[pool["Sales Order"].astype(str).str.upper().eq(so)].copy()
            if len(x)==1:
                sel=x.iloc[0]
                rule="Store 613 Sales Order"
            elif len(x)>1:
                if pd.notna(src_date):
                    xd=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.normalize()==src_date.normalize()]
                    if len(xd)==1:
                        sel=xd.iloc[0]; rule="Store 613 Sales Order + Date"
                    else:
                        reason="Multiple GL candidates for Sales Order"
                else:
                    reason="Multiple GL candidates for Sales Order"

        # Other stores: identity = store + expected clearing account + date.
        if sel is None and not store_pool.empty:
            x=store_pool.copy()
            if pd.notna(src_date):
                xd=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.normalize()==src_date.normalize()].copy()
            else:
                xd=pd.DataFrame()

            if len(xd)==1:
                sel=xd.iloc[0]
                rule="Store + Clearing Account + Date"
            elif len(xd)>1:
                # Unique source-level identity can disambiguate by Auth Code or
                # Sales Order when those fields are populated in the GL export.
                for key, sval in [
                    ("Sales Order",so),
                    ("Auth Code",str(s.get("Auth Code","")).strip().upper()),
                ]:
                    if sval and key in xd.columns:
                        xx=xd[xd[key].astype(str).str.strip().str.upper().eq(sval)]
                        if len(xx)==1:
                            sel=xx.iloc[0]
                            rule=f"Store + Clearing Account + Date + {key}"
                            break
                if sel is None:
                    reason="Multiple GL candidates for Store + Clearing Account + Date"
            elif pd.notna(src_date):
                # Period-only is never promoted to deterministic evidence.
                xp=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.to_period("M")==src_date.to_period("M")]
                if len(xp)==1:
                    sel=xp.iloc[0]
                    rule="Store + Clearing Account + Period"
                    status="GL REVIEW REQUIRED"
                    reason="Date differs; unique same-period GL candidate"
                elif len(xp)>1:
                    reason="Multiple same-period GL candidates"

        rec={
            "_ROW_ID":str(len(rows)),
            "GL Trace Status":status,
            "GL Trace Rule":rule,
            "GL Trace Reason":reason,
            "GL Journal Number":"",
            "GL Voucher":"",
            "GL Date":pd.NaT,
            "Actual Main Account":"",
            "Actual Ledger Account":"",
            "Actual GL Amount":float("nan"),
            "GL Description":"",
            "GL Source File":"",
            "GL Fingerprint":"",
        }
        if sel is not None:
            used.add(sel.name)
            actual=float(pd.to_numeric(pd.Series([sel.get("Absolute Amount")]),errors="coerce").fillna(float("nan")).iloc[0])
            rec.update({
                "GL Trace Status":"GL EVIDENCE FOUND" if abs(actual-_num(s.get("D365 Amount")) or 0)>float(tolerance) else "GL MATCHED",
                "GL Journal Number":sel.get("Journal Number",""),
                "GL Voucher":sel.get("Voucher",""),
                "GL Date":sel.get("GL Date",pd.NaT),
                "Actual Main Account":sel.get("Main Account",""),
                "Actual Ledger Account":sel.get("Ledger Account",""),
                "Actual GL Amount":sel.get("Absolute Amount",float("nan")),
                "GL Description":sel.get("Description",""),
                "GL Source File":sel.get("Source File",""),
                "GL Fingerprint":sel.get("GL Fingerprint",""),
            })
        rows.append(rec)

    return pd.DataFrame(rows), g[~g.index.isin(used)].copy()

def run_three_way(tender,pos,gl,tolerance=1.0):
    """
    Store Tender -> POS -> GL.

    GL accounting authority is POS Statement Amount -> D365 GL Amount.
    The GL evidence row is identified independently; amount is compared only
    after the row is identified. No settlement/JV state is modified.
    """
    tender=tender.copy() if tender is not None else pd.DataFrame()
    pos=pos.copy() if pos is not None else pd.DataFrame()
    gl=gl.copy() if gl is not None else pd.DataFrame()

    if tender.empty:
        return {"detail":pd.DataFrame(),
                "summary":pd.DataFrame([{"Overall Status":"NO STORE TENDER DATA"}]),
                "pos_matched":pd.DataFrame(),"pos_unmatched_tender":pd.DataFrame(),
                "pos_unmatched_provider":pos,"gl_trace":pd.DataFrame(),
                "gl_untraced":gl,"exceptions":pd.DataFrame()}

    tender=tender.reset_index(drop=True)
    noncash=tender[tender["D365 Payment"].astype(str).str.upper().ne("CASH")].copy()

    pos_match,pos_unmatched_tender,pos_unmatched_provider=core.reconcile(
        noncash,pos,tolerance
    )
    gl_trace,gl_untraced=_build_gl_evidence(tender,gl,tolerance)

    p=pos_match.copy()
    if not p.empty:
        p=p.rename(columns={"Difference":"Tender-POS Difference","Status":"POS Status",
                            "Match Rule":"POS Match Rule","Source File":"POS Source File"})
        p=p[[c for c in ["Unique Transaction ID","POS Amount","Tender-POS Difference",
                         "POS Status","POS Match Rule","POS Date","Posting Date",
                         "Terminal ID","POS Source File"] if c in p.columns]]
    else:
        p=pd.DataFrame(columns=["Unique Transaction ID","POS Amount"])

    detail=tender.merge(p,on="Unique Transaction ID",how="left",suffixes=("","_POS"))
    gl_trace["_ROW_ID"]=gl_trace["_ROW_ID"].astype(str)
    detail["_ROW_ID"]=[str(i) for i in range(len(detail))]
    detail=detail.merge(gl_trace,on="_ROW_ID",how="left",suffixes=("","_GL"))

    detail["POS-GL Amount Difference"]=(pd.to_numeric(detail.get("POS Amount"),errors="coerce")-
                                        pd.to_numeric(detail.get("Actual GL Amount"),errors="coerce"))

    def gl_status(r):
        pa=_num(r.get("POS Amount")); ga=_num(r.get("Actual GL Amount"))
        if pa is None: return "GL BLOCKED - POS NOT MATCHED"
        if ga is None: return "GL NOT POSTED"
        return "GL AMOUNT MATCHED" if abs(pa-ga)<=float(tolerance) else "GL AMOUNT EXCEPTION"
    detail["GL Amount Status"]=detail.apply(gl_status,axis=1)

    def classify(r):
        payment=str(r.get("D365 Payment","")).upper()
        if payment=="CASH":
            return "CASH / GL AMOUNT CONTROL" if r["GL Amount Status"]=="GL AMOUNT MATCHED" else (
                "CASH / GL NOT POSTED" if r["GL Amount Status"]=="GL NOT POSTED" else
                "CASH / GL AMOUNT EXCEPTION")
        if str(r.get("POS Status",""))=="Matched" and r["GL Amount Status"]=="GL AMOUNT MATCHED":
            return "THREE-WAY RECONCILED"
        if str(r.get("POS Status",""))=="Matched" and r["GL Amount Status"]=="GL AMOUNT EXCEPTION":
            return "POS RECONCILED / GL AMOUNT EXCEPTION"
        if str(r.get("POS Status",""))=="Matched" and r["GL Amount Status"]=="GL NOT POSTED":
            return "POS RECONCILED / GL NOT POSTED"
        if str(r.get("POS Status",""))=="Matched":
            return "POS RECONCILED / GL CONTROL PENDING"
        return "STORE TENDER / POS EXCEPTION"
    detail["Three-Way Status"]=detail.apply(classify,axis=1)

    def reason(r):
        s=r["Three-Way Status"]
        if s=="THREE-WAY RECONCILED": return "Store Tender→POS matched and POS Statement Amount→GL Amount matched."
        if s=="POS RECONCILED / GL AMOUNT EXCEPTION": return "POS matched, but POS Statement Amount does not equal D365 GL Amount within tolerance."
        if s=="POS RECONCILED / GL NOT POSTED": return "POS matched, but no corresponding GL amount was found."
        if s=="STORE TENDER / POS EXCEPTION": return "Store Tender→POS deterministic match requires review."
        if s=="CASH / GL AMOUNT CONTROL": return "Cash controlled directly by Store Tender→GL Amount; POS is not required."
        if s=="CASH / GL NOT POSTED": return "Cash Store Tender exists but no corresponding GL amount was found."
        return "Cash GL amount exception or GL control pending."
    detail["Control Reason"]=detail.apply(reason,axis=1)

    counts=detail["Three-Way Status"].value_counts()
    total=len(detail); rec=int(counts.get("THREE-WAY RECONCILED",0))
    cash=int(counts.get("CASH / GL AMOUNT CONTROL",0))
    exc=total-rec-cash
    summary=pd.DataFrame([{
        "Overall Status":"RECONCILED" if exc==0 else "EXCEPTIONS REQUIRE REVIEW",
        "Store Tender Transactions":total,"Three-Way Reconciled":rec,
        "Cash / GL Amount Control":cash,"Exceptions":exc,
        "POS Matched":int((detail.get("POS Status",pd.Series(dtype=str))=="Matched").sum()),
        "POS-GL Amount Matched":int((detail["GL Amount Status"]=="GL AMOUNT MATCHED").sum()),
        "POS-GL Amount Exceptions":int((detail["GL Amount Status"]=="GL AMOUNT EXCEPTION").sum()),
        "GL Not Posted":int((detail["GL Amount Status"]=="GL NOT POSTED").sum()),
        "Unmatched POS Rows":len(pos_unmatched_provider),"Untraced GL Rows":len(gl_untraced),
        "Tolerance SAR":float(tolerance)}])
    exceptions=detail[~detail["Three-Way Status"].isin(
        ["THREE-WAY RECONCILED","CASH / GL AMOUNT CONTROL"])].copy()
    return {"detail":detail.drop(columns=["_ROW_ID"],errors="ignore"),"summary":summary,
            "pos_matched":p,"pos_unmatched_tender":pos_unmatched_tender,
            "pos_unmatched_provider":pos_unmatched_provider,"gl_trace":gl_trace,
            "gl_untraced":gl_untraced,"exceptions":exceptions}

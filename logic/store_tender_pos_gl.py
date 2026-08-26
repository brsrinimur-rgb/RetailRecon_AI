
from __future__ import annotations
import pandas as pd
import core

def run_three_way(tender, pos, gl, tolerance=1.0):
    """
    Deterministic Store Tender -> POS -> GL control.

    The existing deterministic engines remain authoritative:
      core.reconcile() for Store Tender -> POS
      core.trace_d365_source_to_gl() for Store Tender -> D365 GL

    This module only combines their results. It does not change settlement,
    bank receipt, JV eligibility, JV creation, approval, or posting.
    """
    tender=tender.copy() if tender is not None else pd.DataFrame()
    pos=pos.copy() if pos is not None else pd.DataFrame()
    gl=gl.copy() if gl is not None else pd.DataFrame()

    if tender.empty:
        return {
            "detail":pd.DataFrame(),
            "summary":pd.DataFrame([{"Overall Status":"NO STORE TENDER DATA"}]),
            "pos_matched":pd.DataFrame(),
            "pos_unmatched_tender":pd.DataFrame(),
            "pos_unmatched_provider":pos,
            "gl_trace":pd.DataFrame(),
            "gl_untraced":gl,
            "exceptions":pd.DataFrame(),
        }

    # Give every source row an internal immutable join key. The core GL trace
    # preserves source-row order, so we can safely reattach this key after the
    # trace without changing core.py or weakening its matching authority.
    tender=tender.reset_index(drop=True)
    tender["_THREE_WAY_ID"]=tender.index.astype(str)

    noncash=tender[tender["D365 Payment"].astype(str).str.upper().ne("CASH")].copy()
    cash=tender[tender["D365 Payment"].astype(str).str.upper().eq("CASH")].copy()

    pos_match,pos_unmatched_tender,pos_unmatched_provider=core.reconcile(
        noncash.drop(columns=["_THREE_WAY_ID"],errors="ignore"),pos,tolerance
    )
    gl_trace,gl_untraced=core.trace_d365_source_to_gl(
        tender.drop(columns=["_THREE_WAY_ID"],errors="ignore"),gl,tolerance
    )

    if not pos_match.empty:
        # Unique Transaction ID is the existing source key produced by
        # normalize_tender() and retained by core.reconcile().
        p=pos_match.copy()
        p=p.rename(columns={
            "POS Amount":"POS Amount",
            "Difference":"Tender-POS Difference",
            "Status":"POS Status",
            "Match Rule":"POS Match Rule",
            "Source File":"POS Source File",
        })
        p=p[[c for c in [
            "Unique Transaction ID","POS Amount","Tender-POS Difference",
            "POS Status","POS Match Rule","POS Date","Posting Date",
            "Terminal ID","POS Source File"
        ] if c in p.columns]]
    else:
        p=pd.DataFrame(columns=["Unique Transaction ID"])

    # core.trace_d365_source_to_gl returns one row per source tender row in
    # original order. Reattach the same positional internal key.
    g=gl_trace.copy()
    if not g.empty:
        g["_THREE_WAY_ID"]=[str(i) for i in range(len(g))]
        g=g.rename(columns={
            "Actual GL Amount":"GL Amount",
            "Actual Main Account":"GL Main Account",
            "GL Journal Number":"GL Journal",
        })
        g=g[[c for c in [
            "_THREE_WAY_ID","Store Code","Source Date","Receipt ID","Sales Order",
            "Auth Code","Payment Type","Source Amount","Expected GL Accounts",
            "GL Trace Status","GL Trace Rule","GL Trace Reason","GL Journal",
            "GL Voucher","GL Date","GL Main Account","Actual Ledger Account",
            "GL Amount","GL Description","GL Source File","GL Fingerprint"
        ] if c in g.columns]]

    detail=tender.merge(
        p,on="Unique Transaction ID",how="left",suffixes=("","_POS")
    )
    detail=detail.merge(g,on="_THREE_WAY_ID",how="left",suffixes=("","_GL"))

    def classify(r):
        payment=str(r.get("D365 Payment","")).upper()
        if payment=="CASH":
            gs=str(r.get("GL Trace Status",""))
            if gs=="GL MATCHED":
                return "CASH / GL CONTROL ONLY"
            if gs:
                return "CASH / GL EXCEPTION"
            return "CASH / GL NOT TESTED"
        ps=str(r.get("POS Status",""))
        gs=str(r.get("GL Trace Status",""))
        if ps=="Matched" and gs=="GL MATCHED":
            return "THREE-WAY RECONCILED"
        if ps=="Matched" and gs:
            return "POS RECONCILED / GL EXCEPTION"
        if ps:
            return "POS EXCEPTION"
        return "STORE TENDER / POS EXCEPTION"

    detail["Three-Way Status"]=detail.apply(classify,axis=1)

    def reason(r):
        s=r["Three-Way Status"]
        if s=="THREE-WAY RECONCILED":
            return "Store Tender, POS Statement and D365 GL independently matched."
        if s=="POS RECONCILED / GL EXCEPTION":
            return str(r.get("GL Trace Reason","")) or "POS matched; GL evidence requires review."
        if s=="POS EXCEPTION":
            return str(r.get("Reason","")) or "POS matching requires review."
        if s=="STORE TENDER / POS EXCEPTION":
            return "No deterministic POS match."
        if s=="CASH / GL CONTROL ONLY":
            return "Cash is sourced from Store Tender; POS is not required."
        if s=="CASH / GL EXCEPTION":
            return "Cash Store Tender exists but D365 GL evidence requires review."
        return "GL evidence not available."
    detail["Control Reason"]=detail.apply(reason,axis=1)

    counts=detail["Three-Way Status"].value_counts()
    total=len(detail)
    reconciled=int(counts.get("THREE-WAY RECONCILED",0))
    cash_control=int(counts.get("CASH / GL CONTROL ONLY",0))
    exceptions=total-reconciled-cash_control

    summary=pd.DataFrame([{
        "Overall Status":"RECONCILED" if exceptions==0 else "EXCEPTIONS REQUIRE REVIEW",
        "Store Tender Transactions":total,
        "Three-Way Reconciled":reconciled,
        "Cash / GL Control Only":cash_control,
        "Exceptions":exceptions,
        "POS Matched":int((detail["POS Status"]=="Matched").sum()) if "POS Status" in detail else 0,
        "GL Matched":int((detail["GL Trace Status"]=="GL MATCHED").sum()) if "GL Trace Status" in detail else 0,
        "Unmatched POS Rows":len(pos_unmatched_provider),
        "Untraced GL Rows":len(gl_untraced),
        "Tolerance SAR":float(tolerance),
    }])

    exceptions_df=detail[~detail["Three-Way Status"].isin(
        ["THREE-WAY RECONCILED","CASH / GL CONTROL ONLY"]
    )].copy()

    return {
        "detail":detail.drop(columns=["_THREE_WAY_ID"],errors="ignore"),
        "summary":summary,
        "pos_matched":pos_match,
        "pos_unmatched_tender":pos_unmatched_tender,
        "pos_unmatched_provider":pos_unmatched_provider,
        "gl_trace":gl_trace.drop(columns=["_THREE_WAY_ID"],errors="ignore"),
        "gl_untraced":gl_untraced,
        "exceptions":exceptions_df,
    }

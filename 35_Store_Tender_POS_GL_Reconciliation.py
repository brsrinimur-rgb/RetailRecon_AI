
from __future__ import annotations
import io
import pandas as pd
import streamlit as st
import auth, theme, core
from logic.store_tender_pos_gl import run_three_way

st.set_page_config(page_title="Store Tender • POS • GL",layout="wide",page_icon="🔗")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Store Tender • POS • GL Control"),unsafe_allow_html=True)

st.title("🔗 Store Tender → POS Statement → GL")
st.caption(
    "Three-way accounting control after transaction reconciliation. "
    "Read-only against reconciliation/JV state: it does not change settlement, bank receipt, JV eligibility, approval or posting."
)
st.info(
    "For non-cash tenders, Store Tender + POS Statement + D365 GL must independently match "
    "for THREE-WAY RECONCILED. Cash is controlled Store Tender → GL because cash does not require POS."
)

r=st.session_state.get("ct_result") or {}
current_tender=r.get("tender",pd.DataFrame())
current_pos=r.get("pos",pd.DataFrame())

with st.expander("Current reconciliation session",expanded=True):
    if not current_tender.empty:
        st.success(f"Current Store Tender: {len(current_tender):,} rows.")
        use_current=st.checkbox("Use current Store Tender and POS data",value=True)
    else:
        use_current=False
        st.info("No current reconciliation session. Upload Store Tender and POS files below.")

st.markdown("### Upload source data")
c1,c2,c3=st.columns(3)
with c1:
    tender_files=st.file_uploader("Store Tender",type=["xlsx","xls","csv"],accept_multiple_files=True,key="v45_tender")
with c2:
    pos_files=st.file_uploader("POS Statement",type=["xlsx","xls","csv"],accept_multiple_files=True,key="v45_pos")
with c3:
    gl_files=st.file_uploader("D365 GL",type=["xlsx","xls","csv"],accept_multiple_files=True,key="v45_gl")

tol=st.number_input("Matching tolerance (SAR)",0.0,10.0,1.0,0.01)

def load_tender(files):
    parts=[]; errors=[]
    for f in files or []:
        try:
            for sheet,df in core.read_upload(f).items():
                try:
                    n=core.normalize_tender(df)
                    if n is not None and not n.empty: parts.append(n)
                except Exception as e: errors.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})
        except Exception as e: errors.append({"File":f.name,"Sheet":"","Reason":str(e)})
    return (pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()),errors

def load_pos(files):
    parts=[]; errors=[]
    for f in files or []:
        try:
            for sheet,df in core.read_upload(f).items():
                try:
                    n=core.normalize_pos(df,f.name)
                    if n is not None and not n.empty: parts.append(n)
                except Exception as e: errors.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})
        except Exception as e: errors.append({"File":f.name,"Sheet":"","Reason":str(e)})
    return (pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()),errors

def load_gl(files):
    parts=[]; errors=[]
    for f in files or []:
        try:
            for sheet,df in core.read_upload(f).items():
                try:
                    n=core.normalize_d365_gl(df,f.name)
                    if n is not None and not n.empty: parts.append(n)
                except Exception as e: errors.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})
        except Exception as e: errors.append({"File":f.name,"Sheet":"","Reason":str(e)})
    return (pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()),errors

if st.button("RUN STORE TENDER → POS → GL CONTROL",type="primary",use_container_width=True):
    if use_current:
        tender=current_tender.copy()
        pos=current_pos.copy()
        errs=[]
    else:
        tender,e1=load_tender(tender_files)
        pos,e2=load_pos(pos_files)
        errs=e1+e2
    gl,e3=load_gl(gl_files)
    errs+=e3
    if tender.empty:
        st.error("No usable Store Tender data was found.")
        st.stop()
    result=run_three_way(tender,pos,gl,tol)
    result["quarantine"]=pd.DataFrame(errs)
    st.session_state["three_way_result"]=result

res=st.session_state.get("three_way_result")
if res:
    s=res["summary"].iloc[0]
    st.markdown("### Control Dashboard")
    a,b,c,d=st.columns(4)
    a.metric("Overall",s["Overall Status"])
    b.metric("Store Tender",f'{int(s["Store Tender Transactions"]):,}')
    c.metric("3-Way Reconciled",f'{int(s["Three-Way Reconciled"]):,}')
    d.metric("Exceptions",f'{int(s["Exceptions"]):,}')
    a,b,c,d=st.columns(4)
    a.metric("POS Matched",f'{int(s["POS Matched"]):,}')
    b.metric("GL Matched",f'{int(s["GL Matched"]):,}')
    c.metric("Cash / GL Only",f'{int(s["Cash / GL Control Only"]):,}')
    d.metric("Untraced GL",f'{int(s["Untraced GL Rows"]):,}')

    tabs=st.tabs(["Three-Way Detail","Exceptions","Tender → POS","Tender → GL","Unmatched POS","Untraced GL","Quarantine"])
    with tabs[0]: st.dataframe(res["detail"],use_container_width=True,hide_index=True)
    with tabs[1]:
        if res["exceptions"].empty: st.success("No three-way exceptions.")
        else: st.dataframe(res["exceptions"],use_container_width=True,hide_index=True)
    with tabs[2]:
        st.dataframe(res["pos_matched"],use_container_width=True,hide_index=True)
        st.markdown("**Store Tender without POS match**")
        st.dataframe(res["pos_unmatched_tender"],use_container_width=True,hide_index=True)
    with tabs[3]: st.dataframe(res["gl_trace"],use_container_width=True,hide_index=True)
    with tabs[4]: st.dataframe(res["pos_unmatched_provider"],use_container_width=True,hide_index=True)
    with tabs[5]: st.dataframe(res["gl_untraced"],use_container_width=True,hide_index=True)
    with tabs[6]: st.dataframe(res["quarantine"],use_container_width=True,hide_index=True)

    bbuf=io.BytesIO()
    with pd.ExcelWriter(bbuf,engine="openpyxl") as w:
        res["summary"].to_excel(w,index=False,sheet_name="Summary")
        res["detail"].to_excel(w,index=False,sheet_name="Three-Way Detail")
        res["exceptions"].to_excel(w,index=False,sheet_name="Exceptions")
        res["pos_matched"].to_excel(w,index=False,sheet_name="Tender to POS")
        res["pos_unmatched_tender"].to_excel(w,index=False,sheet_name="Missing POS")
        res["gl_trace"].to_excel(w,index=False,sheet_name="Tender to GL")
        res["pos_unmatched_provider"].to_excel(w,index=False,sheet_name="Unmatched POS")
        res["gl_untraced"].to_excel(w,index=False,sheet_name="Untraced GL")
        res["quarantine"].to_excel(w,index=False,sheet_name="Quarantine")
    st.download_button("DOWNLOAD THREE-WAY CONTROL PACK",bbuf.getvalue(),
        "RetailReconAI_StoreTender_POS_GL_Control.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True)
else:
    st.divider()
    st.markdown("### Deterministic control")
    st.markdown(
        "- **Store Tender → POS:** existing `core.reconcile()` authority.\n"
        "- **Store Tender → GL:** existing `core.trace_d365_source_to_gl()` authority.\n"
        "- **THREE-WAY RECONCILED:** both independent controls match.\n"
        "- **Cash / GL Control Only:** POS is not required for cash.\n"
        "- No settlement, bank, JV eligibility, JV creation, approval or posting state is modified."
    )

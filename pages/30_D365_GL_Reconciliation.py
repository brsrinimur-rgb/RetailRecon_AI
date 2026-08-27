from __future__ import annotations
import io
import pandas as pd
import streamlit as st
import auth,theme,core,db

st.set_page_config(page_title="D365 GL Reconciliation",layout="wide",page_icon="📚")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","D365 GL Reconciliation & Clearing Control"),unsafe_allow_html=True)

st.title("📚 D365 GL Reconciliation")
st.caption(
    "Independent accounting proof after reconciliation/JV posting: "
    "Source Transaction → RetailRecon JV → Actual D365 General Ledger → GL Verified / Exception."
)

st.info(
    "The General Journal Account Entry files supplied by Finance are clearing-account extracts. "
    "This module can independently verify clearing-account activity, store dimensions, Sales Orders, amounts, "
    "dates and vouchers. For complete voucher-integrity proof of Bank 1015 + Commission 7231 + VAT P0672 as well, "
    "upload a D365 journal/GL extract that contains those voucher lines too."
)

with st.expander("Controlled D365 Clearing Account Matrix",expanded=False):
    mp=db.load_gl_control_mapping()
    edit=st.data_editor(
        mp.drop(columns=["Updated At"],errors="ignore"),
        use_container_width=True,hide_index=True,num_rows="dynamic"
    )
    if st.button("SAVE GL CONTROL MATRIX"):
        try:
            db.save_gl_control_mapping(edit)
            st.success("GL Control Matrix saved.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

uploads=st.file_uploader(
    "Upload D365 General Journal Account Entry files",
    type=["xlsx","xls","csv"],
    accept_multiple_files=True,
    help="You can upload multiple clearing-account exports in one run."
)
tol=st.number_input("GL amount tolerance (SAR)",0.0,10.0,1.0,0.01)

if st.button("RUN D365 GL CONTROL",type="primary",use_container_width=True):
    if not uploads:
        st.error("Upload at least one D365 General Journal Account Entry file.")
        st.stop()

    gl_parts=[];quarantine=[]
    for f in uploads:
        try:
            sheets=core.read_upload(f)
        except Exception as e:
            quarantine.append({"File":f.name,"Sheet":"","Reason":str(e)})
            continue
        for sheet,df in sheets.items():
            try:
                g=core.normalize_d365_gl(df,f.name)
                if g is not None and not g.empty:
                    g["Source Sheet"]=sheet
                    gl_parts.append(g)
                else:
                    quarantine.append({"File":f.name,"Sheet":sheet,"Reason":"No usable GL lines"})
            except Exception as e:
                quarantine.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})

    actual=pd.concat(gl_parts,ignore_index=True) if gl_parts else pd.DataFrame()
    if actual.empty:
        st.error("No valid D365 GL rows were detected.")
        st.dataframe(pd.DataFrame(quarantine),use_container_width=True,hide_index=True)
        st.stop()

    r=st.session_state.get("ct_result") or {}
    tender=r.get("tender",pd.DataFrame())
    jv=db.load_jv()

    source_trace,gl_only=core.trace_d365_source_to_gl(tender,actual,tol)
    jv_verify,jv_residual=core.reconcile_jv_to_d365_gl(jv,actual,tol)
    clearing=core.d365_gl_clearing_control(actual)
    exceptions=core.build_d365_gl_exceptions(source_trace,jv_verify,gl_only,actual)

    source_matched=int((source_trace.get("GL Trace Status",pd.Series(dtype=str))=="GL MATCHED").sum()) if not source_trace.empty else 0
    source_missing=int((source_trace.get("GL Trace Status",pd.Series(dtype=str))=="GL NOT FOUND").sum()) if not source_trace.empty else 0
    jv_matched=int((jv_verify.get("GL Verification Status",pd.Series(dtype=str))=="GL MATCHED").sum()) if not jv_verify.empty else 0
    jv_missing=int((jv_verify.get("GL Verification Status",pd.Series(dtype=str))=="GL NOT FOUND").sum()) if not jv_verify.empty else 0
    critical=int((exceptions.get("Priority",pd.Series(dtype=str))=="CRITICAL").sum()) if not exceptions.empty else 0

    overall="D365 GL VERIFIED" if (
        (source_trace.empty or (source_trace["GL Trace Status"]=="GL MATCHED").all())
        and (jv_verify.empty or (jv_verify["GL Verification Status"]=="GL MATCHED").all())
        and critical==0
    ) else "GL REVIEW REQUIRED"

    summary={
        "Overall Status":overall,
        "Actual GL Rows":len(actual),
        "Source GL Matched":source_matched,
        "Source GL Missing":source_missing,
        "Untraced GL Rows":len(gl_only),
        "JV GL Matched":jv_matched,
        "JV GL Missing":jv_missing,
        "GL Exceptions":len(exceptions),
        "Critical Exceptions":critical,
    }

    result={
        "actual_gl":actual,
        "source_trace":source_trace,
        "gl_only":gl_only,
        "jv_verification":jv_verify,
        "jv_residual":jv_residual,
        "clearing_control":clearing,
        "exceptions":exceptions,
        "quarantine":pd.DataFrame(quarantine),
        "summary":summary,
    }
    st.session_state["gl_control_result"]=result

    # Make GL intelligence available to AI Finance Copilot in the same active control session.
    if r is not None:
        r["gl_actual"]=actual
        r["gl_source_trace"]=source_trace
        r["gl_jv_verification"]=jv_verify
        r["gl_exceptions"]=exceptions
        r["gl_clearing_control"]=clearing
        st.session_state["ct_result"]=r

    try:
        run_id=db.save_gl_verification_run(
            summary,
            {
                "source_trace":source_trace,
                "jv_verification":jv_verify,
                "clearing_control":clearing,
                "exceptions":exceptions,
            },
            st.session_state.user["username"],
            "ULC"
        )
        st.success(f"D365 GL Control completed. Snapshot saved as {run_id}.")
    except Exception as e:
        st.warning(f"Control completed, but snapshot persistence failed: {e}")

res=st.session_state.get("gl_control_result")
if res:
    s=res["summary"]
    st.markdown("### GL Control Dashboard")
    k1,k2,k3,k4=st.columns(4)
    k1.metric("Overall",s["Overall Status"])
    k2.metric("Actual D365 GL Rows",s["Actual GL Rows"])
    k3.metric("Source → GL Matched",s["Source GL Matched"])
    k4.metric("Source GL Missing",s["Source GL Missing"])
    k1,k2,k3,k4=st.columns(4)
    k1.metric("JV → GL Matched",s["JV GL Matched"])
    k2.metric("JV GL Missing",s["JV GL Missing"])
    k3.metric("Untraced D365 GL",s["Untraced GL Rows"])
    k4.metric("Critical Exceptions",s["Critical Exceptions"])

    tabs=st.tabs([
        "Normalized D365 GL","Source → GL Trace","JV → GL Verification",
        "Clearing Movement Control","GL Exceptions","Store 613 Sales Order Trace",
        "Untraced D365 GL","Upload Quarantine","Run History"
    ])

    with tabs[0]:
        st.dataframe(res["actual_gl"],use_container_width=True,hide_index=True)

    with tabs[1]:
        st.caption("Deterministic source-to-GL matches only. Same-period amount-only candidates remain REVIEW.")
        st.dataframe(res["source_trace"],use_container_width=True,hide_index=True)

    with tabs[2]:
        if res["jv_verification"].empty:
            st.info("No RetailRecon clearing JV lines are currently stored. Create/approve/post JVs to activate JV → GL verification.")
        else:
            st.dataframe(res["jv_verification"],use_container_width=True,hide_index=True)

    with tabs[3]:
        st.caption(
            "Net GL Movement is the signed movement in the uploaded extract, not a certified closing balance "
            "unless the upload contains the complete period/opening population."
        )
        st.dataframe(res["clearing_control"],use_container_width=True,hide_index=True)

    with tabs[4]:
        if res["exceptions"].empty:
            st.success("No GL exceptions in the current uploaded scope.")
        else:
            st.dataframe(res["exceptions"],use_container_width=True,hide_index=True)

    with tabs[5]:
        a=res["actual_gl"]
        t=res["source_trace"]
        gl613=a[(a["Store Code"].astype(str)=="613") & a["Sales Order"].astype(str).ne("")] if not a.empty else pd.DataFrame()
        tr613=t[t["Store Code"].astype(str)=="613"] if not t.empty else pd.DataFrame()
        c1,c2=st.columns(2)
        with c1:
            st.markdown("**D365 GL Store 613 Sales Order Evidence**")
            st.dataframe(gl613,use_container_width=True,hide_index=True)
        with c2:
            st.markdown("**Store 613 Source → GL Result**")
            st.dataframe(tr613,use_container_width=True,hide_index=True)

    with tabs[6]:
        st.dataframe(res["gl_only"],use_container_width=True,hide_index=True)

    with tabs[7]:
        st.dataframe(res["quarantine"],use_container_width=True,hide_index=True)

    with tabs[8]:
        st.dataframe(db.load_gl_verification_runs(),use_container_width=True,hide_index=True)

    # Export audit pack.
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine="openpyxl") as w:
        pd.DataFrame([s]).to_excel(w,index=False,sheet_name="Summary")
        res["actual_gl"].to_excel(w,index=False,sheet_name="Actual D365 GL")
        res["source_trace"].to_excel(w,index=False,sheet_name="Source to GL")
        res["jv_verification"].to_excel(w,index=False,sheet_name="JV to GL")
        res["clearing_control"].to_excel(w,index=False,sheet_name="Clearing Control")
        res["exceptions"].to_excel(w,index=False,sheet_name="GL Exceptions")
        res["gl_only"].to_excel(w,index=False,sheet_name="Untraced GL")
    st.download_button(
        "DOWNLOAD D365 GL VERIFICATION PACK",
        b.getvalue(),
        "RetailReconAI_D365_GL_Verification.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    st.divider()
    st.markdown("### What this module proves")
    st.markdown(
        """
        - **Source → GL:** Can the D365 Store Tender transaction be traced into the correct clearing account?
        - **Store 613:** Does the Sales Order in D365 GL trace back to the Sales Order / Receipt evidence?
        - **JV → GL:** Does the RetailRecon clearing JV line appear in actual D365 GL?
        - **Dimension:** Is the expected Store Code embedded in the D365 Ledger Account?
        - **Duplicate / reversal:** Are repeated fingerprints or opposite-sign movements present?
        - **Reverse reconciliation:** Which D365 controlled clearing entries cannot be traced back to current source data?
        """
    )

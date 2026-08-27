
import io, pandas as pd, streamlit as st
import auth, theme
from logic.pos_gl_reconciliation import normalize_pos, normalize_gl, reconcile_pos_to_gl
st.set_page_config(page_title="POS → GL Reconciliation",layout="wide",page_icon="🧾")
auth.require_login({"Admin","Finance Manager","Finance Checker"}); auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","POS Statement → D365 GL Reconciliation"),unsafe_allow_html=True)
st.title("🧾 POS Statement → D365 GL Reconciliation")
st.caption("Accounting authority: POS Statement Amount ↔ D365 GL Amount. Store Tender is not part of this module.")
st.info("Merchant ID is a key identity control. Amount is never used to select a GL row. Amount is compared only after deterministic GL evidence is identified.")
a,b,c=st.columns([1,1,.5])
with a: pf=st.file_uploader("POS Statement",type=["xlsx","xls","csv"],key="v47pos")
with b: gf=st.file_uploader("D365 GL Ledger / GL Verification",type=["xlsx","xls","csv"],key="v47gl")
with c: tol=st.number_input("Tolerance (SAR)",0.0,10.0,.50,.01)
def read(f):
    if f.name.lower().endswith(".csv"): return pd.read_csv(f)
    return pd.concat([pd.read_excel(f,sheet_name=s) for s in pd.ExcelFile(f).sheet_names],ignore_index=True)
if st.button("RUN POS → GL RECONCILIATION",type="primary",use_container_width=True):
    if not pf or not gf: st.error("Upload both POS Statement and D365 GL Ledger."); st.stop()
    st.session_state["v47"]=reconcile_pos_to_gl(normalize_pos(read(pf),pf.name),normalize_gl(read(gf),gf.name),tol)
r=st.session_state.get("v47")
if r:
    s=r["summary"].iloc[0]; a,b,c,d=st.columns(4)
    a.metric("Overall",s["Overall Status"]); b.metric("POS Rows",int(s["POS Rows"])); c.metric("GL Matched",int(s["GL Matched"])); d.metric("Exceptions",len(r["exceptions"]))
    tabs=st.tabs(["All Results","GL Matched","Amount Exceptions","Review","Not Posted / ID","Unmatched GL"])
    with tabs[0]: st.dataframe(r["detail"],use_container_width=True,hide_index=True)
    with tabs[1]: st.dataframe(r["matched"],use_container_width=True,hide_index=True)
    with tabs[2]: st.dataframe(r["exceptions"][r["exceptions"].Status=="GL AMOUNT EXCEPTION"],use_container_width=True,hide_index=True)
    with tabs[3]: st.dataframe(r["exceptions"][r["exceptions"].Status=="GL REVIEW REQUIRED"],use_container_width=True,hide_index=True)
    with tabs[4]: st.dataframe(r["exceptions"][r["exceptions"].Status.isin(["GL NOT POSTED","IDENTIFIER MISMATCH","POS DATA INCOMPLETE"])],use_container_width=True,hide_index=True)
    with tabs[5]: st.dataframe(r["unmatched_gl"],use_container_width=True,hide_index=True)
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine="openpyxl") as w:
        for k,n in [("summary","Summary"),("detail","POS to GL"),("matched","GL Matched"),("exceptions","Exceptions"),("unmatched_gl","Unmatched GL")]: r[k].to_excel(w,index=False,sheet_name=n)
    st.download_button("DOWNLOAD POS-GL RECONCILIATION",b.getvalue(),"RetailReconAI_POS_to_GL_Reconciliation.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
else: st.markdown("### Rule: **POS Statement Amount ↔ D365 GL Amount**")

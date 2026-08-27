
import io
import pandas as pd
import streamlit as st
import auth, theme
from logic.pos_gl_reconciliation import normalize_pos, normalize_gl, reconcile_pos_to_gl

st.set_page_config(page_title="POS → D365 GL Reconciliation", layout="wide", page_icon="🧾")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","POS Statement → D365 GL Reconciliation"), unsafe_allow_html=True)

st.title("🧾 POS Statement → D365 GL Reconciliation")
st.caption("Accounting authority: POS Statement Amount ↔ D365 GL Amount. Store Tender is NOT used in this module.")

st.info(
    "Merchant ID is a key identity control. The engine never uses amount to select a GL row. "
    "After deterministic identity evidence is found, POS Statement Amount is compared with D365 GL Amount."
)

c1, c2, c3 = st.columns([1, 1, 0.5])
with c1:
    pos_files = st.file_uploader(
        "POS Statement — MULTIPLE FILES",
        type=["xlsx", "xls", "csv"], accept_multiple_files=True, key="v51_pos",
        help="Use Ctrl/Shift to select several files together, or click + to add files one by one."
    )
with c2:
    gl_files = st.file_uploader(
        "D365 GL LEDGER — MULTIPLE FILES",
        type=["xlsx", "xls", "csv"], accept_multiple_files=True, key="v51_gl",
        help="Use Ctrl/Shift to select several files together, or click + to add files one by one."
    )
with c3:
    tolerance = st.number_input("Tolerance (SAR)", 0.0, 10.0, 0.50, 0.01)

st.caption("MULTI-FILE MODE: Add multiple POS files and multiple D365 GL files. Use Ctrl/Shift in the picker, or click + to add files one by one.")
if pos_files:
    st.success(f"POS files selected: {len(pos_files)}")
    st.write("POS: " + " | ".join(f.name for f in pos_files))
else:
    st.info("POS: No files selected yet.")
if gl_files:
    st.success(f"D365 GL files selected: {len(gl_files)}")
    st.write("D365 GL: " + " | ".join(f.name for f in gl_files))
else:
    st.info("D365 GL: No files selected yet.")

def read_one(f):
    if f.name.lower().endswith(".csv"):
        return pd.read_csv(f)
    frames=[]
    for s in pd.ExcelFile(f).sheet_names:
        x=pd.read_excel(f, sheet_name=s)
        if not x.empty:
            frames.append(x)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def read_many(files):
    frames=[]
    for f in files:
        x=read_one(f)
        if not x.empty:
            x["__uploaded_file__"]=f.name
            frames.append(x)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

if st.button("RUN POS → GL RECONCILIATION", type="primary", use_container_width=True):
    if not pos_files or not gl_files:
        st.error("Upload at least one POS Statement file and at least one D365 GL Ledger file.")
        st.stop()
    raw_pos=read_many(pos_files)
    raw_gl=read_many(gl_files)
    st.session_state["v50_pos_gl"]=reconcile_pos_to_gl(
        normalize_pos(raw_pos, "MULTIPLE POS FILES"),
        normalize_gl(raw_gl, "MULTIPLE GL FILES"),
        tolerance
    )

r=st.session_state.get("v50_pos_gl")
if r:
    s=r["summary"].iloc[0]

    # Explicitly use the V47/V48 summary schema. No legacy three-way keys.
    overall=s.get("Overall Status","EXCEPTIONS REQUIRE REVIEW")
    pos_rows=int(s.get("POS Rows",0))
    gl_matched=int(s.get("GL Matched",0))
    amount_exc=int(s.get("GL Amount Exceptions",0))
    not_posted=int(s.get("GL Not Posted",0))
    review=int(s.get("Review Required",0))
    id_mismatch=int(s.get("Identifier Mismatch",0))
    incomplete=int(s.get("POS Data Incomplete",0))
    unmatched_gl=int(s.get("Unmatched GL Rows",0))
    exceptions=amount_exc+not_posted+review+id_mismatch+incomplete

    st.subheader("Control Dashboard")
    a,b,c,d=st.columns(4)
    a.metric("Overall", overall)
    b.metric("POS Rows", f"{pos_rows:,}")
    c.metric("GL Matched", f"{gl_matched:,}")
    d.metric("Exceptions", f"{exceptions:,}")

    a,b,c,d,e=st.columns(5)
    a.metric("Amount Exceptions", amount_exc)
    b.metric("GL Not Posted", not_posted)
    c.metric("Review Required", review)
    d.metric("Identifier Mismatch", id_mismatch)
    e.metric("Unmatched GL", unmatched_gl)

    st.subheader("POS → GL Results")
    tabs=st.tabs(["All Results","GL Matched","Amount Exceptions","Review Required","Not Posted / ID","Unmatched GL"])
    with tabs[0]:
        st.dataframe(r["detail"], use_container_width=True, hide_index=True)
    with tabs[1]:
        st.dataframe(r["matched"], use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(r["exceptions"][r["exceptions"]["Status"]=="GL AMOUNT EXCEPTION"], use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(r["exceptions"][r["exceptions"]["Status"]=="GL REVIEW REQUIRED"], use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(
            r["exceptions"][r["exceptions"]["Status"].isin(
                ["GL NOT POSTED","IDENTIFIER MISMATCH","POS DATA INCOMPLETE"]
            )],
            use_container_width=True, hide_index=True
        )
    with tabs[5]:
        st.dataframe(r["unmatched_gl"], use_container_width=True, hide_index=True)

    b=io.BytesIO()
    with pd.ExcelWriter(b, engine="openpyxl") as w:
        r["summary"].to_excel(w,index=False,sheet_name="Summary")
        r["detail"].to_excel(w,index=False,sheet_name="POS to GL")
        r["matched"].to_excel(w,index=False,sheet_name="GL Matched")
        r["exceptions"].to_excel(w,index=False,sheet_name="Exceptions")
        r["unmatched_gl"].to_excel(w,index=False,sheet_name="Unmatched GL")
    st.download_button(
        "DOWNLOAD POS-GL RECONCILIATION",
        b.getvalue(),
        "RetailReconAI_POS_to_GL_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
else:
    st.subheader("Control Rule")
    st.markdown("### **POS Statement Amount ↔ D365 GL Amount**")
    st.write(
        "Merchant ID, Store, Provider, Reference/Auth and Date establish transaction identity. "
        "A matching amount alone can never create a GL match."
    )

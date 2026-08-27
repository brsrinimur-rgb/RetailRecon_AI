
import io, zipfile
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
st.caption("Daily bulk reconciliation: multiple POS files + multiple D365 GL account dumps. Store Tender is NOT used.")
st.info(
    "Accounting authority: POS Statement Amount ↔ D365 GL Amount. "
    "Merchant ID, Store, Provider, Reference/Auth and Date establish identity. "
    "Amount is compared only after deterministic GL evidence is identified."
)

def read_one_bytes(name, data):
    lname=name.lower()
    if lname.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    return pd.concat(
        [pd.read_excel(io.BytesIO(data), sheet_name=s) for s in pd.ExcelFile(io.BytesIO(data)).sheet_names],
        ignore_index=True
    )

def read_uploaded(f):
    return read_one_bytes(f.name, f.getvalue())

def expand_zip(zf):
    result=[]
    with zipfile.ZipFile(io.BytesIO(zf.getvalue())) as z:
        for info in z.infolist():
            if info.is_dir(): continue
            name=info.filename
            if name.lower().endswith((".xlsx",".xls",".csv")):
                result.append((Path(name).name,z.read(info)))
    return result

st.subheader("1. POS Statements — Daily Bulk Upload")
st.caption("Select as many daily POS files as you need, or upload one ZIP containing all POS files.")
pos_mode=st.radio("POS upload method",["Multiple files","ZIP batch"],horizontal=True,key="v53_pos_mode")
pos_pairs=[]
if pos_mode=="Multiple files":
    pos_uploads=st.file_uploader(
        "POS files — MULTIPLE",
        type=["xlsx","xls","csv"],
        accept_multiple_files=True,
        key="v53_pos_multi",
        help="Use the file picker to select several files. You can also add more files after the picker opens."
    )
    for f in (pos_uploads or []):
        pos_pairs.append((f.name,f.getvalue()))
else:
    pos_zip=st.file_uploader("POS ZIP batch",type=["zip"],accept_multiple_files=False,key="v53_pos_zip")
    if pos_zip: pos_pairs=expand_zip(pos_zip)

if pos_pairs:
    st.success(f"POS files loaded: {len(pos_pairs)}")
    st.write("POS: " + " | ".join(n for n,_ in pos_pairs[:50]) + (" ..." if len(pos_pairs)>50 else ""))
else:
    st.info("POS: no files loaded.")

st.subheader("2. D365 GL — Daily Bulk Upload")
st.caption("Upload all GL account dumps together. More than 8 GL accounts is supported; there is no account-count limit in the reconciliation UI.")
gl_mode=st.radio("GL upload method",["Multiple files","ZIP batch"],horizontal=True,key="v53_gl_mode")
gl_pairs=[]
if gl_mode=="Multiple files":
    gl_uploads=st.file_uploader(
        "D365 GL files — MULTIPLE",
        type=["xlsx","xls","csv"],
        accept_multiple_files=True,
        key="v53_gl_multi",
        help="Select all GL account dumps for the period. You can upload 8, 20, 50+ files."
    )
    for f in (gl_uploads or []):
        gl_pairs.append((f.name,f.getvalue()))
else:
    gl_zip=st.file_uploader("D365 GL ZIP batch",type=["zip"],accept_multiple_files=False,key="v53_gl_zip")
    if gl_zip: gl_pairs=expand_zip(gl_zip)

if gl_pairs:
    st.success(f"D365 GL files loaded: {len(gl_pairs)}")
    st.write("GL: " + " | ".join(n for n,_ in gl_pairs[:50]) + (" ..." if len(gl_pairs)>50 else ""))
else:
    st.info("D365 GL: no files loaded.")

tolerance=st.number_input("Matching tolerance (SAR)",0.0,10.0,0.50,0.01)

if st.button("RUN POS → GL RECONCILIATION",type="primary",use_container_width=True):
    if not pos_pairs or not gl_pairs:
        st.error("Load at least one POS file and one GL file (or ZIP batch) before running.")
        st.stop()

    pos_frames=[]
    for name,data in pos_pairs:
        x=read_one_bytes(name,data)
        if not x.empty: pos_frames.append(x)
    gl_frames=[]
    for name,data in gl_pairs:
        x=read_one_bytes(name,data)
        if not x.empty: gl_frames.append(x)

    raw_pos=pd.concat(pos_frames,ignore_index=True) if pos_frames else pd.DataFrame()
    raw_gl=pd.concat(gl_frames,ignore_index=True) if gl_frames else pd.DataFrame()

    st.session_state.v53_pos_gl=reconcile_pos_to_gl(
        normalize_pos(raw_pos,"MULTIPLE POS FILES"),
        normalize_gl(raw_gl,"MULTIPLE GL FILES"),
        tolerance
    )

r=st.session_state.get("v53_pos_gl")
if r:
    s=r["summary"].iloc[0]
    overall=s.get("Overall Status","EXCEPTIONS REQUIRE REVIEW")
    pos_rows=int(s.get("POS Rows",0)); gl_matched=int(s.get("GL Matched",0))
    amount_exc=int(s.get("GL Amount Exceptions",0)); not_posted=int(s.get("GL Not Posted",0))
    review=int(s.get("Review Required",0)); id_mismatch=int(s.get("Identifier Mismatch",0))
    incomplete=int(s.get("POS Data Incomplete",0)); unmatched_gl=int(s.get("Unmatched GL Rows",0))
    exceptions=amount_exc+not_posted+review+id_mismatch+incomplete

    st.subheader("Control Dashboard")
    a,b,c,d=st.columns(4)
    a.metric("Overall",overall); b.metric("POS Rows",f"{pos_rows:,}"); c.metric("GL Matched",f"{gl_matched:,}"); d.metric("Exceptions",f"{exceptions:,}")
    a,b,c,d,e=st.columns(5)
    a.metric("Amount Exceptions",amount_exc); b.metric("GL Not Posted",not_posted); c.metric("Review Required",review); d.metric("Identifier Mismatch",id_mismatch); e.metric("Unmatched GL",unmatched_gl)

    tabs=st.tabs(["All Results","GL Matched","Amount Exceptions","Review Required","Not Posted / ID","Unmatched GL"])
    with tabs[0]: st.dataframe(r["detail"],use_container_width=True,hide_index=True)
    with tabs[1]: st.dataframe(r["matched"],use_container_width=True,hide_index=True)
    with tabs[2]: st.dataframe(r["exceptions"][r["exceptions"]["Status"]=="GL AMOUNT EXCEPTION"],use_container_width=True,hide_index=True)
    with tabs[3]: st.dataframe(r["exceptions"][r["exceptions"]["Status"]=="GL REVIEW REQUIRED"],use_container_width=True,hide_index=True)
    with tabs[4]: st.dataframe(r["exceptions"][r["exceptions"]["Status"].isin(["GL NOT POSTED","IDENTIFIER MISMATCH","POS DATA INCOMPLETE"])],use_container_width=True,hide_index=True)
    with tabs[5]: st.dataframe(r["unmatched_gl"],use_container_width=True,hide_index=True)

    b=io.BytesIO()
    with pd.ExcelWriter(b,engine="openpyxl") as w:
        r["summary"].to_excel(w,index=False,sheet_name="Summary")
        r["detail"].to_excel(w,index=False,sheet_name="POS to GL")
        r["matched"].to_excel(w,index=False,sheet_name="GL Matched")
        r["exceptions"].to_excel(w,index=False,sheet_name="Exceptions")
        r["unmatched_gl"].to_excel(w,index=False,sheet_name="Unmatched GL")
    st.download_button("DOWNLOAD POS-GL RECONCILIATION",b.getvalue(),"RetailReconAI_POS_to_GL_Reconciliation.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
else:
    st.subheader("Control Rule")
    st.markdown("### POS Statement Amount ↔ D365 GL Amount")
    st.write("Merchant ID, Store, Provider, Reference/Auth and Date establish transaction identity. A matching amount alone can never create a GL match.")

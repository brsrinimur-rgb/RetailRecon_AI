
import io, zipfile
from pathlib import Path
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

def _find_header_row(path_or_bytes, sheet_name):
    raw=pd.read_excel(path_or_bytes, sheet_name=sheet_name, header=None, nrows=30)
    wanted={"merchant id","transaction amount","terminal id","approval code","trans seq number",
            "retailer pos account","retailer id","transaction date"}
    for i,row in raw.iterrows():
        vals={str(v).strip().lower() for v in row.tolist() if pd.notna(v)}
        if len(vals & wanted) >= 2:
            return int(i)
    return 0

def read_one_bytes(name, data):
    lname=name.lower()
    if lname.endswith(".csv"):
        raw=pd.read_csv(io.BytesIO(data),header=None)
        for i,row in raw.iterrows():
            vals={str(v).strip().lower() for v in row.tolist() if pd.notna(v)}
            if len(vals & {"merchant id","transaction amount","terminal id","approval code"}) >= 2:
                return pd.read_csv(io.BytesIO(data),header=i)
        return pd.read_csv(io.BytesIO(data))
    frames=[]
    for s in pd.ExcelFile(io.BytesIO(data)).sheet_names:
        header=_find_header_row(io.BytesIO(data),s)
        x=pd.read_excel(io.BytesIO(data),sheet_name=s,header=header)
        x=x.dropna(axis=0,how="all").dropna(axis=1,how="all")
        if not x.empty:
            x["__Source Sheet"]=s
            frames.append(x)
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()

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

st.subheader("1. POS Statements — BULK EXCEL UPLOAD")
st.caption("Upload many daily POS Excel/CSV files together. There is no one-file limit.")

pos_uploads=st.file_uploader(
    "📤 UPLOAD MULTIPLE POS EXCEL FILES",
    type=["xlsx","xls","csv"],
    accept_multiple_files=True,
    key="v54_pos_multi",
    help="In the Windows picker, hold Ctrl or Shift to select several files. You can also drag multiple files into this box."
)
pos_zip=st.file_uploader(
    "OR upload ONE ZIP containing all POS files",
    type=["zip"],
    accept_multiple_files=False,
    key="v54_pos_zip"
)

pos_pairs=[]
for f in (pos_uploads or []):
    pos_pairs.append((f.name,f.getvalue()))
if pos_zip:
    pos_pairs.extend(expand_zip(pos_zip))

_seen=set()
clean=[]
for item in pos_pairs:
    if item[0] not in _seen:
        _seen.add(item[0])
        clean.append(item)
pos_pairs=clean

if pos_pairs:
    st.success(f"POS files loaded: {len(pos_pairs)}")
    with st.expander("View POS files", expanded=False):
        st.write("\n".join(f"• {n}" for n,_ in pos_pairs))
else:
    st.info("POS: upload multiple Excel files above, or upload one ZIP batch.")

st.subheader("2. D365 GL — BULK EXCEL UPLOAD")
st.caption("Upload all D365 GL account dumps together. 8, 20, 50+ GL accounts are supported.")

gl_uploads=st.file_uploader(
    "📤 UPLOAD MULTIPLE D365 GL EXCEL FILES",
    type=["xlsx","xls","csv"],
    accept_multiple_files=True,
    key="v54_gl_multi",
    help="In the Windows picker, hold Ctrl or Shift to select several files. You can also drag multiple files into this box."
)
gl_zip=st.file_uploader(
    "OR upload ONE ZIP containing all D365 GL files",
    type=["zip"],
    accept_multiple_files=False,
    key="v54_gl_zip"
)

gl_pairs=[]
for f in (gl_uploads or []):
    gl_pairs.append((f.name,f.getvalue()))
if gl_zip:
    gl_pairs.extend(expand_zip(gl_zip))

_seen=set()
clean=[]
for item in gl_pairs:
    if item[0] not in _seen:
        _seen.add(item[0])
        clean.append(item)
gl_pairs=clean

if gl_pairs:
    st.success(f"D365 GL files loaded: {len(gl_pairs)}")
    with st.expander("View D365 GL files", expanded=False):
        st.write("\n".join(f"• {n}" for n,_ in gl_pairs))
else:
    st.info("D365 GL: upload multiple Excel files above, or upload one ZIP batch.")

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
    if not raw_pos.empty:
        preview=normalize_pos(raw_pos,"MULTIPLE POS FILES")
        mids=preview["merchant_id"].replace("",pd.NA).dropna().unique().tolist()
        terms=preview["terminal_id"].replace("",pd.NA).dropna().unique().tolist() if "terminal_id" in preview else []
        st.success(f"POS extraction: {len(preview):,} rows | Merchant IDs: {len(mids)} | Terminals: {len(terms)}")
        if mids: st.write("Merchant ID(s): "+", ".join(map(str,mids[:30])))
        if terms: st.write("Terminal ID(s): "+", ".join(map(str,terms[:30])))

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


import io, zipfile
from pathlib import Path
import pandas as pd
import streamlit as st
import auth, theme
from logic.pos_gl_reconciliation import (
    build_pos_dataset, build_gl_dataset,
    reconcile_pos_to_gl, reconcile_pos_to_gl_by_bucket,
    detect_exact_duplicate_files, detect_content_duplicate_pos, detect_content_duplicate_gl,
    validate_pos_completeness, upload_control_summary,
)

st.set_page_config(page_title="POS → D365 GL Reconciliation", layout="wide", page_icon="🧾")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","POS Statement → D365 GL Reconciliation"), unsafe_allow_html=True)

st.title("🧾 POS Statement → D365 GL Reconciliation")
st.caption("Daily bulk reconciliation: multiple POS files + multiple D365 GL account dumps. Store Tender is NOT used.")
st.info(
    "Accounting authority: POS Statement Amount ↔ D365 GL Amount, summed per Store + Date. "
    "Store Code and Date identify the bucket; Amount alone proves or rejects the match. "
    "Merchant ID, Provider, Terminal and Auth Code stay available as investigation detail, "
    "never as part of the matching key."
)

def read_one_bytes(name, data):
    lname=name.lower()
    if lname.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    return pd.concat(
        [pd.read_excel(io.BytesIO(data), sheet_name=s) for s in pd.ExcelFile(io.BytesIO(data)).sheet_names],
        ignore_index=True
    )

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

st.subheader("3. Validate")
st.caption("Checks uploads for duplicate files, missing Store Code/Date, and shows what's actually loaded -- before you commit to a full reconciliation run.")

if st.button("🔍 VALIDATE UPLOADS", use_container_width=True):
    if not pos_pairs or not gl_pairs:
        st.error("Load at least one POS file and one GL file (or ZIP batch) before validating.")
        st.stop()
    with st.spinner("Reading and normalizing uploads..."):
        npos = build_pos_dataset(pos_pairs)
        ngl = build_gl_dataset(gl_pairs)
        st.session_state.v53_pos_ds = npos
        st.session_state.v53_gl_ds = ngl
        st.session_state.v53_pos_pairs_sig = [n for n,_ in pos_pairs]
        st.session_state.v53_gl_pairs_sig = [n for n,_ in gl_pairs]
        st.session_state.v53_validated = True

if st.session_state.get("v53_validated"):
    npos = st.session_state.v53_pos_ds
    ngl = st.session_state.v53_gl_ds

    exact_pos = detect_exact_duplicate_files(pos_pairs)
    exact_gl = detect_exact_duplicate_files(gl_pairs)
    content_pos = detect_content_duplicate_pos(npos)
    content_gl = detect_content_duplicate_gl(ngl)
    all_dupes = exact_pos + exact_gl + content_pos + content_gl

    if all_dupes:
        st.error(f"🔴 DUPLICATE SOURCE FILE DETECTED ({len(all_dupes)}) -- review before running reconciliation. Totals will double-count until this is resolved.")
        for d in exact_pos + exact_gl:
            st.write(f"• **Exact duplicate:** `{d['file_a']}` and `{d['file_b']}` -- {d['reason']}")
        for d in content_pos + content_gl:
            st.write(f"• **Likely duplicate:** `{d['file_a']}` and `{d['file_b']}` -- {d['reason']}")
    else:
        st.success("✅ No duplicate files detected among the uploads.")

    comp = validate_pos_completeness(npos)
    if comp["missing_store"] or comp["missing_date"] or comp["missing_amount"]:
        st.warning(
            f"POS completeness: {comp['clean_rows']:,}/{comp['total_rows']:,} rows usable. "
            f"{comp['missing_store']:,} missing Store Code, {comp['missing_date']:,} missing Date, "
            f"{comp['missing_amount']:,} missing Amount -- these rows can't be bucketed and will show as "
            f"Identifier Mismatch / POS Data Incomplete."
        )
        with st.expander("View rows with missing Store Code / Date / Amount", expanded=False):
            st.dataframe(comp["sample"], use_container_width=True, hide_index=True)
    else:
        st.success(f"✅ POS completeness: all {comp['total_rows']:,} rows have a Store Code, Date and Amount.")

    ctrl = upload_control_summary(pos_pairs, gl_pairs, npos, ngl)
    st.subheader("Upload Control Summary")
    a,b,c,d = st.columns(4)
    a.metric("POS Files", ctrl["pos_files"]); b.metric("GL Files", ctrl["gl_files"])
    c.metric("POS Rows", f"{ctrl['pos_rows']:,}"); d.metric("GL Rows", f"{ctrl['gl_rows']:,}")
    a,b,c = st.columns(3)
    a.metric("POS Stores", len(ctrl["pos_stores"])); b.metric("GL Stores", len(ctrl["gl_stores"])); c.metric("GL Clearing Accounts", len(ctrl["gl_accounts"]))

    period = ctrl["period"]
    st.write(f"**POS date range:** {period['pos_date_min']} → {period['pos_date_max']} ({period['pos_distinct_dates']} distinct dates)")
    st.write(f"**GL date range:** {period['gl_date_min']} → {period['gl_date_max']} ({period['gl_distinct_dates']} distinct dates)")
    if period["dates_pos_only"]:
        st.warning(f"{len(period['dates_pos_only'])} date(s) have POS activity but no GL file covering them: " + ", ".join(str(d.date()) for d in period["dates_pos_only"][:15]) + (" ..." if len(period["dates_pos_only"])>15 else ""))
    if period["dates_gl_only"]:
        st.warning(f"{len(period['dates_gl_only'])} date(s) have GL activity but no POS file covering them: " + ", ".join(str(d.date()) for d in period["dates_gl_only"][:15]) + (" ..." if len(period["dates_gl_only"])>15 else ""))
    if ctrl["stores_pos_only"]:
        st.caption(f"Stores in POS only (no GL clearing activity at all): {', '.join(ctrl['stores_pos_only'])}")
    if ctrl["stores_gl_only"]:
        st.caption(f"Stores in GL only (no POS activity at all): {', '.join(ctrl['stores_gl_only'])}")

st.divider()
tolerance=st.number_input("Matching tolerance per line item (SAR)",0.0,10.0,0.50,0.01,
    help="Applied per transaction/line in a bucket, with a hard automatic bucket ceiling of SAR 50. This prevents a large row count from creating an unsafe multi-hundred or multi-thousand SAR tolerance.")

st.info(
    "Control principle: Store Code + Date is the only matching key. "
    "Amount proves or rejects the Store+Date bucket. Provider, Merchant ID, "
    "Terminal and Auth Code are investigation fields only."
)

granularity=st.radio(
    "Matching granularity",
    ["Store + Date bucket (recommended)","Row-to-row (1:1)"],
    index=0,
    help=(
        "Bucket (recommended): compares total POS Amount vs total D365 GL Amount per Store + Date. "
        "Store Code and Date identify the bucket; the amount alone decides match vs exception. "
        "Row-to-row: requires a single POS transaction to match a single GL line exactly -- only "
        "produces matches if your D365 export truly posts one GL line per POS transaction."
    ),
)
settlement_lag_days=0
exclude_dup_pos=True
exclude_dup_gl=True
if granularity.startswith("Store + Date"):
    c1,c2 = st.columns(2)
    with c1:
        settlement_lag_days=st.number_input(
            "Settlement lag (days) -- shifts POS Date forward before matching to GL Date",
            0,10,0,1,
            help="Default 0: D365 GL/journal postings are normally booked the same day as the sale.",
        )
    with c2:
        st.write("Row-level duplicate exclusion")
        exclude_dup_pos=st.checkbox("Exclude duplicate POS rows from bucket sums (Store+Date+Reference/Auth+Amount)",value=True)
        exclude_dup_gl=st.checkbox("Exclude duplicate GL rows from bucket sums (Voucher+Journal+Account+Store+Date)",value=True)

if st.button("RUN POS → GL RECONCILIATION",type="primary",use_container_width=True):
    if not pos_pairs or not gl_pairs:
        st.error("Load at least one POS file and one GL file (or ZIP batch) before running.")
        st.stop()

    # Each file/sheet is read and normalized on its own (real header-row
    # detection + provider-specific parsing + D365 Ledger Account dimension
    # parsing all happen per file here) instead of being concatenated into
    # one raw blob first -- that concatenation was what caused every POS
    # and GL identity field to come out blank. Reuse the Validate step's
    # already-normalized datasets when available so files aren't re-parsed.
    same_upload = (st.session_state.get("v53_pos_pairs_sig")==[n for n,_ in pos_pairs]
                   and st.session_state.get("v53_gl_pairs_sig")==[n for n,_ in gl_pairs])
    if st.session_state.get("v53_validated") and same_upload:
        npos = st.session_state.v53_pos_ds
        ngl = st.session_state.v53_gl_ds
    else:
        npos=build_pos_dataset(pos_pairs)
        ngl=build_gl_dataset(gl_pairs)

    if granularity.startswith("Store + Date"):
        st.session_state.v53_pos_gl=reconcile_pos_to_gl_by_bucket(npos,ngl,tolerance,settlement_lag_days,exclude_dup_pos,exclude_dup_gl)
    else:
        st.session_state.v53_pos_gl=reconcile_pos_to_gl(npos,ngl,tolerance)

r=st.session_state.get("v53_pos_gl")
if r:
    s=r["summary"].iloc[0]
    overall=s.get("Overall Status","EXCEPTIONS REQUIRE REVIEW")
    is_bucket = "bucket_summary" in r

    if is_bucket:
        st.subheader("POS → D365 GL CONTROL")
        a,b,c=st.columns(3)
        a.metric("Files Loaded",f"{len(pos_pairs)+len(gl_pairs)}"); b.metric("POS Rows",f"{int(s['POS Rows']):,}"); c.metric("GL Rows",f"{int(s['GL Rows']):,}")
        a,b,c=st.columns(3)
        a.metric("Store-Date Buckets",f"{int(s['Store-Date Buckets']):,}")
        b.metric("Matched Buckets",f"{int(s['GL Matched Buckets']):,}")
        c.metric("Exception Buckets",f"{int(s['GL Amount Exception Buckets']):,}")
        st.caption(
            f"Accounting KPI: {int(s['GL Matched Buckets']):,} Store+Date buckets reconciled. "
            f"This is NOT a count of individual POS transactions."
        )
        a,b,c=st.columns(3)
        a.metric("GL Not Posted",f"{int(s['GL Not Posted']):,}"); b.metric("Duplicate POS Excluded",f"{int(s['Duplicate POS Rows Excluded']):,}"); c.metric("Duplicate GL Excluded",f"{int(s['Duplicate GL Rows Excluded']):,}")
        a,b,c=st.columns(3)
        a.metric("POS Total (SAR)",f"{s['POS Total (SAR)']:,.2f}"); b.metric("GL Total (SAR)",f"{s['GL Total (SAR)']:,.2f}"); c.metric("Net Difference (SAR)",f"{s['Net Difference (SAR)']:,.2f}")
        st.caption(f"Overall: {overall}")

        swaps = r["bucket_summary"][r["bucket_summary"]["Store Swap Suspected With"]!=""]
        if not swaps.empty:
            st.error(f"🔴 {len(swaps)} bucket(s) show a possible Store Code swap -- see the 'Store Date Buckets' tab, 'Store Swap Suspected With' column.")

        st.subheader("🔴 Top 20 Exceptions (by absolute SAR difference)")
        st.dataframe(r["top_exceptions"],use_container_width=True,hide_index=True)
    else:
        pos_rows=int(s.get("POS Rows",0)); gl_matched=int(s.get("GL Matched",0))
        amount_exc=int(s.get("GL Amount Exceptions",0)); not_posted=int(s.get("GL Not Posted",0))
        review=int(s.get("Review Required",0)); id_mismatch=int(s.get("Identifier Mismatch",0))
        incomplete=int(s.get("POS Data Incomplete",0)); unmatched_gl=int(s.get("Unmatched GL Rows",0))
        exceptions=amount_exc+not_posted+review+id_mismatch+incomplete
        st.subheader("Control Dashboard")
        a,b,c,d=st.columns(4)
        a.metric("Overall",overall); b.metric("POS Rows",f"{pos_rows:,}"); c.metric("GL Matched",f"{gl_matched:,}"); d.metric("Exceptions",f"{exceptions:,}")

    tab_labels=["All Results","GL Matched","Amount Exceptions","Not Posted / ID","Unmatched GL"]
    if is_bucket:
        tab_labels.append("Store Date Buckets")
    tabs=st.tabs(tab_labels)
    with tabs[0]: st.dataframe(r["detail"],use_container_width=True,hide_index=True)
    with tabs[1]: st.dataframe(r["matched"],use_container_width=True,hide_index=True)
    with tabs[2]: st.dataframe(r["exceptions"][r["exceptions"]["Status"]=="GL AMOUNT EXCEPTION"],use_container_width=True,hide_index=True)
    not_posted_statuses=["GL NOT POSTED","IDENTIFIER MISMATCH","POS DATA INCOMPLETE"]+(["GL REVIEW REQUIRED"] if not is_bucket else [])
    with tabs[3]: st.dataframe(r["exceptions"][r["exceptions"]["Status"].isin(not_posted_statuses)],use_container_width=True,hide_index=True)
    with tabs[4]: st.dataframe(r["unmatched_gl"],use_container_width=True,hide_index=True)
    if is_bucket:
        with tabs[5]:
            st.caption("One row per Store + Date bucket, sorted worst-first within each status -- the best view for spotting duplicate files or store-code swaps.")
            st.dataframe(r["bucket_summary"],use_container_width=True,hide_index=True)

    b=io.BytesIO()
    with pd.ExcelWriter(b,engine="openpyxl") as w:
        r["summary"].to_excel(w,index=False,sheet_name="Summary")
        r["detail"].to_excel(w,index=False,sheet_name="POS to GL")
        r["matched"].to_excel(w,index=False,sheet_name="GL Matched")
        r["exceptions"].to_excel(w,index=False,sheet_name="Exceptions")
        r["unmatched_gl"].to_excel(w,index=False,sheet_name="Unmatched GL")
        if is_bucket:
            r["bucket_summary"].to_excel(w,index=False,sheet_name="Store Date Buckets")
            r["top_exceptions"].to_excel(w,index=False,sheet_name="Top 20 Exceptions")
    st.download_button("DOWNLOAD POS-GL RECONCILIATION",b.getvalue(),"RetailReconAI_POS_to_GL_Reconciliation.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
else:
    st.subheader("Control Rule")
    st.markdown("### POS Statement Amount ↔ D365 GL Amount")
    st.write("Store Code and Date identify the bucket. Amount alone proves or rejects the match. Merchant ID, Provider, Terminal and Auth Code stay available as investigation detail only.")

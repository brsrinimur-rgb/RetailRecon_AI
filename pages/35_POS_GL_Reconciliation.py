import io
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

import auth
import theme
from logic.pos_gl_reconciliation import (
    build_pos_dataset,
    build_gl_dataset,
    reconcile_pos_to_gl,
    reconcile_pos_to_gl_by_bucket,
)

st.set_page_config(
    page_title="POS → D365 GL Reconciliation",
    layout="wide",
    page_icon="🧾",
)

auth.require_login({"Admin", "Finance Manager", "Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(
    theme.top_banner("RETAIL CONTROL TOWER", "POS Statement → D365 GL Reconciliation"),
    unsafe_allow_html=True,
)

st.title("🧾 POS Statement → D365 GL Reconciliation")
st.caption(
    "Bulk reconciliation: multiple POS Excel/CSV files + multiple D365 GL Excel/CSV files. "
    "Store Tender is NOT used."
)

st.info(
    "Accounting authority: POS Statement Amount ↔ D365 GL Amount. "
    "Store Code and Date establish the production reconciliation bucket. "
    "Amount is compared only after the Store+Date bucket is identified."
)


def expand_zip(uploaded_zip):
    result = []
    try:
        with zipfile.ZipFile(io.BytesIO(uploaded_zip.getvalue())) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name.lower().endswith((".xlsx", ".xls", ".csv")):
                    result.append((Path(name).name, z.read(info)))
    except zipfile.BadZipFile:
        st.error(f"Invalid ZIP file: {uploaded_zip.name}")
    return result


def collect_uploads(files, uploaded_zip):
    pairs = [(f.name, f.getvalue()) for f in (files or [])]
    if uploaded_zip is not None:
        pairs.extend(expand_zip(uploaded_zip))

    # De-duplicate by filename within this run.
    seen = set()
    result = []
    for name, data in pairs:
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append((name, data))
    return result


st.subheader("1. POS Statements — MULTIPLE FILES")
st.caption(
    "Select multiple files in the Windows picker with Ctrl/Shift, or drag several files here."
)

pos_uploads = st.file_uploader(
    "📤 UPLOAD MULTIPLE POS EXCEL / CSV FILES",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key="pos_gl_v55_pos_multi",
)

pos_zip = st.file_uploader(
    "OR UPLOAD ONE ZIP CONTAINING POS FILES",
    type=["zip"],
    accept_multiple_files=False,
    key="pos_gl_v55_pos_zip",
)

pos_pairs = collect_uploads(pos_uploads, pos_zip)

if pos_pairs:
    st.success(f"POS files loaded: {len(pos_pairs)}")
    with st.expander("View POS files"):
        for name, _ in pos_pairs:
            st.write(f"• {name}")
else:
    st.info("Upload one or multiple POS files.")


st.subheader("2. D365 GL — MULTIPLE FILES")
st.caption(
    "Select all D365 General Journal Account Entry exports together. "
    "There is no account-count limit."
)

gl_uploads = st.file_uploader(
    "📤 UPLOAD MULTIPLE D365 GL EXCEL / CSV FILES",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key="pos_gl_v55_gl_multi",
)

gl_zip = st.file_uploader(
    "OR UPLOAD ONE ZIP CONTAINING D365 GL FILES",
    type=["zip"],
    accept_multiple_files=False,
    key="pos_gl_v55_gl_zip",
)

gl_pairs = collect_uploads(gl_uploads, gl_zip)

if gl_pairs:
    st.success(f"D365 GL files loaded: {len(gl_pairs)}")
    with st.expander("View D365 GL files"):
        for name, _ in gl_pairs:
            st.write(f"• {name}")
else:
    st.info("Upload one or multiple D365 GL files.")


st.subheader("3. Matching Control")
tolerance = st.number_input(
    "Matching tolerance (SAR)",
    min_value=0.00,
    max_value=10.00,
    value=0.50,
    step=0.01,
)

granularity = st.radio(
    "Matching method",
    [
        "Store + Date bucket — RECOMMENDED",
        "Row-to-row 1:1 — diagnostic only",
    ],
    index=0,
)

if granularity.startswith("Store + Date"):
    st.caption(
        "Production method: D365 can contain many GL lines for the same Store+Date. "
        "The application compares the total POS amount with the total GL amount for that bucket."
    )
else:
    st.warning(
        "1:1 mode is diagnostic only. Real D365 exports commonly contain multiple GL lines "
        "per store/day, so this mode may produce many Review Required results."
    )


if st.button(
    "RUN POS → GL RECONCILIATION",
    type="primary",
    use_container_width=True,
):
    if not pos_pairs:
        st.error("Please upload at least one POS file.")
        st.stop()
    if not gl_pairs:
        st.error("Please upload at least one D365 GL file.")
        st.stop()

    with st.spinner("Reading and normalizing POS and D365 GL files..."):
        npos = build_pos_dataset(pos_pairs)
        ngl = build_gl_dataset(gl_pairs)

    st.subheader("Data Quality Check")

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("POS transactions", f"{len(npos):,}")
    q2.metric("GL rows", f"{len(ngl):,}")

    pos_store_pct = (
        npos["store_code"].ne("").mean() * 100 if len(npos) else 0
    )
    gl_store_pct = (
        ngl["store_code"].ne("").mean() * 100 if len(ngl) else 0
    )

    q3.metric("POS Store Code populated", f"{pos_store_pct:.1f}%")
    q4.metric("GL Store Code populated", f"{gl_store_pct:.1f}%")

    if len(npos) and pos_store_pct < 90:
        st.warning(
            "POS Store Code resolution is below 90%. Check Store Mapping Master, "
            "Merchant ID Master and Terminal ID Master before relying on the result."
        )

    if len(ngl) and gl_store_pct < 90:
        st.error(
            "D365 GL Store Code extraction is below 90%. Check the Ledger Account "
            "format in the GL export before relying on the result."
        )

    with st.spinner("Running reconciliation..."):
        if granularity.startswith("Store + Date"):
            result = reconcile_pos_to_gl_by_bucket(npos, ngl, tolerance)
        else:
            result = reconcile_pos_to_gl(npos, ngl, tolerance)

    st.session_state["pos_gl_v55_result"] = result


result = st.session_state.get("pos_gl_v55_result")

if result:
    summary = result["summary"].iloc[0]

    pos_rows = int(summary.get("POS Rows", 0))
    gl_rows = int(summary.get("GL Rows", 0))
    matched = int(summary.get("GL Matched", 0))
    amount_exc = int(summary.get("GL Amount Exceptions", 0))
    not_posted = int(summary.get("GL Not Posted", 0))
    review = int(summary.get("Review Required", 0))
    id_mismatch = int(summary.get("Identifier Mismatch", 0))
    incomplete = int(summary.get("POS Data Incomplete", 0))
    unmatched_gl = int(summary.get("Unmatched GL Rows", 0))

    exceptions = amount_exc + not_posted + review + id_mismatch + incomplete

    st.subheader("Control Dashboard")

    a, b, c, d = st.columns(4)
    a.metric("Overall Status", summary.get("Overall Status", ""))
    b.metric("POS Rows", f"{pos_rows:,}")
    c.metric("D365 GL Rows", f"{gl_rows:,}")
    d.metric("GL Matched", f"{matched:,}")

    a, b, c, d, e = st.columns(5)
    a.metric("Amount Exceptions", amount_exc)
    b.metric("GL Not Posted", not_posted)
    c.metric("Review Required", review)
    d.metric("Identifier Mismatch", id_mismatch)
    e.metric("Unmatched GL Rows", unmatched_gl)

    st.caption(
        f"Tolerance: SAR {float(summary.get('Tolerance SAR', tolerance)):.2f} | "
        f"Exceptions: {exceptions:,} | "
        f"Method: {summary.get('Match Granularity', '')}"
    )

    tabs = st.tabs(
        [
            "All Results",
            "GL Matched",
            "Amount Exceptions",
            "Not Posted / ID",
            "Unmatched GL",
        ]
    )

    with tabs[0]:
        st.dataframe(
            result["detail"],
            use_container_width=True,
            hide_index=True,
        )

    with tabs[1]:
        st.dataframe(
            result["matched"],
            use_container_width=True,
            hide_index=True,
        )

    with tabs[2]:
        st.dataframe(
            result["exceptions"][
                result["exceptions"]["Status"] == "GL AMOUNT EXCEPTION"
            ],
            use_container_width=True,
            hide_index=True,
        )

    with tabs[3]:
        st.dataframe(
            result["exceptions"][
                result["exceptions"]["Status"].isin(
                    [
                        "GL NOT POSTED",
                        "IDENTIFIER MISMATCH",
                        "POS DATA INCOMPLETE",
                    ]
                )
            ],
            use_container_width=True,
            hide_index=True,
        )

    with tabs[4]:
        st.dataframe(
            result["unmatched_gl"],
            use_container_width=True,
            hide_index=True,
        )

    export = io.BytesIO()
    with pd.ExcelWriter(export, engine="openpyxl") as writer:
        result["summary"].to_excel(writer, index=False, sheet_name="Summary")
        result["detail"].to_excel(writer, index=False, sheet_name="POS to GL")
        result["matched"].to_excel(writer, index=False, sheet_name="GL Matched")
        result["exceptions"].to_excel(writer, index=False, sheet_name="Exceptions")
        result["unmatched_gl"].to_excel(writer, index=False, sheet_name="Unmatched GL")
        if "buckets" in result:
            result["buckets"].to_excel(writer, index=False, sheet_name="Store Date Buckets")

    st.download_button(
        "DOWNLOAD POS-GL RECONCILIATION",
        data=export.getvalue(),
        file_name="RetailReconAI_POS_to_GL_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
else:
    st.subheader("Production Control Rule")
    st.markdown("### POS Statement Amount ↔ D365 GL Amount")
    st.write(
        "Production matching uses Store Code + Date as the deterministic bucket. "
        "The total POS Amount is compared with the total D365 GL Amount within the configured tolerance."
    )

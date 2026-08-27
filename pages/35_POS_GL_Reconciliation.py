import io
from pathlib import Path
import pandas as pd
import streamlit as st
import auth, theme
from logic.pos_gl_reconciliation import (
    build_pos_dataset,
    build_gl_dataset,
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
    "Daily control: upload multiple POS files and multiple D365 GL account dumps. "
    "Store Tender is not used."
)
st.info(
    "Primary accounting rule: Store Code + Date define the control bucket. "
    "POS Amount is compared with the total D365 GL clearing-account Amount for "
    "the same bucket. A single GL line is never selected by amount alone."
)

st.subheader("1. POS Statements — MULTIPLE EXCEL FILES")
st.caption(
    "Click Browse and use Ctrl/Shift to select all daily POS Excel files in one window. "
    "You can also drag multiple files into the upload area."
)
pos_uploads = st.file_uploader(
    "📤 SELECT MULTIPLE POS EXCEL FILES",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key="final_v56_pos_multi",
)
pos_pairs = [(f.name, f.getvalue()) for f in (pos_uploads or [])]

if pos_pairs:
    st.success(f"POS files loaded: {len(pos_pairs)}")
    with st.expander("View selected POS files"):
        st.write("\n".join(f"• {name}" for name, _ in pos_pairs))
else:
    st.info("No POS files selected.")

st.subheader("2. D365 GL — MULTIPLE EXCEL FILES")
st.caption(
    "Click Browse and use Ctrl/Shift to select all GL account dumps together. "
    "8, 20, 50+ files are supported."
)
gl_uploads = st.file_uploader(
    "📤 SELECT MULTIPLE D365 GL EXCEL FILES",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key="final_v56_gl_multi",
)
gl_pairs = [(f.name, f.getvalue()) for f in (gl_uploads or [])]

if gl_pairs:
    st.success(f"D365 GL files loaded: {len(gl_pairs)}")
    with st.expander("View selected D365 GL files"):
        st.write("\n".join(f"• {name}" for name, _ in gl_pairs))
else:
    st.info("No D365 GL files selected.")

tolerance = st.number_input(
    "Matching tolerance (SAR)",
    min_value=0.0,
    max_value=10.0,
    value=0.50,
    step=0.01,
)

if st.button(
    "RUN POS → GL RECONCILIATION",
    type="primary",
    use_container_width=True,
):
    if not pos_pairs:
        st.error("Please select at least one POS Excel/CSV file.")
        st.stop()
    if not gl_pairs:
        st.error("Please select at least one D365 GL Excel/CSV file.")
        st.stop()

    with st.spinner("Reading and reconciling POS and D365 GL files..."):
        npos = build_pos_dataset(pos_pairs)
        ngl = build_gl_dataset(gl_pairs)

        if npos.empty:
            st.error(
                "No usable POS transactions were extracted. Check the POS file format "
                "and header rows."
            )
            st.stop()

        if ngl.empty:
            st.error(
                "No controlled D365 GL clearing-account rows were extracted. "
                "Check the GL export and GL Control Account configuration."
            )
            st.stop()

        result = reconcile_pos_to_gl_by_bucket(
            npos,
            ngl,
            tolerance=tolerance,
            settlement_lag_days=0,
        )
        st.session_state["final_v56_pos_gl"] = result

r = st.session_state.get("final_v56_pos_gl")

if r:
    s = r["summary"].iloc[0]

    overall = s.get("Overall Status", "EXCEPTIONS REQUIRE REVIEW")
    pos_rows = int(s.get("POS Rows", 0))
    gl_rows = int(s.get("GL Rows", 0))
    gl_matched = int(s.get("GL Matched", 0))
    amount_exc = int(s.get("GL Amount Exceptions", 0))
    not_posted = int(s.get("GL Not Posted", 0))
    id_mismatch = int(s.get("Identifier Mismatch", 0))
    incomplete = int(s.get("POS Data Incomplete", 0))
    unmatched_gl = int(s.get("Unmatched GL Rows", 0))

    exceptions = amount_exc + not_posted + id_mismatch + incomplete

    st.subheader("Control Dashboard")
    a, b, c, d = st.columns(4)
    a.metric("Overall", overall)
    b.metric("POS Rows", f"{pos_rows:,}")
    c.metric("GL Rows", f"{gl_rows:,}")
    d.metric("Exceptions", f"{exceptions:,}")

    a, b, c, d, e = st.columns(5)
    a.metric("POS Rows in Matched Buckets", f"{gl_matched:,}")
    b.metric("Amount Exceptions", f"{amount_exc:,}")
    c.metric("GL Not Posted", f"{not_posted:,}")
    d.metric("Identifier / Data Issues", f"{id_mismatch + incomplete:,}")
    e.metric("Unmatched GL Rows", f"{unmatched_gl:,}")

    tabs = st.tabs(
        [
            "All Results",
            "Store-Date Buckets",
            "Matched",
            "Amount Exceptions",
            "Not Posted / Data",
            "Unmatched GL",
        ]
    )

    with tabs[0]:
        st.dataframe(r["detail"], use_container_width=True, hide_index=True)

    with tabs[1]:
        st.dataframe(
            r.get("buckets", pd.DataFrame()),
            use_container_width=True,
            hide_index=True,
        )

    with tabs[2]:
        st.dataframe(r["matched"], use_container_width=True, hide_index=True)

    with tabs[3]:
        st.dataframe(
            r["exceptions"][
                r["exceptions"]["Status"] == "GL AMOUNT EXCEPTION"
            ],
            use_container_width=True,
            hide_index=True,
        )

    with tabs[4]:
        st.dataframe(
            r["exceptions"][
                r["exceptions"]["Status"].isin(
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

    with tabs[5]:
        st.dataframe(
            r["unmatched_gl"],
            use_container_width=True,
            hide_index=True,
        )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        r["summary"].to_excel(writer, index=False, sheet_name="Summary")
        r["buckets"].to_excel(writer, index=False, sheet_name="Store Date Buckets")
        r["detail"].to_excel(writer, index=False, sheet_name="POS to GL")
        r["matched"].to_excel(writer, index=False, sheet_name="GL Matched")
        r["exceptions"].to_excel(writer, index=False, sheet_name="Exceptions")
        r["unmatched_gl"].to_excel(writer, index=False, sheet_name="Unmatched GL")

    st.download_button(
        "DOWNLOAD POS-GL RECONCILIATION",
        output.getvalue(),
        "RetailReconAI_POS_to_GL_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
else:
    st.subheader("Final Control Rule")
    st.markdown("### Store Code + Date → POS Amount vs D365 GL Amount")
    st.write(
        "Store Code and Date define the reconciliation bucket. "
        "POS Amount is compared with the aggregated D365 GL clearing-account amount. "
        "Provider is used only internally to prevent mixing different D365 clearing "
        "accounts; Merchant ID, Terminal ID, Auth Code, Reference and Store Tender "
        "are not required for the POS → GL accounting match."
    )

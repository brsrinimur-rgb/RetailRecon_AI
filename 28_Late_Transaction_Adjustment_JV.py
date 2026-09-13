import pandas as pd
import streamlit as st
import auth, theme, db
from logic import adjustment_bulk_extension as bulk_adj

st.set_page_config(page_title="Late Transaction Adjustment JV", layout="wide")
auth.require_login({"Admin", "Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "Late Transaction Adjustment JV"), unsafe_allow_html=True)
st.title("Late Transaction Adjustment JV")
st.caption("Use only after period close when previously missing transactions arrive. "
           "Original period remains locked; correction is recorded through an adjustment/reversal JV.")

ctrl = db.load_accounting_period_control("ULC")
st.info(
    f"Closed through: {ctrl.get('Closed Through Date') or 'Not set'} | "
    f"Next open accounting date: {ctrl.get('Next Open Date') or 'Not set'}"
)

# ---------------------------------------------------------------------------
# V58 additive: bulk adjustment JV creation from an uploaded file.
# The single-row form below (unchanged) still works exactly as before for a
# one-off adjustment. This section is for creating many adjustment JVs at
# once -- e.g. a batch of "Missing D365" exceptions -- without retyping each
# one by hand. It never touches D365 or auto-approves anything: every row
# still lands in the same `adjustments` table with status "PENDING APPROVAL",
# exactly like a manually entered one. Data-shaping logic lives in
# logic/adjustment_bulk_extension.py so it can be unit-tested without
# Streamlit.
# ---------------------------------------------------------------------------
with st.expander("Bulk create adjustment JVs from a file", expanded=False):
    st.caption(
        "Upload either a simple Store/Provider/Amount/Reason file, or a reconciliation "
        "exceptions export (Store Code, Auth Code, POS Tender, Net Amount, ...) -- both are "
        "recognized automatically. Review and edit the table below, then create. Each row "
        "becomes its own adjustment JV with status PENDING APPROVAL, same as the manual form."
    )
    bulk_file = st.file_uploader(
        "Upload adjustment batch (.xlsx or .csv)", type=["xlsx", "csv"], key="bulk_adjustment_upload"
    )

    if bulk_file is not None:
        try:
            bulk_raw = (
                pd.read_csv(bulk_file, dtype=str)
                if bulk_file.name.lower().endswith(".csv")
                else pd.read_excel(bulk_file, dtype=str)
            )
        except Exception as e:
            bulk_raw = None
            st.error(f"Could not read the uploaded file: {e}")

        if bulk_raw is not None and not bulk_raw.empty:
            preview = bulk_adj.build_bulk_preview(bulk_raw)
            st.caption(f"{len(preview)} row(s) parsed from the upload. Uncheck any row to exclude it.")
            edited = st.data_editor(
                preview,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key="bulk_adjustment_editor",
                column_config={
                    "Provider": st.column_config.SelectboxColumn(options=bulk_adj.VALID_PROVIDERS),
                    "Amount": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            if st.button("CREATE ALL INCLUDED ADJUSTMENT JVS", type="primary", use_container_width=True):
                created, skipped = 0, []
                for i, r in edited.iterrows():
                    if not bool(r["Include"]):
                        continue
                    store = str(r["Store"]).strip()
                    provider = str(r["Provider"]).strip()
                    amt = float(r["Amount"]) if pd.notna(r["Amount"]) else 0.0
                    reason = str(r["Reason"]).strip()
                    if not store or not reason or amt == 0:
                        skipped.append((i + 1, store or "(blank store)", "Store, amount and reason are required"))
                        continue
                    db.append_adjustment(store, provider, amt, reason, st.session_state.user["username"])
                    created += 1

                if created:
                    st.success(f"Created {created} adjustment JV(s).")
                if skipped:
                    st.warning(
                        "Skipped " + str(len(skipped)) + " row(s): "
                        + "; ".join(f"row {n} ({s}) - {msg}" for n, s, msg in skipped)
                    )
                if created:
                    st.rerun()
        elif bulk_raw is not None:
            st.warning("The uploaded file has no rows.")

st.divider()

store = st.text_input("Store Code")
provider = st.selectbox("Provider", bulk_adj.VALID_PROVIDERS)
amt = st.number_input("Adjustment Amount", value=0.0, step=1.0)
reason = st.text_area("Reason / Case reference")
if st.button("CREATE ADJUSTMENT JV", type="primary"):
    if not store or not reason or amt == 0:
        st.error("Store, amount and reason are required.")
    else:
        db.append_adjustment(store, provider, amt, reason, st.session_state.user["username"])
        st.success("Adjustment JV created.")
        st.rerun()

st.dataframe(db.load_adjustments(), use_container_width=True, hide_index=True)

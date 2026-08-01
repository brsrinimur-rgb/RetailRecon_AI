import streamlit as st
import pandas as pd
import auth, theme, core, db

st.set_page_config(page_title="JV Creation", layout="wide")
auth.require_login({"Admin", "Finance Manager", "Finance Maker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "JV Creation"), unsafe_allow_html=True)

st.title("JV Creation")

st.info(
    "Confirmed D365 mapping: Bank 1015 | Commission 7231 | VAT Vendor P0672 | "
    "CC (MADA+VISA+MASTERCARD) 11020907 | AMEX 11020901 | "
    "TABBY 11020913 | TAMARA 11020922 | TAP 11020904. "
    "Each of AMEX/TABBY/TAMARA/TAP remains a separate weekly JV."
)

r = st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

st.caption(
    "Only matched transactions within the approved SAR 1 tolerance AND bank-settled transactions are eligible. "
    "CARD = MADA + VISA + MASTERCARD; AMEX / TABBY / TAMARA / TAP remain separate. "
    "Commission is calculated transaction-by-transaction before weekly store aggregation."
)

if st.button("CREATE WEEKLY STORE JVs", type="primary"):
    gl_config = db.load_gl_config()
    j = core.create_jv(
        r["matched"],
        gl_config,
        db.load_commission_rate_master()
    )
    # Hard control gate: every batch is validated against the Finance-confirmed
    # chart of accounts and dimension format BEFORE it is saved. Approval and
    # D365 Posting Center both refuse to act on a batch that failed here.
    j = core.validate_jv(j, gl_config)
    db.replace_jv(j)
    n_batches = j['Journal Batch'].nunique() if not j.empty else 0
    n_failed = j.loc[~j["Validation Passed"], "Journal Batch"].nunique() if not j.empty else 0
    if n_failed:
        st.error(
            f"Created {n_batches} JV batches, but {n_failed} failed D365 validation and are "
            "BLOCKED from approval/posting. See Validation Errors below."
        )
    else:
        st.success(f"Created {n_batches} JV batches, all passed D365 validation, saved to the shared database.")

j = db.load_jv()

if not j.empty:
    preferred = [
        "Valid","Company accounts","Journal batch number","RecId","Line number","Date",
        "Account type","Main Account","Ledger Dimension","Default Dimension","Location",
        "Brand Dimension","Department","Currency","Exchange rate",
        "Debit","Credit","Description","Difference","Balanced",
        "Validation Passed","Validation Date","Mapping Version","Validated By/System","Validation Errors",
        "Approval Status","D365 Status","Voucher"
    ]
    show_cols=[c for c in preferred if c in j.columns]
    st.dataframe(j[show_cols] if show_cols else j, use_container_width=True, hide_index=True)

    if "Balanced" in j.columns and (~j["Balanced"].astype(bool)).any():
        st.error("Unbalanced JV detected. Posting is blocked.")

    if (pd.to_numeric(j["Debit"],errors="coerce").fillna(0)<0).any() or (pd.to_numeric(j["Credit"],errors="coerce").fillna(0)<0).any():
        st.error("Negative debit/credit line detected. Posting is blocked.")

    if "Validation Passed" in j.columns and (~j["Validation Passed"].astype(bool)).any():
        failed = j.loc[~j["Validation Passed"].astype(bool), ["Journal Batch","Validation Errors"]].drop_duplicates()
        st.error("The following batches failed D365 chart-of-accounts validation and are BLOCKED from approval/posting:")
        st.dataframe(failed, use_container_width=True, hide_index=True)
else:
    st.info("No JV batches yet. Click CREATE WEEKLY STORE JVs above.")

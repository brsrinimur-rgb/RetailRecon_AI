import streamlit as st
import auth, theme, db

st.set_page_config(page_title="Exception Correction Center", layout="wide")
auth.require_login({"Admin", "Finance Manager", "Finance Maker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "Exception Correction Center"), unsafe_allow_html=True)
st.title("Exception Correction Center")

r = st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

u = r["unmatched_sales"].copy()
st.dataframe(u, use_container_width=True, hide_index=True)
if not u.empty:
    row = st.number_input("D365 Row to correct", min_value=1, value=int(u.iloc[0]["D365 Row"]), step=1)
    new_auth = st.text_input("Corrected Auth Code")
    reason = st.text_area("Reason / Evidence Reference")
    if st.button("SUBMIT CORRECTION", type="primary"):
        if not reason.strip():
            st.error("Reason is mandatory.")
        else:
            db.append_correction_log(row, new_auth, reason, st.session_state.user["username"])
            st.success("Correction submitted with original-value audit trail.")
            st.rerun()

st.dataframe(db.load_correction_log(), use_container_width=True, hide_index=True)

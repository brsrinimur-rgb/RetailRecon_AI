import streamlit as st
import auth, theme, db

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
store = st.text_input("Store Code")
provider = st.selectbox("Provider", ["CARD", "AMEX", "TABBY", "TAMARA", "TAP"])
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

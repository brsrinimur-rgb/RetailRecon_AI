import pandas as pd
import streamlit as st
import auth, theme, db

st.set_page_config(page_title="Accounting Period Control", layout="wide")
auth.require_login({"Admin","Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Accounting Period / Close Control"), unsafe_allow_html=True)
st.title("Accounting Period Control")

st.info(
    "Closing July does not cancel July transactions. The original Source Date and Source Period stay July. "
    "If settlement is received later, the JV can use the next open D365 Accounting Date in August."
)

entity = st.selectbox("Legal Entity", ["ULC"])
ctrl = db.load_accounting_period_control(entity)

c1,c2,c3 = st.columns(3)
c1.metric("Closed Through", ctrl["Closed Through Date"] or "Not set")
c2.metric("Next Open Date", ctrl["Next Open Date"] or "Not set")
c3.metric("Status", ctrl["Status"])

closed_old = pd.to_datetime(ctrl["Closed Through Date"], errors="coerce")
open_old = pd.to_datetime(ctrl["Next Open Date"], errors="coerce")

closed = st.date_input(
    "Close Through Date",
    value=closed_old.date() if pd.notna(closed_old) else pd.Timestamp.today().date()
)
next_open = st.date_input(
    "Next Open Accounting Date",
    value=open_old.date() if pd.notna(open_old) else (pd.Timestamp(closed)+pd.Timedelta(days=1)).date()
)
status = st.selectbox("Status", ["CLOSED / NEXT PERIOD OPEN","OPEN"])
reason = st.text_area("Reason / Close Reference")

if st.button("SAVE ACCOUNTING PERIOD CONTROL", type="primary", use_container_width=True):
    try:
        db.save_accounting_period_control(
            entity, closed, next_open, status,
            st.session_state.user["username"], reason
        )
        st.success("Accounting period control saved with audit trail.")
        st.rerun()
    except Exception as e:
        st.error(str(e))

st.code(
    "Example\n"
    "Source Date: 31-Jul-2026\n"
    "Closed Through: 31-Jul-2026\n"
    "Next Open: 01-Aug-2026\n"
    "Source Period: Jul-2026\n"
    "JV Accounting Date: 01-Aug-2026"
)

with st.expander("Accounting period audit trail"):
    st.dataframe(db.load_accounting_period_audit(entity), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Operational Close Calendar")
cal = db.load_close_calendar()
edit = st.data_editor(cal.drop(columns=["id"]), use_container_width=True, num_rows="fixed", hide_index=True)
if st.button("SAVE OPERATIONAL CLOSE CALENDAR"):
    edit["id"] = cal["id"].values
    db.save_close_calendar(edit)
    st.success("Close calendar saved.")
    st.rerun()

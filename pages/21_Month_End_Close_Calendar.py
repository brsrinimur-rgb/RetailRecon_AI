import streamlit as st
import auth, theme, db

st.set_page_config(page_title="Month End Close Calendar", layout="wide")
auth.require_login({"Admin", "Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "Month End Close Calendar"), unsafe_allow_html=True)
st.title("Month End Close Calendar")

cal = db.load_close_calendar()
edit = st.data_editor(
    cal.drop(columns=["id"]),
    use_container_width=True,
    num_rows="fixed",
    hide_index=True,
)
if st.button("SAVE CLOSE CALENDAR", type="primary"):
    edit["id"] = cal["id"].values
    db.save_close_calendar(edit)
    st.success("Close calendar saved.")
    st.rerun()

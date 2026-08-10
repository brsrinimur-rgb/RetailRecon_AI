import streamlit as st
import auth, theme, db

st.set_page_config(page_title="D365 Posting Verification", layout="wide")
auth.require_login({"Admin", "Finance Manager", "Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "D365 Posting Verification"), unsafe_allow_html=True)
st.title("D365 Posting Verification")

j = db.load_jv()
if j.empty:
    st.info("No JV available.")
    st.stop()

posted = j[j["D365 Status"] == "POSTED"]
c1, c2 = st.columns(2)
c1.metric("Posted Batches", posted["Journal Batch"].nunique())
c2.metric("Verified Balanced", posted[posted["Balanced"]]["Journal Batch"].nunique())
st.dataframe(posted, use_container_width=True, hide_index=True)

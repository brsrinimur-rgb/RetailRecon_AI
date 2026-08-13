import streamlit as st
import auth, theme

st.set_page_config(page_title="Retail Control Tower",layout="wide",page_icon="🏬")
auth.require_login()
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","POS Reconciliation → POS-to-GL Control Center"),unsafe_allow_html=True)
st.title("Finance Control Tower")
st.caption("Reconcile → Validate → Settle → Correct → Close → Configure GL → Create JV → Approve → Post to D365 → Verify.")

c1,c2,c3=st.columns(3)
c1.metric("Control Model","POS → Bank → GL")
c2.metric("Tolerance","SAR 1.00")
c3.metric("Posting","Maker-Checker")

st.page_link("pages/1_POS_Reconciliation.py",label="Open POS Reconciliation",icon="🧾")
st.page_link("pages/29_AI_Finance_Copilot.py",label="Open AI Finance Copilot",icon="🤖")

st.page_link("pages/30_D365_GL_Reconciliation.py",label="Open D365 GL Reconciliation",icon="📚")

st.page_link("pages/18_Settlement_Batch_Engine.py",label="Open Settlement Batch Engine",icon="💰")

st.page_link("pages/31_Database_Health.py",label="Database Health & Migration",icon="🩺")

st.page_link("pages/32_System_Logic_Health.py",label="System Logic Health",icon="🧩")

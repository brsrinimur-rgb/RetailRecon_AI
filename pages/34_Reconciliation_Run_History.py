import streamlit as st
import pandas as pd
import auth,theme,db

st.set_page_config(page_title="Reconciliation Run History",layout="wide",page_icon="🗂️")
auth.require_login({"Admin","Finance Manager","Finance Checker","Finance Maker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Reconciliation Run History"),unsafe_allow_html=True)

st.title("🗂️ Reconciliation Run History")
st.caption(
    "Every completed reconciliation is stored as a separate Run ID. Loading an old run does not delete newer runs."
)

runs=db.list_reconciliation_runs(200)
if runs.empty:
    st.info("No saved reconciliation runs yet.")
    st.stop()

st.dataframe(runs,use_container_width=True,hide_index=True)

run_id=st.selectbox("Select Run ID",runs["Run ID"].astype(str).tolist())
if st.button("LOAD SELECTED RUN",type="primary",use_container_width=True):
    result=db.load_reconciliation_run(run_id)
    if not result:
        st.error("Selected run could not be loaded.")
    else:
        st.session_state["ct_result"]=result
        st.session_state["current_reconciliation_run_id"]=run_id
        st.success(f"Loaded {run_id}. All report pages now use this historical run.")

if st.session_state.get("current_reconciliation_run_id"):
    st.info(f"Current active reconciliation run: {st.session_state['current_reconciliation_run_id']}")

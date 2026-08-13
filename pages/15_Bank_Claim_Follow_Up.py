import pandas as pd,streamlit as st
import auth,theme
st.set_page_config(page_title="Bank Claim Follow Up",layout="wide")
auth.require_login({"Admin","Finance Manager"});auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True);st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Bank Claim Follow Up"),unsafe_allow_html=True)
st.title("Bank Claim Follow Up")
r=st.session_state.get("ct_result")
if not r:st.info("Run POS Reconciliation first.");st.stop()
m=r["matched"];openx=m[~m["Bank Settled"]].copy()
if not openx.empty:
    openx["Owner"]="Treasury";openx["Claim Status"]="OPEN";openx["Aging Days"]=(pd.Timestamp.today().normalize()-pd.to_datetime(openx["Posting Date"],errors="coerce")).dt.days
st.dataframe(openx,use_container_width=True,hide_index=True)

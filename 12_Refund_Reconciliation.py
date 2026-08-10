import pandas as pd,streamlit as st
import auth,theme
st.set_page_config(page_title="Refund Reconciliation",layout="wide")
auth.require_login({"Admin","Finance Manager"});auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True);st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Refund Reconciliation"),unsafe_allow_html=True)
st.title("Refund Reconciliation")
u=st.file_uploader("Upload refund / reversal file",type=["xlsx","xls","csv"])
st.info("Refunds are kept separate from normal sales settlement and require provider/bank evidence before closure.")
if u:
    d=pd.read_csv(u) if u.name.lower().endswith(".csv") else pd.read_excel(u)
    st.dataframe(d,use_container_width=True,hide_index=True)

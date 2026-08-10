import pandas as pd, streamlit as st
import auth,theme
st.set_page_config(page_title="Bank Settlement Audit",layout="wide")
auth.require_login({"Admin","Finance Manager","Finance Checker"});auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True);st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Bank Settlement Audit"),unsafe_allow_html=True)
st.title("Bank Settlement Audit")
r=st.session_state.get("ct_result")
if not r: st.info("Run POS Reconciliation first."); st.stop()
m=r["matched"].copy()
m["Delay Bucket"]=pd.cut(m["Settlement Delay Days"],bins=[-999,1,2,3,999],labels=["T+0/T+1","T+2","T+3",">T+3"])
c1,c2,c3=st.columns(3);c1.metric("Settled",int(m["Bank Settled"].sum()));c2.metric("Awaiting",int((~m["Bank Settled"]).sum()));c3.metric("Open Net",f"SAR {m.loc[~m['Bank Settled'],'Net Amount'].sum():,.2f}")
st.dataframe(m,use_container_width=True,hide_index=True)

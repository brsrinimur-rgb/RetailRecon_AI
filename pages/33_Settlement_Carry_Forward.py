import pandas as pd
import streamlit as st
import auth,theme
from logic.carry_forward_extension import build_settlement_carry_forward,monthly_carry_forward_summary

st.set_page_config(page_title="Settlement Carry Forward",layout="wide",page_icon="↪️")
auth.require_login({"Admin","Finance Manager","Finance Checker","Finance Maker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Settlement Carry Forward"),unsafe_allow_html=True)

st.title("↪️ Settlement Carry Forward")
st.caption(
    "Unsettled transactions remain in their original sales period and carry forward until the bank receipt is verified. "
    "A later receipt changes the resolution period, never the original transaction period."
)

r=st.session_state.get("ct_result")
if not r:
    st.info("Run or load a reconciliation first.")
    st.stop()

matched=r.get("matched",pd.DataFrame())
if matched is None or matched.empty:
    st.info("No matched transactions available.")
    st.stop()

dates=pd.to_datetime(matched.get("Date"),errors="coerce").dropna()
if dates.empty:
    st.error("No usable transaction dates.")
    st.stop()

default_end=dates.max().date()
period_end=st.date_input("Month-End / Period-End Date",value=default_end)

cf=build_settlement_carry_forward(matched,pd.Timestamp(period_end),None)
if cf.empty:
    st.success("No settlement carry-forward items for this period end.")
    st.stop()

open_mask=cf.get("Carry Forward Status","").astype(str).eq("OPEN - CARRY FORWARD")
settled_next=cf.get("Carry Forward Status","").astype(str).eq("SETTLED IN NEXT PERIOD")
outstanding=pd.to_numeric(cf.get("Outstanding Amount",0),errors="coerce").fillna(0.0)

c1,c2,c3,c4=st.columns(4)
c1.metric("Carry Forward Rows",len(cf))
c2.metric("Open Carry Forward",int(open_mask.sum()))
c3.metric("Settled in Next Period",int(settled_next.sum()))
c4.metric("Closing Outstanding",f"SAR {outstanding.sum():,.2f}")

st.markdown("### Detailed Carry Forward")
preferred=[
    "Store Code","Store Name","Original Transaction Date","Original Period",
    "Carry Forward Period","Resolution Period","Carry Forward Status",
    "Payment Type","Receipt ID","Auth Code","D365 Amount","Outstanding Amount",
    "Bank Settled","Settlement Bank Date","Settlement Batch ID","Settlement Match Rule"
]
show=[c for c in preferred if c in cf.columns]
st.dataframe(cf[show] if show else cf,use_container_width=True,hide_index=True)

st.markdown("### Monthly Carry Forward Summary")
summ=monthly_carry_forward_summary(cf)
st.dataframe(summ,use_container_width=True,hide_index=True)

st.info(
    "Control equation: Opening Carry Forward + Current Period Open Items − Settled During Period = Closing Carry Forward."
)

import pandas as pd
import streamlit as st
import auth,theme

st.set_page_config(page_title="Bank Settlement Audit",layout="wide")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Bank Settlement Audit"),unsafe_allow_html=True)

st.title("Bank Settlement Audit")
st.caption(
    "Accounting proof: POS/provider settlement evidence → actual bank receipt → transaction-level settlement status. "
    "For ANB card settlements, POS batch amount must equal the ANB bank credit; commission and VAT are separate debit evidence."
)

r=st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

m=r.get("matched",pd.DataFrame()).copy()
if m.empty:
    st.info("No matched transactions in the active reconciliation.")
    st.stop()

if "Bank Settled" not in m.columns:
    m["Bank Settled"]=False
m["Bank Settled"]=m["Bank Settled"].fillna(False).astype(bool)

if "Settlement Delay Days" in m.columns:
    delay=pd.to_numeric(m["Settlement Delay Days"],errors="coerce")
else:
    pos_date=pd.to_datetime(m.get("POS Date",m.get("Date")),errors="coerce")
    bank_date=pd.to_datetime(m.get("Settlement Bank Date",m.get("Bank Date")),errors="coerce")
    delay=(bank_date-pos_date).dt.days
    m["Settlement Delay Days"]=delay

m["Delay Bucket"]=pd.cut(
    pd.to_numeric(m["Settlement Delay Days"],errors="coerce"),
    bins=[-999,1,2,3,999],
    labels=["T+0/T+1","T+2","T+3",">T+3"]
)

amt_col="D365 Amount" if "D365 Amount" in m.columns else "Net Amount"
amounts=pd.to_numeric(m.get(amt_col,0),errors="coerce").fillna(0.0)

c1,c2,c3,c4=st.columns(4)
c1.metric("Settled Transactions",int(m["Bank Settled"].sum()))
c2.metric("Awaiting Bank Receipt",int((~m["Bank Settled"]).sum()))
c3.metric("Settled Amount",f"SAR {amounts[m['Bank Settled']].sum():,.2f}")
c4.metric("Open / Carry Forward Amount",f"SAR {amounts[~m['Bank Settled']].sum():,.2f}")

st.markdown("### Settlement Evidence")
evidence_cols=[
    "Store Code","Store Name","Date","POS Date","Payment Type","Terminal ID",
    "Unique Transaction ID","Receipt ID","Auth Code","D365 Amount","POS Amount",
    "Settlement Batch ID","Settlement Stage","Bank Settled","Settlement Match Rule",
    "Settlement Bank Date","Settlement Bank Amount","Settlement Bank Reference",
    "Settlement Evidence Source","Settlement Delay Days","Delay Bucket"
]
show=[c for c in evidence_cols if c in m.columns]
st.dataframe(m[show] if show else m,use_container_width=True,hide_index=True)

batches=r.get("settlement_batches",pd.DataFrame())
if batches is not None and not batches.empty:
    st.markdown("### Batch-Level Bank Proof")
    batch_cols=[
        "Store Code","Provider","Payment Type","Terminal ID","Settlement Date",
        "Transaction Count","POS Batch Amount","Expected Bank Amount",
        "Actual Bank Amount","ANB Commission","ANB VAT","Net Bank Movement",
        "Bank Difference","Settlement Status","Bank Match Rule",
        "Bank Date","Bank Source File","Bank Source Sheet","Bank Source Row","Bank Reference",
        "Settlement Review Reason"
    ]
    bshow=[c for c in batch_cols if c in batches.columns]
    st.dataframe(batches[bshow] if bshow else batches,use_container_width=True,hide_index=True)

st.markdown("### Settlement Status Summary")
summary=(
    m.groupby(["Store Code","Payment Type","Bank Settled"],dropna=False)
    .agg(Transactions=(amt_col,"size"),Amount=(amt_col,"sum"))
    .reset_index()
)
summary["Amount"]=pd.to_numeric(summary["Amount"],errors="coerce").fillna(0.0)
st.dataframe(summary,use_container_width=True,hide_index=True)

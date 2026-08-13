import streamlit as st
import pandas as pd
import auth, theme, core

st.set_page_config(page_title="Settlement Batch Engine",layout="wide",page_icon="💰")
auth.require_login({"Admin","Finance Manager","Finance Checker","Finance Maker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Settlement Batch Engine"),unsafe_allow_html=True)

st.title("💰 Settlement Batch Engine")
st.caption(
    "Transaction Match → Provider/POS Settlement Batch → Bank Receipt → Settlement Propagation → JV Eligibility"
)

r=st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

matched=r.get("matched",pd.DataFrame()).copy()
if matched.empty:
    st.warning("No matched transactions are available.")
    st.stop()

st.markdown("### 1. Build Card/AMEX Settlement Batches")
card_batches=core.build_card_settlement_batches(matched)
if card_batches.empty:
    st.info("No card/AMEX matched transactions available for batch construction.")
else:
    st.dataframe(card_batches,use_container_width=True,hide_index=True)

st.markdown("### 2. Upload Provider Payout / Bank Evidence")
provider_files=st.file_uploader(
    "Upload Tabby/Tamara/TAP payout files and bank statements",
    type=["xlsx","xls","csv"],
    accept_multiple_files=True
)

tabby_fee=st.number_input("Tabby fixed payout-level deduction (SAR)",0.0,100.0,5.0,0.5)
tol=st.number_input("Settlement-to-bank tolerance (SAR)",0.0,10.0,1.0,0.01)

if st.button("RUN SETTLEMENT BATCH CONTROL",type="primary",use_container_width=True):
    payout_parts=[]
    bank_parts=[]
    quarantine=[]

    for f in provider_files or []:
        try:
            sheets=core.read_upload(f)
        except Exception as e:
            quarantine.append({"File":f.name,"Sheet":"","Reason":str(e)})
            continue

        for sheet,df in sheets.items():
            try:
                typ=core.classify_settlement_source(f.name,df)
                if typ=="TAMARA_PAYOUT":
                    x=core.normalize_tamara_payout(df,f.name)
                    if not x.empty:payout_parts.append(x)
                elif typ=="TABBY_PAYOUT":
                    x=core.normalize_tabby_payout(df,f.name)
                    if not x.empty:payout_parts.append(x)
                elif typ=="TAP_PAYOUT":
                    x=core.normalize_tap_payout(df,f.name)
                    if not x.empty:payout_parts.append(x)
                else:
                    # Try bank normalization if the file resembles a bank statement.
                    try:
                        x=core.normalize_bank(df,f.name)
                        if x is not None and not x.empty:
                            x["Detected Bank"]=core.detect_bank_name(f.name,df)
                            bank_parts.append(x)
                        else:
                            quarantine.append({"File":f.name,"Sheet":sheet,"Reason":"Unsupported settlement/payout format"})
                    except Exception:
                        quarantine.append({"File":f.name,"Sheet":sheet,"Reason":"Unsupported settlement/payout format"})
            except Exception as e:
                quarantine.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})

    provider_batches=pd.concat(payout_parts,ignore_index=True) if payout_parts else pd.DataFrame()
    all_batches=pd.concat([x for x in [card_batches,provider_batches] if x is not None and not x.empty],ignore_index=True) if (not card_batches.empty or not provider_batches.empty) else pd.DataFrame()
    bank=pd.concat(bank_parts,ignore_index=True) if bank_parts else r.get("bank",pd.DataFrame())

    batch_result,bank_unmatched=core.reconcile_settlement_batches_to_bank(
        all_batches,bank,tol,tabby_fee
    )

    updated=core.propagate_batch_settlement_to_matched(matched,batch_result)
    r["matched"]=updated
    r["settlement_batches"]=batch_result
    r["settlement_bank_unmatched"]=bank_unmatched
    r["settlement_quarantine"]=pd.DataFrame(quarantine)
    r["settlement_stage_summary"]=core.settlement_stage_summary(updated)
    st.session_state["ct_result"]=r

    received=int((batch_result["Settlement Status"]=="BANK RECEIVED").sum()) if not batch_result.empty else 0
    pending=int((batch_result["Settlement Status"]=="BANK RECEIPT PENDING").sum()) if not batch_result.empty else 0
    review=int((batch_result["Settlement Status"]=="BANK REVIEW REQUIRED").sum()) if not batch_result.empty else 0

    st.success(
        f"Settlement control completed: {received} batch(es) BANK RECEIVED, "
        f"{pending} pending, {review} review-required."
    )

res=st.session_state.get("ct_result",{})
batches=res.get("settlement_batches",pd.DataFrame())
stage=res.get("settlement_stage_summary",pd.DataFrame())

if not batches.empty:
    st.markdown("### Settlement Batch Results")
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Batches",len(batches))
    m2.metric("Bank Received",int((batches["Settlement Status"]=="BANK RECEIVED").sum()))
    m3.metric("Bank Pending",int((batches["Settlement Status"]=="BANK RECEIPT PENDING").sum()))
    m4.metric("Review Required",int((batches["Settlement Status"]=="BANK REVIEW REQUIRED").sum()))

    tabs=st.tabs(["Settlement Batches","Settlement Stage Summary","Unmatched Bank Credits","Quarantine"])
    with tabs[0]:
        st.dataframe(batches,use_container_width=True,hide_index=True)
    with tabs[1]:
        st.dataframe(stage,use_container_width=True,hide_index=True)
    with tabs[2]:
        st.dataframe(res.get("settlement_bank_unmatched",pd.DataFrame()),use_container_width=True,hide_index=True)
    with tabs[3]:
        st.dataframe(res.get("settlement_quarantine",pd.DataFrame()),use_container_width=True,hide_index=True)
else:
    st.info("Build and run settlement batches to populate settlement status.")

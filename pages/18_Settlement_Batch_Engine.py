import streamlit as st
import pandas as pd
import auth, theme, core
from logic import bank_settlement_extension as bank_ext

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
    amex_batch_count=int((card_batches.get("Provider","").astype(str).str.upper()=="AMEX").sum())
    if amex_batch_count:
        st.caption(
            f"{amex_batch_count} AMEX settlement batch(es) above settle differently from ANB card "
            "batches -- AMEX pays as a company-level wire, not a per-terminal/per-day bank credit. "
            "Upload the AMEX Statement of Account below to match them against AMEX's own submission "
            "ledger; without it they remain BANK RECEIPT PENDING like today."
        )

st.markdown("### 2. Upload Provider Payout / Bank Evidence")
provider_files=st.file_uploader(
    "Upload Tabby/Tamara/TAP payout files, AMEX Statement of Account, and bank statements",
    type=["xlsx","xls","csv"],
    accept_multiple_files=True
)

tabby_fee=st.number_input("Tabby fixed payout-level deduction (SAR)",0.0,100.0,5.0,0.5)
tol=st.number_input("Settlement-to-bank tolerance (SAR)",0.0,10.0,1.0,0.01)
settlement_lag_days=st.number_input(
    "Extra ANB settlement lag (days, on top of existing 0-3 day window)",
    0,10,0,1,
    help="Widens how many additional days beyond the standard 0-3 day window a bank "
         "credit is still considered for a POS batch. Use this if a specific statement "
         "shows receipts consistently posting later than 3 days after the transaction date. "
         "0 leaves matching exactly as before."
)

if st.button("RUN SETTLEMENT BATCH CONTROL",type="primary",use_container_width=True):
    payout_parts=[]
    bank_parts=[]
    quarantine=[]
    amex_payment_parts=[]
    amex_submission_parts=[]

    for f in provider_files or []:
        try:
            sheets=core.read_upload(f)
        except Exception as e:
            quarantine.append({"File":f.name,"Sheet":"","Reason":str(e)})
            continue

        for sheet,df in sheets.items():
            try:
                if core.is_amex_statement_file(f.name,df):
                    amex_pay,amex_subs=core.normalize_amex_statement(df,f.name)
                    if amex_pay is not None and not amex_pay.empty:amex_payment_parts.append(amex_pay)
                    if amex_subs is not None and not amex_subs.empty:amex_submission_parts.append(amex_subs)
                    continue
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
                        x=bank_ext.normalize_bank_statement(df,f.name)
                        if x is None or x.empty:
                            x=core.normalize_bank(
                                df,f.name,source_file=f.name,source_sheet=sheet
                            )
                        if x is not None and not x.empty:
                            x["Bank Source File"]=f.name
                            x["Bank Source Sheet"]=sheet
                            if "Bank Source Row" not in x.columns:
                                x["Bank Source Row"]=range(1,len(x)+1)
                            bank_parts.append(x)
                        else:
                            quarantine.append({"File":f.name,"Sheet":sheet,"Reason":"Unsupported settlement/payout format"})
                    except Exception:
                        quarantine.append({"File":f.name,"Sheet":sheet,"Reason":"Unsupported settlement/payout format"})
            except Exception as e:
                quarantine.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})

    provider_batches=pd.concat(payout_parts,ignore_index=True) if payout_parts else pd.DataFrame()
    if provider_batches is not None and not provider_batches.empty:
        provider_batches=core.link_tabby_payout_underlying_ids(provider_batches,matched)

    all_batches=pd.concat(
        [x for x in [card_batches,provider_batches] if x is not None and not x.empty],
        ignore_index=True
    ) if (not card_batches.empty or not provider_batches.empty) else pd.DataFrame()
    bank=pd.concat(bank_parts,ignore_index=True) if bank_parts else r.get("bank",pd.DataFrame())

    amex_payments_all=pd.concat(amex_payment_parts,ignore_index=True) if amex_payment_parts else pd.DataFrame()
    amex_submissions_all=pd.concat(amex_submission_parts,ignore_index=True) if amex_submission_parts else pd.DataFrame()

    # AMEX settles as a company-level wire, not a per-terminal/per-day bank
    # credit -- it cannot be resolved by the ANB card matcher below, so it is
    # split out and resolved separately against AMEX's own statement
    # (finalize_amex_batches, V71). This split changes nothing about how
    # MADA/VISA/MASTERCARD ("ANB POS") batches are matched: those batches
    # never received an AMEX candidate anyway, so removing AMEX rows from
    # this call cannot change which bank credit any of them consumes.
    if not card_batches.empty and "Provider" in card_batches.columns:
        _is_amex=card_batches["Provider"].astype(str).str.upper().eq("AMEX")
        amex_card_batches=card_batches[_is_amex].copy()
        other_card_batches=card_batches[~_is_amex].copy()
    else:
        amex_card_batches=pd.DataFrame()
        other_card_batches=card_batches

    # Run strong ANB card matching and provider/Al Rajhi payout matching separately,
    # then combine results. Legacy core matching remains available in core.py.
    card_result,anb_unmatched=bank_ext.reconcile_card_batches_advanced(
        other_card_batches,bank,tol,settlement_lag_days
    )
    provider_result,rajhi_unmatched=bank_ext.reconcile_provider_batches_to_rajhi(
        provider_batches,bank,tol,tabby_fee
    )
    amex_result=bank_ext.finalize_amex_batches(
        amex_card_batches,amex_submissions_all,tol
    ) if not amex_card_batches.empty else pd.DataFrame()

    batch_result=pd.concat(
        [x for x in [card_result,provider_result,amex_result] if x is not None and not x.empty],
        ignore_index=True
    ) if (not card_result.empty or not provider_result.empty or not amex_result.empty) else pd.DataFrame()

    bank_unmatched=pd.concat(
        [x for x in [anb_unmatched,rajhi_unmatched] if x is not None and not x.empty],
        ignore_index=True
    ) if (not anb_unmatched.empty or not rajhi_unmatched.empty) else pd.DataFrame()

    # Informational only: tags AMEX-tagged unmatched bank credits that AMEX's
    # own declared wires independently confirm against this bank data. Never
    # removes a row or promotes any settlement batch (see V71 doc).
    bank_unmatched=bank_ext.annotate_amex_wire_confirmations(
        bank_unmatched,amex_payments_all,bank,tol,settlement_lag_days
    )

    updated=bank_ext.propagate_verified_batches(matched,batch_result)
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

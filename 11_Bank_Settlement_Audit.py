from __future__ import annotations
import io
import pandas as pd
import streamlit as st

import auth, theme, core
import bank_settlement_final as bsv

st.set_page_config(page_title="Bank Settlement Audit",layout="wide",page_icon="🏦")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Bank Settlement Audit / Verification"),unsafe_allow_html=True)
st.title("Bank Settlement Audit / Verification")

st.info(
    "Bank verification is a control gate after D365 ↔ POS/provider reconciliation, not a second reconciliation. "
    "Open settlements carry forward. Normal JV creation requires Bank Settled = TRUE."
)

r=st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

matched=r.get("matched",pd.DataFrame()).copy()
pos=r.get("pos",pd.DataFrame()).copy()

tabs=st.tabs(["ANB Cards","AMEX","TAP","TABBY","TAMARA","Dashboard"])

with tabs[0]:
    st.subheader("ANB Card Settlement Verification")
    st.caption(
        "Terminal ID + Payment Type + POS Transaction Date + grouped POS gross + TX count → ANB credit. "
        "The DDMMYY inside Narration 2 is retained as ANB batch/reference date, not assumed to be the POS sale date."
    )
    files=st.file_uploader("Upload ANB Bank Statement",type=["xlsx","xls","csv"],accept_multiple_files=True,key="anb_verify")
    if st.button("VERIFY ANB",type="primary",use_container_width=True):
        parts=[]
        for f in files or []:
            for _,df in core.read_upload(f).items():
                try:
                    x=bsv.normalize_anb_bank_batches(df)
                    if not x.empty: parts.append(x)
                except Exception:
                    pass
        bank_batches=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
        pos_batches=bsv.retail_pos_to_anb_batches(pos)
        if bank_batches.empty:
            st.error("No usable ANB settlement rows found.")
        elif pos_batches.empty:
            st.error("No normalized POS rows available.")
        else:
            v=bsv.verify_anb(pos_batches,bank_batches,tolerance=1.0)
            st.session_state["bank_verify_anb"]=v
            r["matched"]=bsv.apply_anb_verification_to_matched(matched,v)
            st.session_state.ct_result=r
            st.success("ANB verification completed and eligible matched rows updated.")
    v=st.session_state.get("bank_verify_anb",pd.DataFrame())
    if not v.empty:
        st.dataframe(v,use_container_width=True,hide_index=True)

with tabs[1]:
    st.subheader("AMEX Settlement Verification")
    st.caption(
        "Terminal ID + POS Transaction Date + grouped POS gross → AMEX bank credit. "
        "Same terminal-batch model as ANB Cards; AMEX is a card scheme like MADA/VISA/MASTERCARD, "
        "just settled/reported separately."
    )
    files=st.file_uploader("Upload AMEX Settlement / Bank Statement",type=["xlsx","xls","csv"],accept_multiple_files=True,key="amex_verify")
    if st.button("VERIFY AMEX",type="primary",use_container_width=True):
        parts=[]
        for f in files or []:
            for _,df in core.read_upload(f).items():
                try:
                    x=core.normalize_bank(df,"AMEX Settlement")
                    if x is not None and not x.empty:
                        parts.append(x)
                except Exception:
                    pass
        bank_rows=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
        expected=bsv.build_amex_expected(matched)
        if bank_rows.empty:
            st.error("No usable AMEX settlement rows found.")
        elif expected.empty:
            st.error("No AMEX transactions available from reconciliation.")
        else:
            v=bsv.verify_provider_payouts(expected,bank_rows,"AMEX",tolerance=1.0,
                                           bank_date_col="Bank Date",credit_col="Bank Amount")
            st.session_state["bank_verify_amex"]=v
            matched=bsv.apply_amex_verification_to_matched(matched,v)
            r["matched"]=matched
            st.session_state.ct_result=r
            st.success("AMEX verification completed and eligible matched rows updated.")
    v=st.session_state.get("bank_verify_amex",pd.DataFrame())
    if not v.empty:
        st.dataframe(v,use_container_width=True,hide_index=True)

with tabs[2]:
    st.subheader("TAP Payout Verification")
    st.caption("payout_id → SUM(net_amount) = expected Al Rajhi bank credit. Multiple payouts on the same bank date remain separate.")
    provider=st.file_uploader("Upload TAP charge/payout files",type=["xlsx","xls","csv"],accept_multiple_files=True,key="tap_payout")
    bankf=st.file_uploader("Upload bank statement containing TAP TECHNOLOGIES credits",type=["xlsx","xls","csv"],accept_multiple_files=True,key="tap_bank")
    if st.button("VERIFY TAP",type="primary",use_container_width=True):
        exp=[]; banks=[]
        for f in provider or []:
            for _,df in core.read_upload(f).items():
                try:
                    x=bsv.build_tap_payouts(df)
                    if not x.empty: exp.append(x)
                except Exception:
                    pass
        for f in bankf or []:
            for _,df in core.read_upload(f).items(): banks.append(df)
        e=pd.concat(exp,ignore_index=True) if exp else pd.DataFrame()
        b=pd.concat(banks,ignore_index=True,sort=False) if banks else pd.DataFrame()
        if e.empty or b.empty:
            st.error("TAP payout or bank file is missing/unusable.")
        else:
            v=bsv.verify_provider_payouts(e,b,"TAP")
            st.session_state["bank_verify_tap"]=v
            matched=bsv.apply_provider_verification_to_matched(matched,v,"TAP")
            r["matched"]=matched
            st.session_state.ct_result=r
            applied=int(matched["Bank Settled"].fillna(False).astype(bool).sum()) if "Bank Settled" in matched.columns else 0
            st.success("TAP verification completed. Unsettled payouts remain open. Reconciliation rows were updated where provider references proved the payout.")
    v=st.session_state.get("bank_verify_tap",pd.DataFrame())
    if not v.empty: st.dataframe(v,use_container_width=True,hide_index=True)

with tabs[3]:
    st.subheader("TABBY Payout Verification")
    st.caption(
        "Expected Bank Credit = Transferred Amount − SAR 5.00 ONCE per store/payout transfer. "
        "The SAR 5 is not deducted per customer transaction."
    )
    fee=st.number_input("TABBY transfer fee per payout (SAR)",min_value=0.0,value=5.0,step=0.5)
    provider=st.file_uploader("Upload TABBY Payout Sheet",type=["xlsx","xls","csv"],accept_multiple_files=True,key="tabby_payout")
    bankf=st.file_uploader("Upload bank statement containing TABBY FINANCING COMPANY credits",type=["xlsx","xls","csv"],accept_multiple_files=True,key="tabby_bank")
    if st.button("VERIFY TABBY",type="primary",use_container_width=True):
        exp=[]; banks=[]
        for f in provider or []:
            for _,df in core.read_upload(f).items():
                try:
                    x=bsv.build_tabby_payouts(df,transfer_fee=fee)
                    if not x.empty: exp.append(x)
                except Exception:
                    pass
        for f in bankf or []:
            for _,df in core.read_upload(f).items(): banks.append(df)
        e=pd.concat(exp,ignore_index=True) if exp else pd.DataFrame()
        b=pd.concat(banks,ignore_index=True,sort=False) if banks else pd.DataFrame()
        if e.empty or b.empty:
            st.error("TABBY payout or bank file is missing/unusable.")
        else:
            v=bsv.verify_provider_payouts(e,b,"TABBY")
            st.session_state["bank_verify_tabby"]=v
            matched=bsv.apply_provider_verification_to_matched(matched,v,"TABBY")
            r["matched"]=matched
            st.session_state.ct_result=r
            applied=int(matched["Bank Settled"].fillna(False).astype(bool).sum()) if "Bank Settled" in matched.columns else 0
            st.success("TABBY verification completed. Reconciliation rows were updated where provider references proved the payout.")
    v=st.session_state.get("bank_verify_tabby",pd.DataFrame())
    if not v.empty: st.dataframe(v,use_container_width=True,hide_index=True)

with tabs[4]:
    st.subheader("TAMARA Payout Verification")
    st.caption("Expected Bank Credit = Payable to Merchant exactly. No SAR 5 deduction is applied to TAMARA.")
    provider=st.file_uploader("Upload TAMARA payout/invoice files",type=["xlsx","xls","csv"],accept_multiple_files=True,key="tamara_payout")
    bankf=st.file_uploader("Upload bank statement containing TAMARA FINANCE COMPANY credits",type=["xlsx","xls","csv"],accept_multiple_files=True,key="tamara_bank")
    if st.button("VERIFY TAMARA",type="primary",use_container_width=True):
        exp=[]; banks=[]
        for f in provider or []:
            for _,df in core.read_upload(f).items():
                try:
                    x=bsv.build_tamara_payouts(df)
                    if not x.empty: exp.append(x)
                except Exception:
                    pass
        for f in bankf or []:
            for _,df in core.read_upload(f).items(): banks.append(df)
        e=pd.concat(exp,ignore_index=True) if exp else pd.DataFrame()
        b=pd.concat(banks,ignore_index=True,sort=False) if banks else pd.DataFrame()
        if e.empty or b.empty:
            st.error("TAMARA payout or bank file is missing/unusable.")
        else:
            v=bsv.verify_provider_payouts(e,b,"TAMARA")
            st.session_state["bank_verify_tamara"]=v
            matched=bsv.apply_provider_verification_to_matched(matched,v,"TAMARA")
            r["matched"]=matched
            st.session_state.ct_result=r
            applied=int(matched["Bank Settled"].fillna(False).astype(bool).sum()) if "Bank Settled" in matched.columns else 0
            st.success("TAMARA verification completed. Reconciliation rows were updated where provider references proved the payout.")
    v=st.session_state.get("bank_verify_tamara",pd.DataFrame())
    if not v.empty: st.dataframe(v,use_container_width=True,hide_index=True)

with tabs[5]:
    st.subheader("Settlement Dashboard")
    m=st.session_state.get("ct_result",{}).get("matched",pd.DataFrame()).copy()
    if m.empty:
        st.info("No matched transactions available.")
    else:
        settled=m["Bank Settled"].fillna(False).astype(bool) if "Bank Settled" in m.columns else pd.Series(False,index=m.index)
        c1,c2,c3=st.columns(3)
        c1.metric("Bank Settled",int(settled.sum()))
        c2.metric("Awaiting Settlement",int((~settled).sum()))
        open_net=pd.to_numeric(m.loc[~settled,"Net Amount"],errors="coerce").fillna(0).sum() if "Net Amount" in m.columns else 0
        c3.metric("Open Net",f"SAR {open_net:,.2f}")
        st.dataframe(m,use_container_width=True,hide_index=True)
        st.warning("Awaiting items remain open and carry forward. They are not eligible for the normal JV.")

frames={}
for key,label in [
    ("bank_verify_anb","ANB"),
    ("bank_verify_amex","AMEX"),
    ("bank_verify_tap","TAP"),
    ("bank_verify_tabby","TABBY"),
    ("bank_verify_tamara","TAMARA"),
]:
    d=st.session_state.get(key,pd.DataFrame())
    if isinstance(d,pd.DataFrame) and not d.empty:
        frames[label]=d

if frames:
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w:
        for label,d in frames.items():
            d.to_excel(w,index=False,sheet_name=label)
    st.download_button(
        "DOWNLOAD BANK VERIFICATION PACK",
        out.getvalue(),
        "RetailReconAI_Bank_Verification.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

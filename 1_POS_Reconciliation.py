from __future__ import annotations
import pandas as pd
import streamlit as st
import importlib
import auth, theme, core, db
import report_export

# Reload current core.py from disk on each page run to avoid stale Streamlit module state.
core = importlib.reload(core)

st.set_page_config(page_title="POS Reconciliation - Retail Control Tower",layout="wide",page_icon="🧾")
auth.require_login({"Admin","Finance Manager","Finance Maker","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","POS Reconciliation – POS-to-GL Control Center"),unsafe_allow_html=True)

st.markdown(theme.section_title(1,"POS-TO-GL CONTROL CENTER"),unsafe_allow_html=True)
st.caption("One operating hub for the full lifecycle: Reconcile → Validate → Settle → Correct → Close → Configure GL → Create JV → Approve → Post to D365 → Verify → Adjust Late Transactions.")
st.markdown('<div class="ct-flow">POS Reconciliation → Commission / Bank / Refund Controls → Exceptions & Close → GL Configuration → JV Creation → Approval → D365 Posting → Verification → Adjustment JV</div>',unsafe_allow_html=True)

def card(col,title,desc,page,icon):
    with col:
        st.markdown('<div class="ct-card">',unsafe_allow_html=True)
        st.markdown(f"**{icon} {title}**")
        st.caption(desc)
        st.page_link(page,label=f"Open {title}",icon="➡️")
        st.markdown('</div>',unsafe_allow_html=True)

st.subheader("1. Reconciliation & Treasury Controls")
a,b,c=st.columns(3)
card(a,"Commission Validation","Validate settled POS/provider commission and VAT against signed contract rates.","pages/10_Commission_Validation.py","🧾")
card(b,"Bank Settlement Audit","Match POS batches to real bank credits and measure actual settlement delay.","pages/11_Bank_Settlement_Audit.py","🏦")
card(c,"Refund Reconciliation","Control refunds, reversals and provider/bank refund settlement.","pages/12_Refund_Reconciliation.py","↩️")
a,b,c=st.columns(3)
card(a,"POS Auto Mapper","Learn and map new POS/provider layouts without replacing proven reconciliation rules.","pages/13_POS_Auto_Mapper.py","🧩")
card(b,"Store Mapping Master","Upload/change Provider Store Name → D365 Store Code mappings.","pages/14_Store_Mapping_Master.py","🏬")
card(c,"POS Terminal Master","Upload/change Terminal ID → Store Code mappings without changing code.","pages/16_POS_Terminal_Master.py","🖥️")
card(a,"Merchant ID Master","Upload/change Merchant ID → Store Code mappings for provider files with no Terminal ID.","pages/17_Merchant_ID_Master.py","🏷️")
card(b,"Bank Claim Follow Up","Track missing/delayed settlements, claims, ownership, aging and follow-up.","pages/15_Bank_Claim_Follow_Up.py","📨")
card(c,"AI Finance Copilot","Ask natural-language questions across sales, tenders, exceptions, settlement, corrections and JV status.","pages/29_AI_Finance_Copilot.py","🤖")

st.subheader("2. Close, Configuration & Exception Control")
a,b,c=st.columns(3)
card(a,"Month End Close Calendar","Finance close ownership, due dates, status and completion control.","pages/21_Month_End_Close_Calendar.py","🗓️")
card(b,"GL Configuration","Maintain country, store, provider and accounting GL mappings used by JV creation.","pages/22_GL_Configuration.py","⚙️")
card(c,"Exception Correction Center","Investigate exceptions and apply controlled corrections with reason and audit history.","pages/23_Exception_Correction_Center.py","🛠️")

st.subheader("3. JV, D365 Posting & Verification")
a,b,c=st.columns(3)
card(a,"JV Creation","Create weekly store-wise balanced JVs from approved, bank-settled matched transactions.","pages/24_JV_Creation.py","🧾")
card(b,"JV Approval Center","Maker-checker finance approval before posting.","pages/25_JV_Approval_Center.py","✅")
card(c,"D365 Posting Center","Controlled posting queue with duplicate protection.","pages/26_D365_Posting_Center.py","🚀")
a,b,c=st.columns(3)
card(a,"D365 Posting Verification","Capture voucher/status and verify successful posting.","pages/27_D365_Posting_Verification.py","🔎")
card(b,"Late Transaction Adjustment JV","Create controlled adjustment/reversal JV for late transactions after close.","pages/28_Late_Transaction_Adjustment_JV.py","🔁")

st.divider()
st.markdown(theme.section_title(4,"POS Reconciliation Functions"),unsafe_allow_html=True)
with st.sidebar:
    st.header("Reconciliation Settings")
    tolerance=st.number_input("Tolerance (SAR)",0.0,10.0,1.0,0.25)
    st.caption("Matched within approved SAR 1 tolerance can proceed only after bank settlement and Finance approval.")

uploads=st.file_uploader("Upload D365 Store Tender + POS/AMEX/Tabby/Tamara/Tap files",type=["xlsx","xls","csv"],accept_multiple_files=True)
bank_uploads=st.file_uploader("Upload Bank Statements (ANB / Al Rajhi)",type=["xlsx","xls","csv"],accept_multiple_files=True)
prev_cf=st.file_uploader("Previous Carry Forward (optional)",type=["xlsx","xls","csv"],key="cf")

if st.button("RUN RECONCILIATION",type="primary",use_container_width=True):
    try:
        tender_parts=[];pos_parts=[];quarantine=[]
        for f in uploads or []:
            for sheet,df in core.read_upload(f).items():
                typ=core.classify(f"{f.name}-{sheet}",df)
                if typ=="D365 STORE TENDER":
                    tender_parts.append(core.normalize_tender(df))
                elif typ in {"POS","AMEX","TABBY","TAMARA","TAP"}:
                    forced=typ if typ in {"AMEX","TABBY","TAMARA","TAP"} else None
                    try: pos_parts.append(core.normalize_pos(df,f.name,forced))
                    except Exception as e: quarantine.append({"File":f.name,"Sheet":sheet,"Reason":str(e)})
                else:
                    quarantine.append({"File":f.name,"Sheet":sheet,"Reason":f"Classified as {typ}"})
        # Safety fallback: if auto-classification did not identify the D365 tender,
        # inspect all uploaded sheets directly for the mandatory D365 business keys.
        if not tender_parts:
            for f in uploads or []:
                for sheet,df in core.read_upload(f).items():
                    d=core.norm_cols(df)
                    has_store=core.find(d,["store","store code","store name"])
                    has_date=core.find(d,["transdate","transaction date","sales date","date"])
                    has_receipt=core.find(d,["receiptid","receipt id","receipt","receipt number","receipt no"])
                    has_auth=core.find(d,["auth code","authorization code","auth","authorization","approval code"])
                    if has_store and has_date and has_receipt and has_auth:
                        tender_parts.append(core.normalize_tender(df))

        if not tender_parts:
            detected=[]
            for f in uploads or []:
                for sheet,df in core.read_upload(f).items():
                    detected.append(f"{f.name} / {sheet}: {core.classify(f.name,df)} | Columns: {', '.join(map(str, list(df.columns)[:12]))}")
            detail="\n".join(detected) if detected else "No upload files found."
            raise ValueError(
                "No D365 Store Tender detected. The Store Tender must contain Store, "
                "Transaction Date/Transdate, Receipt ID/Receiptid and Auth Code.\n\n"
                "Detected files:\n" + detail
            )

        tender=pd.concat(tender_parts,ignore_index=True)
        pos=pd.concat(pos_parts,ignore_index=True) if pos_parts else pd.DataFrame()
        # Apply editable store-resolution masters before matching, strictly in
        # priority order: Provider Store Name (weakest signal) -> Merchant ID ->
        # Terminal ID (strongest signal, applied last so it always wins).
        store_master=db.load_store_mapping_master()
        if not pos.empty and not store_master.empty:
            pos=core.apply_store_mapping_master(pos,store_master)

        merchant_master=db.load_merchant_master()
        if not pos.empty:
            pos=core.apply_merchant_master(pos,merchant_master)

        terminal_master=db.load_terminal_master()
        if not pos.empty:
            pos=core.apply_terminal_master(pos,terminal_master)

        # Apply maker-checker approved Auth Code corrections before matching.
        # Original Auth Code remains preserved in the tender audit columns.
        tender=db.apply_approved_corrections(tender)

        # Cash comes directly from D365 Store Tender and never requires a POS/provider settlement.
        cash_transactions=tender[tender["D365 Payment"].astype(str).str.upper()=="CASH"].copy() if not tender.empty else pd.DataFrame()
        tender_for_pos=tender[tender["D365 Payment"].astype(str).str.upper()!="CASH"].copy() if not tender.empty else tender.copy()

        matched,us,up=core.reconcile(tender_for_pos,pos,tolerance)
        banks=[]
        bank_skipped=[]
        for f in bank_uploads or []:
            for sheet,df in core.read_upload(f).items():
                bank="Al Rajhi Bank" if "rajhi" in f.name.lower() else "ANB Bank"
                try:
                    b=core.normalize_bank(df,bank)
                    if b is not None and not b.empty:
                        b["Bank Source File"]=f.name
                        b["Bank Source Sheet"]=sheet
                        banks.append(b)
                    else:
                        bank_skipped.append({
                            "File":f.name,
                            "Sheet":sheet,
                            "Reason":"No usable bank transaction rows"
                        })
                except Exception as e:
                    # Do not stop the complete reconciliation because a workbook
                    # contains a cover/summary/non-transaction sheet.
                    bank_skipped.append({
                        "File":f.name,
                        "Sheet":sheet,
                        "Reason":str(e)
                    })

        bank=pd.concat(banks,ignore_index=True) if banks else pd.DataFrame()
        matched=core.apply_bank_settlement(matched,bank,tolerance)
        previous=None
        if prev_cf:
            previous=list(core.read_upload(prev_cf).values())[0]
        cf=core.make_carry_forward(us,up,previous)
        qdf=pd.DataFrame(quarantine)
        bqdf=pd.DataFrame(bank_skipped)
        if not bqdf.empty:
            bqdf["Type"]="BANK_SHEET_SKIPPED"
            qdf=pd.concat([qdf,bqdf],ignore_index=True,sort=False)

        st.session_state.ct_result={"matched":matched,"unmatched_sales":us,"unmatched_pos":up,"carry_forward":cf,
                                    "cash_transactions":cash_transactions,
                                    "tender":tender,"pos":pos,"bank":bank,"quarantine":qdf}
        st.success("Reconciliation completed and saved to the current control-tower session.")
    except Exception as e:
        st.exception(e)

r=st.session_state.get("ct_result")
if r:
    m=r["matched"];us=r["unmatched_sales"];up=r["unmatched_pos"]
    cash_tx=r.get("cash_transactions",pd.DataFrame())
    k1,k2,k3,k4,k5,k6=st.columns(6)
    k1.metric("Matched / Review",len(m));k2.metric("Unmatched D365",len(us));k3.metric("Unmatched POS",len(up))
    k4.metric("Cash Transactions",len(cash_tx))
    k5.metric("Bank Settled",int(m["Bank Settled"].sum()) if not m.empty else 0)
    k6.metric("Max Diff",f"SAR {m['Difference'].abs().max():,.2f}" if not m.empty else "SAR 0.00")
    tabs=st.tabs(["Matched","Cash Sales / Refunds","Unmatched D365","Unmatched POS","Carry Forward","Quarantine"])
    with tabs[0]:
        st.dataframe(m,use_container_width=True,hide_index=True)
    with tabs[1]:
        if cash_tx.empty:
            st.info("No Cash Sales / Cash Refund transactions in the uploaded Store Tender.")
        else:
            cash_view_cols=[c for c in [
                "Store Code","Date","Receipt ID","Auth Code","Cash Classification","Cash Amount",
                "D365 Raw Auth Code","D365 Row"
            ] if c in cash_tx.columns]
            st.dataframe(cash_tx[cash_view_cols],use_container_width=True,hide_index=True)
    with tabs[2]:st.dataframe(us,use_container_width=True,hide_index=True)
    with tabs[3]:st.dataframe(up,use_container_width=True,hide_index=True)
    with tabs[4]:st.dataframe(r["carry_forward"],use_container_width=True,hide_index=True)
    with tabs[5]:st.dataframe(r["quarantine"],use_container_width=True,hide_index=True)
    blob=report_export.create_reconciliation_pack(r,tolerance)
    st.download_button(
        "DOWNLOAD RECONCILIATION PACK",
        blob,
        "RetailReconAI_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

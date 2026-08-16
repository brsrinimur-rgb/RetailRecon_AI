from __future__ import annotations
import pandas as pd
import streamlit as st
import importlib
import auth, theme, core, db
from logic import bank_settlement_extension as bank_ext
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
card(c,"D365 GL Reconciliation","Independently verify RetailRecon source/JVs against actual D365 clearing-account entries.","pages/30_D365_GL_Reconciliation.py","📚")

st.divider()
st.markdown(theme.section_title(4,"POS Reconciliation Functions"),unsafe_allow_html=True)
with st.sidebar:
    st.header("Reconciliation Settings")
    tolerance=st.number_input("Tolerance (SAR)",0.0,10.0,1.0,0.25)
    st.caption("Matched within approved SAR 1 tolerance can proceed only after bank settlement and Finance approval.")
    settlement_lag_days=st.number_input(
        "Extra ANB settlement lag (days, on top of existing 0-3 day window)",
        0,10,0,1,
        help="Widens how many additional days beyond the standard 0-3 day window a bank "
             "credit is still considered for a POS batch. 0 leaves matching exactly as before."
    )

uploads=st.file_uploader("Upload D365 Store Tender + D365 Sales Details + POS/AMEX/Tabby/Tamara/Tap files",type=["xlsx","xls","csv"],accept_multiple_files=True)
bank_uploads=st.file_uploader("Upload Bank Statements (ANB / Al Rajhi)",type=["xlsx","xls","csv"],accept_multiple_files=True)
prev_cf=st.file_uploader("Previous Carry Forward (optional)",type=["xlsx","xls","csv"],key="cf")

if st.button("RUN RECONCILIATION",type="primary",use_container_width=True):
    try:
        tender_parts=[];sales_details_parts=[];pos_parts=[];quarantine=[]
        payout_sheets=set()
        for f in uploads or []:
            for sheet,df in core.read_upload(f).items():
                payout_type=core.classify_settlement_source(f.name,df)
                if payout_type in {"TABBY_PAYOUT","TAMARA_PAYOUT","TAP_PAYOUT","AMEX_PAYOUT"}:
                    payout_sheets.add((f.name,sheet))
                    # A payout/settlement sheet must never also be normalized as
                    # a transaction source. It will be picked up by the payout scan below.
                    continue
                typ=core.classify(f"{f.name}-{sheet}",df)
                if typ=="D365 STORE TENDER":
                    tender_parts.append(core.normalize_tender(df))
                elif typ=="D365 SALES DETAILS":
                    try:
                        sales_details_parts.append(core.normalize_sales_details(df,f.name))
                    except Exception as e:
                        quarantine.append({"File":f.name,"Sheet":sheet,"Reason":f"Sales Details: {e}"})
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
        sales_details=pd.concat(sales_details_parts,ignore_index=True) if sales_details_parts else pd.DataFrame()

        # Store 613 special D365 bridge:
        # StoreTender Sales Order -> SalesDetails Sales Order -> Receipt ID / Auth Code (only if unique).
        # This happens before corrections and POS/provider matching.
        tender,store613_bridge=core.enrich_store613_from_sales_details(tender,sales_details)

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
        provider_payout_parts=[]
        for f in bank_uploads or []:
            for sheet,df in core.read_upload(f).items():
                bank="Al Rajhi Bank" if "rajhi" in f.name.lower() else "ANB Bank"
                try:
                    # V24 additive parser first: recognizes the Finance-supplied
                    # ANB and Al Rajhi statement structures and preserves narration evidence.
                    b=bank_ext.normalize_bank_statement(df,f.name)
                    if b is None or b.empty:
                        # Legacy parser remains as fallback.
                        b=core.normalize_bank(
                            df,bank,source_file=f.name,source_sheet=sheet
                        )
                    if b is not None and not b.empty:
                        b["Bank Source File"]=f.name
                        b["Bank Source Sheet"]=sheet
                        if "Bank Source Row" not in b.columns:
                            b["Bank Source Row"]=range(1,len(b)+1)
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

        # V26 additive provider-payout scan from the files already supplied to POS Reconciliation.
        # It does not replace the normal provider transaction parser.
        _all_for_payout=[]
        for _v in ["uploads","files","provider_uploads","pos_uploads"]:
            _obj=locals().get(_v)
            if _obj:
                try:
                    _all_for_payout.extend(list(_obj) if isinstance(_obj,(list,tuple)) else [_obj])
                except Exception:
                    pass
        _seen=set()
        for _f in _all_for_payout:
            _name=getattr(_f,"name",str(_f))
            if _name in _seen:
                continue
            _seen.add(_name)
            try:
                for _sheet,_df in core.read_upload(_f).items():
                    _typ=core.classify_settlement_source(_name,_df)
                    _pb=pd.DataFrame()
                    if _typ=="TAMARA_PAYOUT":
                        _pb=core.normalize_tamara_payout(_df,_name)
                    elif _typ=="TABBY_PAYOUT":
                        _pb=core.normalize_tabby_payout(_df,_name)
                    elif _typ=="TAP_PAYOUT":
                        _pb=core.normalize_tap_payout(_df,_name)
                    if _pb is not None and not _pb.empty:
                        provider_payout_parts.append(_pb)
            except Exception:
                # Payout discovery must not break the proven reconciliation parser.
                pass
        r_provider_batches=pd.concat(provider_payout_parts,ignore_index=True) if provider_payout_parts else pd.DataFrame()
        if r_provider_batches is not None and not r_provider_batches.empty:
            # TABBY only: link payout Order Numbers to the already-trusted
            # matched Provider Reference. Tamara/TAP remain unlinked until a
            # trusted transaction-level key is proven.
            r_provider_batches=core.link_tabby_payout_underlying_ids(r_provider_batches,matched)

        bank=pd.concat(banks,ignore_index=True) if banks else pd.DataFrame()

        # Preserve the proven legacy transaction-level bank matching first.
        matched=core.apply_bank_settlement(matched,bank,tolerance)

        # V24 additive settlement-batch pass:
        # ANB card settlements are verified by terminal + source date + scheme + net amount,
        # then BANK RECEIVED is propagated to all underlying matched transactions.
        settlement_batches=core.build_card_settlement_batches(matched)
        card_batch_result,card_bank_unmatched=bank_ext.reconcile_card_batches_advanced(
            settlement_batches,bank,tolerance,settlement_lag_days
        )
        matched=bank_ext.propagate_verified_batches(matched,card_batch_result)

        # V26: provider payout settlement is also part of the main reconciliation path
        # when provider payout batches are available. This removes the undocumented
        # requirement to visit Settlement Batch Engine separately just to release
        # Tabby/Tamara/TAP transactions to bank-settled status.
        provider_batches=r_provider_batches if "r_provider_batches" in locals() else pd.DataFrame()
        provider_batch_result=pd.DataFrame()
        provider_bank_unmatched=pd.DataFrame()
        if provider_batches is not None and not provider_batches.empty:
            provider_batch_result,provider_bank_unmatched=bank_ext.reconcile_provider_batches_to_rajhi(
                provider_batches,bank,tolerance,5.0
            )
            matched=bank_ext.propagate_verified_batches(matched,provider_batch_result)

        previous=None
        if prev_cf:
            previous=list(core.read_upload(prev_cf).values())[0]

        # Split the uploaded previous-period carry-forward file by which kind
        # of row it actually is BEFORE feeding it to either function. Without
        # this split, the whole `previous` file was passed into both
        # make_carry_forward() and build_settlement_carry_forward()
        # unconditionally -- and both functions re-attach every row they're
        # given, tagged "Carry Forward Source"="Prior Period", with no
        # filtering of their own. Since the file this page itself produces is
        # exactly cf = concat([cf_legacy, cf_settlement]), re-uploading a
        # prior export meant every row appeared twice in the new cf: once via
        # cf_legacy, once via cf_settlement.
        previous_legacy=None
        previous_settlement=None
        if previous is not None and not previous.empty:
            if "Carry Forward Type" in previous.columns:
                _leg=previous[
                    previous["Carry Forward Type"].notna()
                    & previous["Carry Forward Type"].astype(str).str.strip().ne("")
                ]
                previous_legacy=_leg if not _leg.empty else None
            if "Carry Forward Status" in previous.columns:
                _settle=previous[
                    previous["Carry Forward Status"].notna()
                    & previous["Carry Forward Status"].astype(str).str.strip().ne("")
                ]
                previous_settlement=_settle if not _settle.empty else None
            # Backward compatible: an older uploaded file that predates this
            # split (has neither discriminating column) is treated exactly as
            # before settlement carry-forward existed -- legacy-only, never
            # duplicated into both paths.
            if previous_legacy is None and previous_settlement is None:
                previous_legacy=previous

        # Legacy unmatched carry-forward remains intact.
        cf_legacy=core.make_carry_forward(us,up,previous_legacy)

        # Settlement carry-forward adds matched transactions whose bank receipt
        # is still pending at the selected period end. Original transaction date
        # is preserved and later settlement is tracked in the resolution period.
        from logic.carry_forward_extension import build_settlement_carry_forward
        _period_end=pd.to_datetime(tender["Date"],errors="coerce").max()
        cf_settlement=build_settlement_carry_forward(
            matched,
            period_end=_period_end,
            previous=previous_settlement
        )
        cf=pd.concat(
            [x for x in [cf_legacy,cf_settlement] if x is not None and not x.empty],
            ignore_index=True,sort=False
        ) if (
            (cf_legacy is not None and not cf_legacy.empty)
            or (cf_settlement is not None and not cf_settlement.empty)
        ) else pd.DataFrame()
        qdf=pd.DataFrame(quarantine)
        bqdf=pd.DataFrame(bank_skipped)
        if not bqdf.empty:
            bqdf["Type"]="BANK_SHEET_SKIPPED"
            qdf=pd.concat([qdf,bqdf],ignore_index=True,sort=False)

        st.session_state.ct_result={"matched":matched,"unmatched_sales":us,"unmatched_pos":up,"carry_forward":cf,
                                    "cash_transactions":cash_transactions,
                                    "tender":tender,"sales_details":sales_details,"store613_bridge":store613_bridge,
                                    "pos":pos,"bank":bank,"quarantine":qdf,
                                    "settlement_batches":pd.concat(
                                        [x for x in [card_batch_result,provider_batch_result]
                                         if x is not None and not x.empty],
                                        ignore_index=True
                                    ) if (
                                        (card_batch_result is not None and not card_batch_result.empty)
                                        or (provider_batch_result is not None and not provider_batch_result.empty)
                                    ) else pd.DataFrame(),
                                    "settlement_bank_unmatched":pd.concat(
                                        [x for x in [card_bank_unmatched,provider_bank_unmatched]
                                         if x is not None and not x.empty],
                                        ignore_index=True
                                    ) if (
                                        (card_bank_unmatched is not None and not card_bank_unmatched.empty)
                                        or (provider_bank_unmatched is not None and not provider_bank_unmatched.empty)
                                    ) else pd.DataFrame(),
                                    "provider_payout_batches":r_provider_batches,
                                    "settlement_blocker_summary":bank_ext.settlement_blocker_summary(matched)}
        # Persist an auditable run snapshot so a later reconciliation does not
        # erase access to the previous reports.
        try:
            _u=st.session_state.get("user",{})
            _run_id=db.save_reconciliation_run(
                st.session_state.ct_result,
                user=str(_u.get("username","system")),
                period_from=pd.to_datetime(tender["Date"],errors="coerce").min(),
                period_to=pd.to_datetime(tender["Date"],errors="coerce").max(),
            )
            st.session_state["current_reconciliation_run_id"]=_run_id
            st.caption(f"Saved reconciliation run: {_run_id}")
        except Exception as _hist_err:
            quarantine.append({"File":"","Sheet":"","Reason":f"Run history save warning: {_hist_err}"})

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
    bridge613=r.get("store613_bridge",pd.DataFrame())
    tabs=st.tabs(["Matched","Cash Sales / Refunds","Store 613 SalesDetails Bridge","Unmatched D365","Unmatched POS","Carry Forward","Quarantine"])
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
    with tabs[2]:
        if bridge613.empty:
            st.info("No Store 613 SalesDetails bridge rows. Upload D365 Sales Details together with Store Tender when Store 613 is included.")
        else:
            st.caption("Store 613 bridge uses Store Code + Sales Order. Receipt ID/Auth Code are populated only when unique in Sales Details.")
            st.dataframe(bridge613,use_container_width=True,hide_index=True)
    with tabs[3]:st.dataframe(us,use_container_width=True,hide_index=True)
    with tabs[4]:st.dataframe(up,use_container_width=True,hide_index=True)
    with tabs[5]:st.dataframe(r["carry_forward"],use_container_width=True,hide_index=True)
    with tabs[6]:st.dataframe(r["quarantine"],use_container_width=True,hide_index=True)
    blob=report_export.create_reconciliation_pack(r,tolerance)
    st.download_button(
        "DOWNLOAD RECONCILIATION PACK",
        blob,
        "RetailReconAI_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

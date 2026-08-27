import pandas as pd
import streamlit as st
import auth, theme, db, core
from logic import exception_routing_extension as exc_route
from logic import bank_settlement_extension as bank_ext

st.set_page_config(page_title="Exception Correction Center",layout="wide",page_icon="🛠️")
auth.require_login({"Admin","Finance Manager","Finance Maker","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Exception Correction Center"),unsafe_allow_html=True)
st.title("Exception Correction Center")
st.caption(
    "Only genuinely unresolved exceptions reach this page. Safe one-to-one matches are resolved "
    "automatically by the reconciliation engine first. Manual Auth Code changes remain controlled: "
    "Maker submits → Checker/Finance Manager approves or rejects → approved value becomes effective. "
    "The maker cannot approve their own request."
)

user=st.session_state.user
username=user["username"]
role=user["role"]

r=st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

# ------------------------------------------------------------- SUBMIT
st.subheader("1. Submit Correction")
all_unmatched=r.get("unmatched_sales",pd.DataFrame()).copy()
u=exc_route.route_auth_correction_candidates(
    all_unmatched,
    r.get("unmatched_pos",pd.DataFrame()),
    r.get("sales_details",pd.DataFrame()),
    1.0
)
other_exceptions=exc_route.unresolved_non_auth_exceptions(all_unmatched,u)

if u.empty:
    st.success(
        "No D365 rows currently have evidence for an Auth Code correction. "
        "Unmatched rows without a proven replacement Auth remain reconciliation exceptions."
    )
else:
    show_cols=[c for c in [
        "D365 Row","Store Code","Date","Receipt ID","Auth Code","Suggested Auth Code",
        "D365 Payment","D365 Amount","Correction Evidence","Evidence Source",
        "Correction Confidence","Candidate Amount Difference","Sales Order","SalesDetails Bridge Status"
    ] if c in u.columns]
    st.dataframe(u[show_cols],use_container_width=True,hide_index=True)

    available_rows=sorted(
        pd.to_numeric(u.get("D365 Row",pd.Series(dtype=float)),errors="coerce")
        .dropna().astype(int).unique().tolist()
    )
    if available_rows:
        row=st.selectbox("D365 Row to correct",available_rows)
        selected=u[pd.to_numeric(u["D365 Row"],errors="coerce").fillna(-1).astype(int)==int(row)].iloc[0]

        c1,c2,c3,c4=st.columns(4)
        c1.metric("Store",str(selected.get("Store Code","")))
        c2.metric("Receipt ID",str(selected.get("Receipt ID","")))
        c3.metric("Current Auth",str(selected.get("Auth Code","")))
        c4.metric("D365 Tender",str(selected.get("D365 Tender",selected.get("Payment Type",""))))

        suggested=str(selected.get("Suggested Auth Code","")).strip()
        new_auth=st.text_input("Corrected Auth Code",value=suggested)
        st.caption(
            f"Evidence: {selected.get('Correction Evidence','')} | "
            f"Source: {selected.get('Evidence Source','')} | "
            f"Confidence: {selected.get('Correction Confidence','')}"
        )
        reason=st.text_area("Reason / Evidence Reference")

        if st.button("SUBMIT CORRECTION",type="primary"):
            if not new_auth.strip():
                st.error("Corrected Auth Code is mandatory.")
            elif not reason.strip():
                st.error("Reason / Evidence Reference is mandatory.")
            elif core.auth(new_auth)==core.auth(selected.get("Auth Code","")):
                st.error("Corrected Auth Code is the same as the current Auth Code.")
            else:
                db.append_correction_log(
                    row,
                    core.auth(new_auth),
                    reason,
                    username,
                    original_auth=str(selected.get("Auth Code","")).strip(),
                    store_code=str(selected.get("Store Code","")).strip(),
                    receipt_id=str(selected.get("Receipt ID","")).strip(),
                )
                st.success("Correction submitted for maker-checker approval.")
                st.rerun()

st.markdown("### Reconciliation Exceptions — Not Auth Corrections")
st.caption(
    "These unmatched D365 rows do not have sufficient evidence for a different Auth Code. "
    "They remain reconciliation/master-data/provider exceptions and cannot be manually changed here."
)
if other_exceptions.empty:
    st.info("No additional non-Auth reconciliation exceptions.")
else:
    st.dataframe(other_exceptions,use_container_width=True,hide_index=True)

st.divider()

# ------------------------------------------------------------- APPROVAL
st.subheader("2. Approval Queue")
pending=db.load_correction_log("PENDING APPROVAL")

if role not in {"Admin","Finance Manager","Finance Checker"}:
    st.info("Approval is restricted to Finance Checker, Finance Manager or Admin.")
elif pending.empty:
    st.success("No corrections are pending approval.")
else:
    # Never offer the current user's own requests for approval.
    eligible=pending[
        pending["Submitted By"].astype(str).str.lower()!=username.lower()
    ].copy()
    own=pending[
        pending["Submitted By"].astype(str).str.lower()==username.lower()
    ].copy()

    if not own.empty:
        st.warning(
            f"{len(own)} pending request(s) were submitted by you and are hidden from your approval list "
            "to enforce maker-checker segregation."
        )

    if eligible.empty:
        st.info("No correction requests are eligible for your approval.")
    else:
        st.dataframe(eligible,use_container_width=True,hide_index=True)

        ids=eligible["ID"].astype(int).tolist()
        correction_id=st.selectbox("Select Correction ID",ids)
        chosen=eligible[eligible["ID"].astype(int)==int(correction_id)].iloc[0]

        c1,c2,c3,c4=st.columns(4)
        c1.metric("Store",str(chosen.get("Store Code","")))
        c2.metric("Receipt ID",str(chosen.get("Receipt ID","")))
        c3.metric("Original Auth",str(chosen.get("Original Auth","")))
        c4.metric("New Auth",str(chosen.get("New Auth","")))

        approval_comment=st.text_area("Approval / Rejection Comment")
        a,b=st.columns(2)

        if a.button("APPROVE CORRECTION",type="primary",use_container_width=True):
            ok,msg=db.decide_correction(correction_id,"APPROVED",username,approval_comment)
            if ok:
                # Apply immediately to current session and recompute POS reconciliation.
                tender=db.apply_approved_corrections(r.get("tender",pd.DataFrame()))
                r["tender"]=tender

                cash=tender[
                    tender["D365 Payment"].astype(str).str.upper()=="CASH"
                ].copy() if not tender.empty else pd.DataFrame()
                tender_for_pos=tender[
                    tender["D365 Payment"].astype(str).str.upper()!="CASH"
                ].copy() if not tender.empty else tender.copy()

                matched,us,up=core.reconcile(
                    tender_for_pos,
                    r.get("pos",pd.DataFrame()),
                    1.0
                )
                matched=core.apply_bank_settlement(
                    matched,
                    r.get("bank",pd.DataFrame()),
                    1.0
                )
                settlement_batches=core.build_card_settlement_batches(matched)
                batch_result,bank_unmatched=bank_ext.reconcile_card_batches_advanced(
                    settlement_batches,r.get("bank",pd.DataFrame()),1.0
                )
                matched=bank_ext.propagate_verified_batches(matched,batch_result)
                r["settlement_batches"]=batch_result
                r["settlement_bank_unmatched"]=bank_unmatched
                r["matched"]=matched
                r["unmatched_sales"]=us
                r["unmatched_pos"]=up
                r["cash_transactions"]=cash
                r["carry_forward"]=core.make_carry_forward(us,up,None)
                st.session_state.ct_result=r
                st.success("Correction approved and applied to the current reconciliation session.")
                st.rerun()
            else:
                st.error(msg)

        if b.button("REJECT CORRECTION",use_container_width=True):
            if not approval_comment.strip():
                st.error("Rejection comment is mandatory.")
            else:
                ok,msg=db.decide_correction(correction_id,"REJECTED",username,approval_comment)
                if ok:
                    st.warning("Correction rejected. Original Auth Code remains unchanged.")
                    st.rerun()
                else:
                    st.error(msg)

st.divider()

# ------------------------------------------------------------- AUDIT
st.subheader("3. Correction Audit Trail")
history=db.load_correction_log()
st.dataframe(history,use_container_width=True,hide_index=True)

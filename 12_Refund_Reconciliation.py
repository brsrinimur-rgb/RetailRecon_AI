from __future__ import annotations
import io
import pandas as pd
import streamlit as st

import auth, theme, core, db
import bank_settlement_final as bsv

st.set_page_config(page_title="Refund Reconciliation", layout="wide", page_icon="↩️")
auth.require_login({"Admin", "Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "Refund Reconciliation"), unsafe_allow_html=True)
st.title("Refund Reconciliation")
st.info(
    "Every refund must be proven against a real, previously reconciled sale before it is accepted. "
    "A refund with no matching sale is an exception, never a silent pass-through. "
    "Bank verification of the refund debit is a separate step, same discipline as sale-side settlement."
)

r = st.session_state.get("ct_result")
matched_sales = r.get("matched", pd.DataFrame()) if r else pd.DataFrame()
if matched_sales.empty:
    st.warning(
        "No reconciled sales found in this session (run POS Reconciliation first). "
        "Refunds can still be uploaded and parsed, but none will be provable against an original "
        "sale until reconciliation has run."
    )

refund_files = st.file_uploader(
    "Upload refund / reversal file(s)",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
)
bank_files = st.file_uploader(
    "Upload bank statement for refund debit verification (optional)",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
)

if st.button("RUN REFUND RECONCILIATION", type="primary", use_container_width=True):
    if not refund_files:
        st.error("Upload at least one refund/reversal file.")
    else:
        parts = []
        skipped = []
        for f in refund_files:
            for sheet, df in core.read_upload(f).items():
                try:
                    x = core.normalize_refunds(df, source=f.name)
                    if not x.empty:
                        parts.append(x)
                    else:
                        skipped.append({"File": f.name, "Sheet": sheet, "Reason": "No usable refund rows"})
                except Exception as e:
                    skipped.append({"File": f.name, "Sheet": sheet, "Reason": str(e)})

        if not parts:
            st.error("No usable refund rows found in the uploaded file(s).")
            if skipped:
                st.dataframe(pd.DataFrame(skipped), use_container_width=True, hide_index=True)
        else:
            refunds = pd.concat(parts, ignore_index=True)
            result = core.reconcile_refunds(refunds, matched_sales)

            bank_parts = []
            for f in bank_files or []:
                for _, df in core.read_upload(f).items():
                    try:
                        b = core.normalize_bank(df, "Refund Bank Statement")
                        if b is not None and not b.empty:
                            bank_parts.append(b)
                    except Exception:
                        pass
            bank = pd.concat(bank_parts, ignore_index=True) if bank_parts else pd.DataFrame()
            if not bank.empty:
                result = bsv.verify_refund_bank_settlement(result, bank, tolerance=1.0)
            else:
                for c, default in {
                    "Bank Settled": False, "Bank Name": "", "Bank Date": pd.NaT,
                    "Bank Amount": float("nan"), "Refund Settlement Status": "Awaiting Bank Debit",
                }.items():
                    if c not in result.columns:
                        result[c] = default

            db.save_refund_reconciliation(result, user=st.session_state.user["username"])
            st.session_state["refund_result"] = result
            st.session_state["refund_skipped"] = pd.DataFrame(skipped)
            st.success(f"Refund reconciliation completed: {len(result)} refund row(s) processed and saved to the shared database.")

result = st.session_state.get("refund_result")
if result is None or result.empty:
    result = db.load_refund_reconciliation()
    if not result.empty:
        st.caption("Showing the most recently saved refund reconciliation (shared database).")

if result is not None and not result.empty:
    matched_n = int((result["Status"] == "Matched").sum())
    exc_n = int((result["Status"] == "Exception").sum())
    bank_settled_n = int(result.get("Bank Settled", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    total_amt = pd.to_numeric(result.get("Refund Amount", 0), errors="coerce").fillna(0).sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Refunds", len(result))
    k2.metric("Matched to Sale", matched_n)
    k3.metric("Exceptions", exc_n)
    k4.metric("Bank Debit Verified", bank_settled_n)
    st.caption(f"Total refund amount processed: SAR {total_amt:,.2f}")

    tabs = st.tabs(["All Refunds", "Exceptions", "Bank Verification"])
    with tabs[0]:
        st.dataframe(result, use_container_width=True, hide_index=True)
    with tabs[1]:
        exc = result[result["Status"] == "Exception"]
        if exc.empty:
            st.success("No refund exceptions. Every refund is proven against a matched sale.")
        else:
            st.dataframe(exc, use_container_width=True, hide_index=True)
    with tabs[2]:
        proven = result[result["Status"] == "Matched"].copy()
        if proven.empty:
            st.info("No proven refunds yet to verify against the bank.")
        else:
            settled = proven.get("Bank Settled", pd.Series(False, index=proven.index)).fillna(False).astype(bool)
            st.write(f"Bank-verified: {int(settled.sum())} / {len(proven)}")
            st.dataframe(proven, use_container_width=True, hide_index=True)
            st.warning("Refunds awaiting a bank debit remain open and are not considered fully closed.")

    skipped = st.session_state.get("refund_skipped")
    if isinstance(skipped, pd.DataFrame) and not skipped.empty:
        with st.expander("Skipped rows / files"):
            st.dataframe(skipped, use_container_width=True, hide_index=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        result.to_excel(w, index=False, sheet_name="Refund Reconciliation")
    st.download_button(
        "DOWNLOAD REFUND RECONCILIATION",
        data=out.getvalue(),
        file_name="RetailRecon_AI_Refund_Reconciliation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
else:
    st.info("No refund reconciliation has been run yet.")

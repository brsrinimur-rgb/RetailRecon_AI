from __future__ import annotations
import pandas as pd
import streamlit as st
import auth, theme, core, db

st.set_page_config(page_title="Late Transaction Adjustment JV", layout="wide")
auth.require_login({"Admin", "Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "Late Transaction Adjustment JV"), unsafe_allow_html=True)
st.title("Late Transaction Adjustment JV")
st.caption(
    "Use only after period close when a previously missing transaction arrives, or to reverse a "
    "prior entry. The original period remains locked; the correction posts through a controlled, "
    "individually-approved adjustment/reversal JV using the same Finance-confirmed GL mapping as "
    "the normal weekly JV - not a different accounting treatment."
)

ctrl = db.load_accounting_period_control("ULC")
c1, c2, c3 = st.columns(3)
c1.metric("Closed Through", ctrl.get("Closed Through Date") or "Not set")
c2.metric("Next Open Date", ctrl.get("Next Open Date") or "Not set")
c3.metric("Status", ctrl.get("Status") or "OPEN")

default_acc = pd.to_datetime(ctrl.get("Next Open Date", ""), errors="coerce")
if pd.isna(default_acc):
    default_acc = pd.Timestamp.today().normalize()

with st.form("adjustment_jv_form"):
    f1, f2 = st.columns(2)
    store = f1.text_input("Store Code", help="Must exist in D365_STORE_DISPLAY / Store Master (e.g. 601).")
    provider = f2.selectbox("Payment Type", ["MADA", "VISA", "MASTERCARD", "AMEX", "TABBY", "TAMARA", "TAP"])
    a1, a2 = st.columns(2)
    amt = a1.number_input(
        "Amount (SAR)", value=0.0, step=1.0,
        help="Positive = book a late/missing sale. Negative = reverse a prior entry.",
    )
    accounting_date = a2.date_input("JV Accounting Date", value=default_acc.date())
    source_date = st.date_input("Original Transaction Date (for Source Period only)", value=default_acc.date())
    reason = st.text_area("Reason / Case reference")
    submitted = st.form_submit_button("CREATE ADJUSTMENT JV", type="primary")

if submitted:
    if not store or not reason or amt == 0:
        st.error("Store, amount and reason are required.")
    else:
        acc_open, acc_msg = db.is_accounting_date_open(accounting_date, "ULC")
        if not acc_open:
            st.error("Posting period blocked: " + acc_msg)
        else:
            existing = db.load_adjustments()
            same_day = existing[
                (existing.get("Store", "") == store)
                & (existing.get("Accounting Date", "") == str(accounting_date))
            ] if not existing.empty else existing
            batch_seq = len(same_day) + 1 if same_day is not None and not same_day.empty else 1

            gl_config = db.load_gl_config()
            j = core.create_adjustment_jv(
                store, provider, amt, reason,
                gl=gl_config,
                commission_master=db.load_commission_rate_master(),
                accounting_date=accounting_date,
                period_control=ctrl,
                batch_seq=batch_seq,
                source_date=source_date,
            )
            if j.empty:
                st.error(
                    "Could not build an adjustment JV: unknown payment group or no D365 store "
                    "display name configured for this Store Code. Check GL Configuration / Store Master."
                )
            else:
                j = core.validate_jv(j, gl_config)
                if not bool(j["Validation Passed"].all()):
                    st.error("Adjustment JV failed D365 chart-of-accounts validation and was NOT saved:")
                    st.dataframe(
                        j[["Journal Batch", "Validation Errors"]].drop_duplicates(),
                        use_container_width=True, hide_index=True,
                    )
                else:
                    batch = db.record_adjustment_jv(
                        store, provider, amt, reason,
                        st.session_state.user["username"], j, accounting_date=str(accounting_date),
                    )
                    st.success(
                        f"Adjustment JV {batch} created and validated. It now requires approval in "
                        "JV Approval Center before it can be posted, exactly like a normal weekly JV."
                    )
                    st.dataframe(
                        j[["Journal Batch", "Account type", "Main Account", "Debit", "Credit", "Description"]],
                        use_container_width=True, hide_index=True,
                    )
                    st.rerun()

st.divider()
st.subheader("Adjustment Requests")
adjustments = db.load_adjustments()
st.dataframe(adjustments, use_container_width=True, hide_index=True)

if not adjustments.empty and "JV Batch" in adjustments.columns:
    linked = adjustments[adjustments["JV Batch"].astype(str) != ""]
    if not linked.empty:
        pick = st.selectbox("View JV lines for batch", [""] + linked["JV Batch"].tolist())
        if pick:
            jv_all = db.load_jv()
            lines = jv_all[jv_all["Journal Batch"] == pick] if not jv_all.empty else pd.DataFrame()
            if not lines.empty:
                st.dataframe(
                    lines[[c for c in [
                        "Journal Batch", "Account type", "Main Account", "Debit", "Credit",
                        "Description", "Balanced", "Validation Passed", "Approval Status", "D365 Status", "Voucher",
                    ] if c in lines.columns]],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("This batch is not (or no longer) in the JV table.")

import streamlit as st
import pandas as pd
from datetime import datetime
import auth, theme, db

st.set_page_config(page_title="D365 Posting Center", layout="wide")
auth.require_login({"Admin", "Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "D365 Posting Center"), unsafe_allow_html=True)
st.title("D365 Posting Center")

j = db.load_jv()
if j.empty:
    st.info("Create and approve JV first.")
    st.stop()

approved_mask = (j["Approval Status"] == "APPROVED") & (j["Balanced"] == True)

period_open = []
period_reason = []
for _, r in j.iterrows():
    acc_date = r.get("JV Accounting Date", r.get("Date",""))
    entity = r.get("Company accounts","ULC") or "ULC"
    ok, msg = db.is_accounting_date_open(acc_date, entity)
    period_open.append(bool(ok))
    period_reason.append(msg)

j["Accounting Period Open"] = period_open
j["Accounting Period Check"] = period_reason
approved_mask = approved_mask & j["Accounting Period Open"]
if "Validation Passed" in j.columns:
    # Final control gate before anything reaches D365: even an APPROVED,
    # balanced batch is refused here if it fails the chart-of-accounts check -
    # approval and validation are independent controls, both must hold.
    approved_mask = approved_mask & (j["Validation Passed"] == True)
approved = j[approved_mask]
batches = approved["Journal Batch"].drop_duplicates().tolist()
st.write("Approved posting queue:", len(batches))

not_postable = j[(j["Approval Status"] == "APPROVED") & ~approved_mask]["Journal Batch"].drop_duplicates().tolist()
if not_postable:
    st.error(
        f"{len(not_postable)} batch(es) are Approved but still blocked from posting "
        f"(unbalanced, failed D365 validation, or accounting period closed): {', '.join(not_postable)}"
    )
if st.button("PUSH APPROVED JV TO D365", type="primary", disabled=not bool(batches)):
    for n, b in enumerate(batches, 1):
        already_posted = (j.loc[j["Journal Batch"] == b, "D365 Status"] == "POSTED").all()
        if already_posted:
            continue
        voucher = f"D365-{datetime.now():%Y%m%d}-{n:04d}"
        db.update_jv_posting(b, voucher)
    st.success("Posting simulation completed with duplicate-posting protection.")
    st.rerun()

st.dataframe(db.load_jv(), use_container_width=True, hide_index=True)

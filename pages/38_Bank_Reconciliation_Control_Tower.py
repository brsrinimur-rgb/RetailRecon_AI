import io

import pandas as pd
import streamlit as st
import auth, theme
from logic import bank_reconciliation_report as bank_rpt

st.set_page_config(page_title="Bank Reconciliation Control Tower", layout="wide", page_icon="🏦")
auth.require_login({"Admin", "Finance Manager", "Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "Bank Reconciliation Control Tower"), unsafe_allow_html=True)

st.title("🏦 Bank Reconciliation Control Tower")
st.caption(
    "POS/D365 → Provider → Expected Settlement → Bank → Exception. "
    "Reads the settlement batches already built by the Settlement Batch Engine (page 18) — "
    "this page does not re-parse bank statements or re-run matching, it turns those already-decided "
    "results into a finance-facing dashboard, exception list, and one downloadable Excel workbook."
)

r = st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first, then Settlement Batch Engine (page 18).")
    st.stop()

batches = r.get("settlement_batches", pd.DataFrame())
if batches is None or batches.empty:
    st.info(
        "No settlement batches found yet. Go to **Settlement Batch Engine** (page 18), build the "
        "card/AMEX batches, upload your provider payout files and bank statement, and click "
        "**RUN SETTLEMENT BATCH CONTROL** — then come back here."
    )
    st.stop()

bank_unmatched = r.get("settlement_bank_unmatched", pd.DataFrame())

st.markdown("### Settings")
c1, c2, c3, c4 = st.columns(4)
amount_threshold = c1.number_input(
    "HIGH priority amount threshold (SAR)", 0.0, 1_000_000.0, 5000.0, 100.0,
    help="An exception's Expected Bank SAR at or above this amount is flagged HIGH priority.",
)
age_high_days = int(c2.number_input(
    "HIGH priority age (days)", 0, 60, 5, 1,
    help="An outstanding (not-received) exception at or beyond this many days old is flagged HIGH priority.",
))
delay_high_days = int(c3.number_input(
    "Late settlement threshold (days)", 0, 60, 5, 1,
    help="A received settlement that took this long (or longer) to hit the bank is labeled a Late Settlement exception.",
))
low_amount_threshold = c4.number_input(
    "LOW priority ceiling (SAR)", 0.0, 100_000.0, 500.0, 50.0,
    help="A fresh (1 day old or less), small exception under this amount is flagged LOW priority (monitoring only).",
)

report = bank_rpt.build_report(
    batches, bank_unmatched,
    amount_threshold=amount_threshold, age_high_days=age_high_days,
    delay_high_days=delay_high_days, low_amount_threshold=low_amount_threshold,
)
k = report["kpis"]

st.markdown("### Executive Dashboard")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Expected Settlements", f"SAR {k['Expected Settlements']:,.2f}")
m2.metric("Received in Bank", f"SAR {k['Received in Bank']:,.2f}")
m3.metric("Group Match %", f"{k['Group Match %']:.2f}%", help="Clean settlement groups ÷ total groups.")
m4.metric("Value Match %", f"{k['Value Match %']:.2f}%",
          help="SAR value of clean settlement groups ÷ total expected SAR value — catches a large single exception that a group-count % would hide.")

m5, m6, m7, m8 = st.columns(4)
m5.metric("Amount Differences", f"SAR {k['Amount Differences']:,.2f}")
m6.metric("Not Yet Received", f"SAR {k['Not Yet Received']:,.2f}")
m7.metric("Review Required", f"SAR {k['Review Required']:,.2f}")
m8.metric("Unidentified Bank Credits", f"SAR {k['Unidentified Bank Credits']:,.2f}")

m9, m10, m11, m12 = st.columns(4)
m9.metric("Allocated Bank Credits", f"SAR {k['Allocated Bank Credits']:,.2f}")
m10.metric("Total Bank Credits in Scope", f"SAR {k['Total Bank Credits in Scope']:,.2f}",
           help="Allocated + Unidentified — should equal every bank credit this run considered.")
m11.metric("Possible Duplicates", k["Possible Duplicates"])
m12.metric("Future-Dated Settlements", k["Future Dated Settlements"],
           help="Settlement Date is after today — a data quality issue, not a normal aging item.")

m13, m14, m15, m16 = st.columns(4)
m13.metric("Settlement Groups", k["Total Settlement Groups"])
m14.metric("Fully Matched", k["Fully Matched"])
m15.metric("Exceptions", k["Exceptions"])
avg_delay = k["Average Settlement Delay (days)"]
m16.metric("Average Settlement Delay", f"{avg_delay} days" if avg_delay is not None else "—")

oldest = k["Oldest Outstanding (days)"]
st.caption(f"Oldest outstanding (excluding future-dated items): {oldest} days" if oldest is not None else
           "Nothing outstanding.")

if k["Possible Duplicates"] or k["Future Dated Settlements"]:
    st.warning(
        f"Data quality flags: {k['Possible Duplicates']} possible duplicate settlement batch(es), "
        f"{k['Future Dated Settlements']} future-dated settlement(s). See the Exceptions list below."
    )

st.markdown("### 1. Bank Reconciliation Detail")
st.dataframe(bank_rpt.display_detail(report["detail"]), use_container_width=True, hide_index=True)

st.markdown("### 2. Exceptions — Finance works this list, not the full detail")
exc = report["exceptions"]
if exc.empty:
    st.success("No exceptions — every settlement group is cleanly matched.")
else:
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    exc = exc.assign(_o=exc["Priority"].map(order).fillna(9)).sort_values("_o").drop(columns="_o")
    show_cols = [c for c in [
        "Priority", "Exception", "Provider", "Store Code", "Settlement Date", "Settlement Batch ID",
        "Expected Bank Amount", "Actual Bank Amount", "Bank Difference",
        "Age", "Action", "Settlement Review Reason",
    ] if c in exc.columns]
    st.dataframe(exc[show_cols], use_container_width=True, hide_index=True)

st.markdown("### 3. Provider Summary")
st.caption("Group Match % = clean groups ÷ total groups. Value Match % = clean SAR value ÷ total expected SAR value.")
st.dataframe(report["provider_summary"], use_container_width=True, hide_index=True)

st.markdown("### 4. Store Summary")
st.dataframe(report["store_summary"], use_container_width=True, hide_index=True)

with st.expander("Store × Provider × Payment Type Summary — which provider is driving a store's outstanding balance"):
    st.dataframe(report["store_provider_summary"], use_container_width=True, hide_index=True)

st.markdown("### 5. Aging (outstanding settlements, excluding future-dated)")
if report["aging"].empty:
    st.info("Nothing outstanding — no aging to show.")
else:
    st.dataframe(report["aging"], use_container_width=True, hide_index=True)

st.markdown("### 6. Unmatched Bank Credits")
st.caption(
    "Money that landed in the bank but this run could not tie to any expected settlement. "
    "Kept visible rather than dropped — a real receipt with no home is exactly what Finance "
    "needs to chase down."
)
if report["bank_unmatched"].empty:
    st.success("No unmatched bank credits.")
else:
    st.dataframe(report["bank_unmatched"], use_container_width=True, hide_index=True)

with st.expander("Matching Audit (which evidence tied each settlement)"):
    st.dataframe(report["matching_audit"], use_container_width=True, hide_index=True)

with st.expander("Control Totals (proves the detail sheet ties back to the Dashboard)"):
    st.dataframe(report["control_totals"], use_container_width=True, hide_index=True)
    st.caption(
        "Matching itself is still 1 settlement batch ↔ 1 bank credit (from page 18's engine). "
        "One bank credit funding several settlements, or one settlement paid across several "
        "credits, is not yet supported — those cases correctly stay in Review/Pending today "
        "rather than being guessed at."
    )

st.markdown("### 7. Download Full Report")
buffer = io.BytesIO()
bank_rpt.write_excel(report, buffer)
st.download_button(
    "⬇️ DOWNLOAD BANK RECONCILIATION REPORT",
    data=buffer.getvalue(),
    file_name="RetailReconAI_Bank_Reconciliation_Report.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

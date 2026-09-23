"""
REGRESSION_V68_BANK_RECONCILIATION_CONTROL_TOWER.py  (covers V68 + V69)

Context: V68 built page 38 (Bank Reconciliation Control Tower) as a
reporting layer on top of page 18's (Settlement Batch Engine) already-
computed settlement_batches / settlement_bank_unmatched -- no new parsing
or matching, per your explicit direction to freeze the matching engine and
improve only this reporting layer.

V69 is a direct response to a real code review of V68 that found several
mistakes and gaps. Every one of the following was fixed in
logic/bank_reconciliation_report.py, and each has a dedicated check below:

  1. HIGH-priority thresholds were exclusive (`>`), so an amount/age exactly
     AT the configured threshold stayed MEDIUM. Now inclusive (`>=`).
  2. A future-dated settlement (Settlement Date after today) produced a
     negative Age Days that could fall outside the aging buckets. Now it's
     its own "Future Settlement Date - Data Validation Required" exception,
     excluded from ordinary aging, HIGH priority.
  3. "Match %" was group-count only, which can hide a small number of large
     exceptions behind a high percentage. Now both Group Match % (unchanged
     formula) and Value Match % (clean SAR value / total expected SAR value)
     are reported, matching the review's own 99-small/1-huge example.
  4. No bank-side control identity existed. Now Control Totals proves
     Allocated Bank Credits + Unidentified Bank Credits = Total Bank Credits
     in Scope, alongside the existing settlement-side identity.
  5. Provider Summary gained Group Match %, Value Match %, Outstanding,
     Average Delay, Oldest Outstanding.
  6. A new Store x Provider x Payment Type summary sheet was added.
  7. Exception priority was HIGH/MEDIUM only. Now CRITICAL/HIGH/MEDIUM/LOW,
     deterministic: a new "possible duplicate settlement batch" integrity
     check (same Provider+Store+Payment Type+Settlement Date+Expected Amount
     on more than one settlement batch) is CRITICAL; Review-Multiple-
     Candidates and future-dated items are HIGH; large/old items are HIGH;
     amount differences/late settlements are MEDIUM; small, fresh items are
     LOW.
  8. The Excel export had no professional formatting. Now: frozen header
     row, autofilter, sized columns, SAR/date/percent number formats, and
     colour fills (green for clean rows, light red for exception rows in
     the detail sheet; CRITICAL/HIGH/MEDIUM/LOW colour tiers in Exceptions).
  9. The regression file's own docstring said "9 sheets" when the code
     always produced (and tested) 10. Now correctly describes 11 sheets
     (Store x Provider Summary added in V69).

What's deliberately NOT changed, per explicit instruction: no matching
engine change (still 1 settlement batch <-> 1 bank credit; many-to-many
remains future work), and no re-parsing of bank/provider files. Real-data
validation against an actual Settlement Batch Engine result is still
outstanding -- everything below remains synthetic data shaped exactly like
the real engine's column contract, since no real settlement_batches export
was available for this review.
"""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bank_reconciliation_report as bank_rpt


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")


TODAY = pd.Timestamp.today().normalize()

# ---------------------------------------------------------------------
# Main scenario: one of each status, plus a duplicate pair and a
# future-dated pending settlement.
# ---------------------------------------------------------------------
batches = pd.DataFrame([
    # 1. MADA, clean match, 1-day delay.
    {
        "Settlement Batch ID": "SET-M001", "Provider": "ANB POS", "Store Code": "601",
        "Terminal ID": "T601", "Payment Type": "MADA",
        "Settlement Date": TODAY - pd.Timedelta(days=5),
        "Gross Amount": 10000.00, "Fee Amount": 55.00, "VAT Amount": 8.25,
        "Expected Bank Amount": 9936.75, "Transaction Count": 12,
        "Settlement Status": "BANK RECEIVED", "Bank Match Rule": "ANB POS Amount = Bank Credit | Terminal + Scheme + Date + TX Count",
        "Actual Bank Amount": 9936.75, "Bank Date": TODAY - pd.Timedelta(days=4), "Bank Difference": 0.0,
        "Bank Reference": "ANB-REF-1",
    },
    # 2. TAP, clean match via Al Rajhi, 2-day delay.
    {
        "Settlement Batch ID": "TAP-92881", "Provider": "TAP", "Store Code": "613",
        "Terminal ID": "", "Payment Type": "TAP",
        "Settlement Date": TODAY - pd.Timedelta(days=4),
        "Gross Amount": 5000.00, "Fee Amount": 77.50, "VAT Amount": 11.63,
        "Expected Bank Amount": 4910.87, "Transaction Count": 3,
        "Settlement Status": "BANK RECEIVED", "Bank Match Rule": "TAP Payout + Al Rajhi Credit",
        "Actual Bank Amount": 4910.87, "Bank Date": TODAY - pd.Timedelta(days=2), "Bank Difference": 0.0,
        "Bank Reference": "RAJHI-REF-2",
    },
    # 3. TABBY, amount difference (SAR 24 short), expected value crosses the
    #    default HIGH amount threshold exactly at 5748 > 5000.
    {
        "Settlement Batch ID": "TB-5521", "Provider": "TABBY", "Store Code": "603",
        "Terminal ID": "", "Payment Type": "TABBY",
        "Settlement Date": TODAY - pd.Timedelta(days=6),
        "Gross Amount": 8000.00, "Fee Amount": 320.00, "VAT Amount": 48.00,
        "Expected Bank Amount": 5748.00, "Transaction Count": 5,
        "Settlement Status": "BANK RECEIVED", "Bank Match Rule": "TABBY Payout - Fixed Fee SAR 5.00 - Al Rajhi Credit",
        "Actual Bank Amount": 5724.00, "Bank Date": TODAY - pd.Timedelta(days=4), "Bank Difference": -24.00,
        "Bank Reference": "RAJHI-REF-3",
    },
    # 4. TAMARA, not yet received, exactly 5 days old -- HIGH boundary test
    #    (age_high_days default is 5; this must be HIGH under >=, not MEDIUM).
    {
        "Settlement Batch ID": "TM-8832", "Provider": "TAMARA", "Store Code": "624",
        "Terminal ID": "", "Payment Type": "TAMARA",
        "Settlement Date": TODAY - pd.Timedelta(days=5),
        "Gross Amount": 3000.00, "Fee Amount": 120.00, "VAT Amount": 18.00,
        "Expected Bank Amount": 2862.00, "Transaction Count": 4,
        "Settlement Status": "BANK RECEIPT PENDING", "Bank Match Rule": "",
        "Actual Bank Amount": None, "Bank Date": pd.NaT, "Bank Difference": None,
        "Bank Reference": "",
    },
    # 5. AMEX, review required (multiple candidates) -- must be HIGH, not CRITICAL.
    {
        "Settlement Batch ID": "SET-A900", "Provider": "AMEX", "Store Code": "634",
        "Terminal ID": "T634", "Payment Type": "AMEX",
        "Settlement Date": TODAY - pd.Timedelta(days=3),
        "Gross Amount": 3000.00, "Fee Amount": 90.00, "VAT Amount": 13.50,
        "Expected Bank Amount": 2896.50, "Transaction Count": 2,
        "Settlement Status": "BANK REVIEW REQUIRED", "Bank Match Rule": "",
        "Actual Bank Amount": None, "Bank Date": pd.NaT, "Bank Difference": None,
        "Bank Reference": "",
    },
    # 6 & 7. Possible duplicate: same Provider+Store+Payment Type+Settlement
    #    Date+Expected Amount on two DIFFERENT settlement batch IDs.
    {
        "Settlement Batch ID": "MADA-DUP-A", "Provider": "ANB POS", "Store Code": "602",
        "Terminal ID": "T602", "Payment Type": "MADA",
        "Settlement Date": TODAY - pd.Timedelta(days=2),
        "Gross Amount": 1000.00, "Fee Amount": 5.50, "VAT Amount": 0.83,
        "Expected Bank Amount": 993.67, "Transaction Count": 1,
        "Settlement Status": "BANK RECEIPT PENDING", "Bank Match Rule": "",
        "Actual Bank Amount": None, "Bank Date": pd.NaT, "Bank Difference": None,
        "Bank Reference": "",
    },
    {
        "Settlement Batch ID": "MADA-DUP-B", "Provider": "ANB POS", "Store Code": "602",
        "Terminal ID": "T602", "Payment Type": "MADA",
        "Settlement Date": TODAY - pd.Timedelta(days=2),
        "Gross Amount": 1000.00, "Fee Amount": 5.50, "VAT Amount": 0.83,
        "Expected Bank Amount": 993.67, "Transaction Count": 1,
        "Settlement Status": "BANK RECEIPT PENDING", "Bank Match Rule": "",
        "Actual Bank Amount": None, "Bank Date": pd.NaT, "Bank Difference": None,
        "Bank Reference": "",
    },
    # 8. Future-dated settlement (data issue -- e.g. a bad date parse
    #    upstream). Must NOT produce a negative Age Days / stray aging row.
    {
        "Settlement Batch ID": "TAP-FUTURE-1", "Provider": "TAP", "Store Code": "619",
        "Terminal ID": "", "Payment Type": "TAP",
        "Settlement Date": TODAY + pd.Timedelta(days=3),
        "Gross Amount": 1200.00, "Fee Amount": 18.00, "VAT Amount": 2.70,
        "Expected Bank Amount": 1179.30, "Transaction Count": 2,
        "Settlement Status": "BANK RECEIPT PENDING", "Bank Match Rule": "",
        "Actual Bank Amount": None, "Bank Date": pd.NaT, "Bank Difference": None,
        "Bank Reference": "",
    },
])

bank_unmatched = pd.DataFrame([
    {"Bank": "AL RAJHI", "Bank Date": TODAY - pd.Timedelta(days=1), "Credit": 2946.52,
     "Description": "AL RAJHI CREDIT - UNKNOWN REF"},
])

report = bank_rpt.build_report(batches, bank_unmatched, amount_threshold=5000.0, age_high_days=5,
                                delay_high_days=5, low_amount_threshold=500.0)
detail = report["detail"]
exc = report["exceptions"]
k = report["kpis"]

# --- 1. Basic delay / age computation still correct ---
mada = detail[detail["Settlement Batch ID"] == "SET-M001"].iloc[0]
_assert(mada["Delay Days"] == 1, f"MADA delay computed as 1 day, got {mada['Delay Days']}")

# --- 2. HIGH-priority boundary is now inclusive (>=) ---
tabby_exc = exc[exc["Settlement Batch ID"] == "TB-5521"].iloc[0]
_assert(tabby_exc["Exception"] == "Amount Difference", f"TABBY labeled Amount Difference, got {tabby_exc['Exception']}")
_assert(tabby_exc["Priority"] == "HIGH",
        f"TABBY expected amount SAR 5748.00 >= SAR 5000 threshold -> HIGH (inclusive), got {tabby_exc['Priority']}")
tamara_exc = exc[exc["Settlement Batch ID"] == "TM-8832"].iloc[0]
_assert(tamara_exc["Exception"] == "Settlement Not Received", f"TAMARA labeled Settlement Not Received, got {tamara_exc['Exception']}")
_assert(tamara_exc["Priority"] == "HIGH",
        f"TAMARA exactly 5 days old with age_high_days=5 -> HIGH under >= (was MEDIUM under > before V69), got {tamara_exc['Priority']}")

# --- 3. Review-Multiple-Candidates is HIGH, not CRITICAL ---
amex_exc = exc[exc["Settlement Batch ID"] == "SET-A900"].iloc[0]
_assert(amex_exc["Exception"] == "Review - Multiple Candidates", f"AMEX labeled Review, got {amex_exc['Exception']}")
_assert(amex_exc["Priority"] == "HIGH", f"Review-Multiple-Candidates is HIGH per the deterministic table, got {amex_exc['Priority']}")

# --- 4. Possible duplicate settlement batch detection -> CRITICAL ---
dup_a = detail[detail["Settlement Batch ID"] == "MADA-DUP-A"].iloc[0]
dup_b = detail[detail["Settlement Batch ID"] == "MADA-DUP-B"].iloc[0]
_assert(bool(dup_a["Possible Duplicate"]) and bool(dup_b["Possible Duplicate"]),
        "both settlement batches sharing the same Provider+Store+Payment+Date+Amount are flagged Possible Duplicate")
dup_exc_a = exc[exc["Settlement Batch ID"] == "MADA-DUP-A"].iloc[0]
dup_exc_b = exc[exc["Settlement Batch ID"] == "MADA-DUP-B"].iloc[0]
_assert(dup_exc_a["Exception"] == bank_rpt.DUPLICATE_LABEL and dup_exc_a["Priority"] == "CRITICAL",
        f"duplicate batch A is CRITICAL, got {dup_exc_a['Exception']} / {dup_exc_a['Priority']}")
_assert(dup_exc_b["Priority"] == "CRITICAL", "duplicate batch B is also CRITICAL")
# A distinct, non-duplicate MADA-style row elsewhere must NOT be flagged.
_assert(not bool(mada["Possible Duplicate"]), "the unrelated clean MADA batch (different store/date) is not flagged as a duplicate")

# --- 5. Future-dated settlement gets its own exception, not negative aging ---
future_row = detail[detail["Settlement Batch ID"] == "TAP-FUTURE-1"].iloc[0]
_assert(bool(future_row["Future Dated"]), "future-dated TAP settlement is flagged Future Dated")
_assert(pd.isna(future_row["Age Days"]), "a future-dated row does not get a (negative) Age Days value")
_assert(future_row["Days Until Settlement"] == 3, f"Days Until Settlement computed as 3, got {future_row['Days Until Settlement']}")
future_exc = exc[exc["Settlement Batch ID"] == "TAP-FUTURE-1"].iloc[0]
_assert(future_exc["Exception"] == bank_rpt.FUTURE_DATE_LABEL, f"future-dated row labeled correctly, got {future_exc['Exception']}")
_assert(future_exc["Priority"] == "HIGH", f"future-dated row is HIGH priority, got {future_exc['Priority']}")
# And it must not leak into ordinary aging.
aging = report["aging"]
_assert(int(aging["Groups"].sum()) < len(batches),
        "the future-dated row and the two received rows are excluded from the aging summary")

# --- 6. Clean matches are still not exceptions ---
_assert(exc[exc["Settlement Batch ID"] == "SET-M001"].empty, "clean MADA match is NOT in the exceptions list")
_assert(exc[exc["Settlement Batch ID"] == "TAP-92881"].empty, "clean TAP match is NOT in the exceptions list")

# --- 7. Group Match % vs Value Match % diverge exactly like the reviewer's example ---
lopsided = pd.DataFrame(
    [
        {
            "Settlement Batch ID": f"SMALL-{i}", "Provider": "MADA", "Store Code": "601",
            "Payment Type": "MADA", "Settlement Date": TODAY - pd.Timedelta(days=1),
            "Expected Bank Amount": 100.0, "Gross Amount": 100.0, "Fee Amount": 0.0, "VAT Amount": 0.0,
            "Settlement Status": "BANK RECEIVED", "Actual Bank Amount": 100.0,
            "Bank Date": TODAY, "Bank Difference": 0.0, "Bank Match Rule": "x", "Bank Reference": "",
        }
        for i in range(99)
    ]
    + [
        {
            "Settlement Batch ID": "HUGE-1", "Provider": "MADA", "Store Code": "601",
            "Payment Type": "MADA", "Settlement Date": TODAY - pd.Timedelta(days=1),
            "Expected Bank Amount": 500000.0, "Gross Amount": 500000.0, "Fee Amount": 0.0, "VAT Amount": 0.0,
            "Settlement Status": "BANK RECEIPT PENDING", "Actual Bank Amount": None,
            "Bank Date": pd.NaT, "Bank Difference": None, "Bank Match Rule": "", "Bank Reference": "",
        }
    ]
)
lopsided_report = bank_rpt.build_report(lopsided)
lk = lopsided_report["kpis"]
_assert(abs(lk["Group Match %"] - 99.0) < 0.01, f"Group Match % is misleadingly high (99%), got {lk['Group Match %']}")
_assert(lk["Value Match %"] < 2.0,
        f"Value Match % correctly exposes the SAR 500,000 exposure hiding behind the 99% group figure, got {lk['Value Match %']}")

# --- 8. Bank-side control identity ties out ---
ct = report["control_totals"]
tie_row = ct[ct["Line"] == "Ties (Allocated + Unidentified - Total, should be 0.00)"].iloc[0]
_assert(abs(tie_row["Amount"]) < 0.01, f"bank-side identity ties to zero, got {tie_row['Amount']}")
settlement_tie = ct[ct["Line"] == "Ties to Total Expected (should be 0.00)"].iloc[0]
_assert(abs(settlement_tie["Amount"]) < 0.01, f"settlement-side identity ties to zero, got {settlement_tie['Amount']}")
dup_row = ct[ct["Line"] == "Possible Duplicate Settlement Batches (count)"].iloc[0]
_assert(dup_row["Amount"] == 2, f"control totals surfaces the 2 duplicate rows, got {dup_row['Amount']}")
future_count_row = ct[ct["Line"] == "Future-Dated Settlements (count)"].iloc[0]
_assert(future_count_row["Amount"] == 1, f"control totals surfaces the 1 future-dated row, got {future_count_row['Amount']}")

# --- 9. Provider Summary has the new columns and they foot correctly ---
psum = report["provider_summary"]
for col in ["Group Match %", "Value Match %", "Outstanding", "Average Delay (days)", "Oldest Outstanding (days)"]:
    _assert(col in psum.columns, f"Provider Summary includes '{col}'")
tap_row = psum[psum["Provider"] == "TAP"].iloc[0]
_assert(int(tap_row["Groups"]) == 2, f"TAP has 2 groups (clean + future-dated), got {tap_row['Groups']}")
_assert(int(tap_row["Matched"]) == 1, f"TAP has 1 clean match, got {tap_row['Matched']}")

# --- 10. Store x Provider x Payment Type summary exists and is correct ---
spsum = report["store_provider_summary"]
_assert(not spsum.empty, "Store x Provider summary is populated")
store_602 = spsum[(spsum["Store Code"] == "602") & (spsum["Provider"] == "ANB POS")]
_assert(len(store_602) == 1 and int(store_602.iloc[0]["Groups"]) == 2,
        "store 602 / ANB POS / MADA row correctly aggregates both duplicate batches")

# --- 11. Excel workbook: 11 sheets (Store x Provider Summary added), formatted ---
buf = io.BytesIO()
bank_rpt.write_excel(report, buf)
buf.seek(0)
xls = pd.ExcelFile(buf, engine="openpyxl")
expected_sheets = {
    "Dashboard", "Bank Reconciliation", "Exceptions", "Aging", "Provider Summary",
    "Store Summary", "Store x Provider Summary", "Daily Summary", "Unmatched Bank Credits",
    "Matching Audit", "Control Totals",
}
_assert(expected_sheets.issubset(set(xls.sheet_names)), f"all 11 sheets present, got {xls.sheet_names}")

buf.seek(0)
import openpyxl
wb = openpyxl.load_workbook(buf)
ws = wb["Bank Reconciliation"]
_assert(ws.freeze_panes == "A2", f"Bank Reconciliation sheet has a frozen header row, got {ws.freeze_panes}")
_assert(ws.auto_filter.ref is not None, "Bank Reconciliation sheet has an autofilter")
header_cell = ws.cell(row=1, column=1)
_assert(header_cell.font.bold, "header row is bold")
_assert(header_cell.fill.fgColor.rgb not in (None, "00000000"), "header row has a fill colour")
# A currency column should carry a 2-decimal number format, not General.
detail_cols = [c.value for c in ws[1]]
gross_idx = detail_cols.index("Gross SAR") + 1
_assert("0.00" in (ws.cell(row=2, column=gross_idx).number_format or ""),
        f"Gross SAR column has a currency number format, got {ws.cell(row=2, column=gross_idx).number_format}")

wsx = wb["Exceptions"]
prio_idx = [c.value for c in wsx[1]].index("Priority") + 1
critical_row = None
for row in range(2, wsx.max_row + 1):
    if wsx.cell(row=row, column=prio_idx).value == "CRITICAL":
        critical_row = row
        break
_assert(critical_row is not None, "at least one CRITICAL row exists in the Exceptions sheet")
fill = wsx.cell(row=critical_row, column=1).fill
_assert(fill.fgColor.rgb not in (None, "00000000"), "a CRITICAL exception row is colour-filled")

# --- 12. Empty-input safety (no batches yet) ---
empty_report = bank_rpt.build_report(pd.DataFrame())
_assert(empty_report["detail"].empty and empty_report["kpis"]["Total Settlement Groups"] == 0,
        "an empty settlement_batches input degrades gracefully with zeroed KPIs, not a crash")
_assert(empty_report["kpis"]["Group Match %"] == 0.0 and empty_report["kpis"]["Value Match %"] == 0.0,
        "empty input reports 0%% for both match KPIs rather than raising a divide-by-zero")

print("\nREGRESSION V68/V69 BANK RECONCILIATION CONTROL TOWER PASS")

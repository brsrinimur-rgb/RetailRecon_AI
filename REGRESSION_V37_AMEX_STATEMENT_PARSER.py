"""
REGRESSION_V37_AMEX_STATEMENT_PARSER.py

Proves core.is_amex_statement_file() / core.normalize_amex_statement()
against the REAL uploaded file (SE-2026_07_31-9710107967.xlsx), not a
synthetic fixture. Confirms parsed totals tie exactly to the statement's
own declared totals (Summary sheet: 23 submissions, gross 422,165.04, net
409,500.09; Submissions sheet: 13 payments, total wires 333,256.82).

Run: python3 REGRESSION_V37_AMEX_STATEMENT_PARSER.py
(requires the real file to be present at the path below)
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_v37",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v37"]=core; sp.loader.exec_module(core)

AMEX_FILE=Path("/mnt/user-data/uploads/SE-2026_07_31-9710107967.xlsx")
assert AMEX_FILE.exists(), f"real AMEX statement not found at {AMEX_FILE}"

class UploadBytes:
    def __init__(self,path):
        self.name=Path(path).name
        self._data=Path(path).read_bytes()
    def getvalue(self):
        return self._data

sheets=core.read_upload(UploadBytes(AMEX_FILE))
assert "Submissions" in sheets

sub_sheet_df=sheets["Submissions"]

# 1. Detection
assert core.is_amex_statement_file(AMEX_FILE.name, sub_sheet_df) is True
assert core.is_amex_statement_file(AMEX_FILE.name, sheets.get("VAT BreakDown")) is False, \
    "VAT BreakDown sheet must NOT be misdetected as the Submissions shape"
print("[PASS] is_amex_statement_file(): correctly detects the real Submissions sheet, "
      "correctly rejects the VAT BreakDown sheet.")

# 2. Parse
payments,submissions=core.normalize_amex_statement(sub_sheet_df,AMEX_FILE.name)
assert not payments.empty and not submissions.empty

# 3. Confirmed real counts from the statement's own "Total submissions" /
#    Summary rows.
assert len(submissions)==23, f"expected 23 submissions, got {len(submissions)}"
assert len(payments)==13, f"expected 13 payments (Sarie wires), got {len(payments)}"
print(f"[PASS] Row counts match the statement's own declared counts: "
      f"{len(submissions)} submissions, {len(payments)} payments.")

# 4. Confirmed real totals (Summary sheet: Total Net Amount 409,500.09;
#    Submissions sheet Total submissions row: gross DB=333,256.82 (wires),
#    net CR=409,500.09; Summary "Submissions (23 submissions)" gross =
#    422,165.04).
gross_total=round(float(submissions["Gross Amount"].sum()),2)
net_total=round(float(submissions["Net Amount"].sum()),2)
wire_total=round(float(payments["Wire Amount"].sum()),2)

assert gross_total==422165.04, f"gross total mismatch: {gross_total}"
assert net_total==409500.09, f"net total mismatch: {net_total}"
assert wire_total==333256.82, f"wire total mismatch: {wire_total}"
print(f"[PASS] Parsed totals tie EXACTLY to the statement's own declared figures: "
      f"gross={gross_total:,.2f}, net={net_total:,.2f}, wires={wire_total:,.2f}.")

# 5. The one genuinely-unpaid submission (Paid='N') must be identifiable,
#    not silently dropped or miscounted as paid.
unpaid=submissions[submissions["Paid"]=="N"]
assert len(unpaid)==1, f"expected exactly 1 unpaid submission, got {len(unpaid)}"
row=unpaid.iloc[0]
assert row["Terminal ID"]=="55610708"
assert round(float(row["Gross Amount"]),2)==77000.00
assert row["Date"].date().isoformat()=="2026-07-31"
print("[PASS] The genuinely-unpaid submission (terminal 55610708, SAR 77,000.00, "
      "31-Jul-2026, Paid='N') is correctly identified, not dropped or miscounted.")

# 6. Spot-check one specific real submission row against the raw file
#    (terminal 55610701, first submission, 10-Jul-2026, gross 51,500.00,
#    net 49,955.00).
first=submissions.iloc[0]
assert first["Terminal ID"]=="55610701"
assert round(float(first["Gross Amount"]),2)==51500.00
assert round(float(first["Net Amount"]),2)==49955.00
print("[PASS] Spot-checked real row (terminal 55610701, SAR 51,500.00 gross / "
      "SAR 49,955.00 net) parses exactly as it appears in the raw file.")

# 7. Spot-check one specific real payment (wire) row (11-Jul-2026, SAR 52,263.47).
first_pay=payments.iloc[0]
assert first_pay["Date"].date().isoformat()=="2026-07-11"
assert round(float(first_pay["Wire Amount"]),2)==52263.47
print("[PASS] Spot-checked real payment row (11-Jul-2026, SAR 52,263.47 wire) "
      "parses exactly as it appears in the raw file.")

print("REGRESSION V37 AMEX STATEMENT PARSER PASS (against real uploaded file)")

# ---------------------------------------------------------------------
# Level 1 batch matching, tested against a batch built from REAL
# submission data (terminal 55610701, 2026-07-10, gross 51,500.00).
# ---------------------------------------------------------------------
from logic import bank_settlement_extension as bank_ext

real_batch=pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B1","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"55610701",
    "Settlement Date":pd.Timestamp("2026-07-10"),
    "Gross Amount":51500.00,
}])
res=bank_ext.reconcile_amex_batches_via_statement(real_batch,submissions,1.0)
assert len(res)==1
assert res.iloc[0]["AMEX Statement Status"]=="AMEX SUBMISSION MATCHED - AWAITING BANK CONFIRMATION", res.iloc[0].to_dict()
# The reason text must reflect the CURRENT chain state, not a stale claim.
# After V38, wire->bank confirmation is built; what's actually outstanding
# is the submission/batch -> specific wire allocation, not "no bank
# statement available". Asserted explicitly so this can't silently go
# stale again the way the earlier V27-V31 documentation did.
_reason=res.iloc[0]["AMEX Statement Reason"]
assert "reconcile_amex_wires_to_bank" in _reason, _reason
assert "already implemented" in _reason, _reason
assert "not built" not in _reason, f"stale claim resurfaced: {_reason}"
assert round(float(res.iloc[0]["AMEX Statement Gross"]),2)==51500.00
print("[PASS] Real batch (terminal 55610701, 10-Jul-2026, SAR 51,500.00) ties to the real "
      "statement submission and correctly stops at 'AWAITING BANK CONFIRMATION', not BANK RECEIVED.")

# The genuinely-unpaid real submission (terminal 55610708, 31-Jul, SAR 77,000)
# must route to REVIEW REQUIRED, not silently settle.
unpaid_batch=pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B2","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"55610708",
    "Settlement Date":pd.Timestamp("2026-07-31"),
    "Gross Amount":77000.00,
}])
res2=bank_ext.reconcile_amex_batches_via_statement(unpaid_batch,submissions,1.0)
assert res2.iloc[0]["AMEX Statement Status"]=="AMEX REVIEW REQUIRED"
assert "Paid=N" in res2.iloc[0]["AMEX Statement Reason"]
print("[PASS] Real unpaid submission (terminal 55610708, SAR 77,000.00) correctly refuses "
      "to settle -- routes to AMEX REVIEW REQUIRED, citing Paid=N.")

# Synthetic multi-submission-same-day grouping (no real example exists in
# this particular statement period, but the summing rule must still hold).
multi_subs=pd.DataFrame([
    {"Terminal ID":"99999999","Date":pd.Timestamp("2026-07-15"),"Ref":"R1",
     "Gross Amount":1000.0,"Net Amount":970.0,"Paid":"P"},
    {"Terminal ID":"99999999","Date":pd.Timestamp("2026-07-15"),"Ref":"R2",
     "Gross Amount":500.0,"Net Amount":485.0,"Paid":"P"},
])
multi_batch=pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B3","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"99999999",
    "Settlement Date":pd.Timestamp("2026-07-15"),
    "Gross Amount":1500.0,
}])
res3=bank_ext.reconcile_amex_batches_via_statement(multi_batch,multi_subs,1.0)
assert res3.iloc[0]["AMEX Statement Status"]=="AMEX SUBMISSION MATCHED - AWAITING BANK CONFIRMATION"
assert res3.iloc[0]["AMEX Submission Refs"]=="R1|R2"
print("[PASS] Synthetic multi-submission-same-day case: two submissions (1000+500) correctly "
      "sum to tie a 1500 batch, both refs cited.")

# Mismatch case must refuse to settle.
mismatch_batch=pd.DataFrame([{
    "Settlement Source":"AMEX","Settlement Batch ID":"B4","Provider":"AMEX",
    "Store Code":"601","Terminal ID":"99999999",
    "Settlement Date":pd.Timestamp("2026-07-15"),
    "Gross Amount":9999.0,
}])
res4=bank_ext.reconcile_amex_batches_via_statement(mismatch_batch,multi_subs,1.0)
assert res4.iloc[0]["AMEX Statement Status"]=="AMEX REVIEW REQUIRED"
assert "does not tie" in res4.iloc[0]["AMEX Statement Reason"]
print("[PASS] Mismatched gross amount correctly refuses to settle, routes to REVIEW REQUIRED.")

print("REGRESSION V37 AMEX LEVEL 1 BATCH MATCHING PASS")

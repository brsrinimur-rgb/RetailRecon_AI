"""
REGRESSION_POS_GL_SUMMARY_AND_EMPTY_INPUT.py

Covers two things found and fixed in this review:

1. Store-wise/GL-wise Summary sheet (V42.2): store_summary Status is now
   tolerance-based, not a constant "REVIEW" -- and gl_summary is a full
   GL-account comparison (GL Total vs POS Total), not unmatched-only.

2. Empty-input crash: (a) merged.apply(axis=1) on a zero-row frame --
   fixed in the uploaded V42.3 pass; (b) pd.DataFrame(rows) with an empty
   `rows` list produces a DataFrame with ZERO COLUMNS, so d.Status raised
   AttributeError -- STILL crashing after (a)'s fix. Fixed here.

Run: python3 REGRESSION_POS_GL_SUMMARY_AND_EMPTY_INPUT.py
"""
from pathlib import Path
import sys
import pandas as pd

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from logic import pos_gl_reconciliation as pgl

pos = pd.DataFrame([
    {"store_code": "601", "pos_date": "2026-07-01", "pos_amount": 1000.00, "provider": "MADA",
     "reference": "A1", "auth_code": "A1", "source_row": 1, "merchant_id": "M1"},
    {"store_code": "602", "pos_date": "2026-07-01", "pos_amount": 500.00, "provider": "MADA",
     "reference": "A2", "auth_code": "A2", "source_row": 2, "merchant_id": "M1"},
    {"store_code": "603", "pos_date": "2026-07-01", "pos_amount": 2000.00, "provider": "MADA",
     "reference": "A3", "auth_code": "A3", "source_row": 3, "merchant_id": "M1"},
])
gl = pd.DataFrame([
    {"store_code": "601", "gl_date": "2026-07-01", "gl_signed_amount": 1000.00, "gl_amount": 1000.00,
     "main_account": "11020907", "voucher": "V1", "journal": "J1", "source_row": 1, "source_file": "gl.xlsx"},
    {"store_code": "602", "gl_date": "2026-07-01", "gl_signed_amount": 500.01, "gl_amount": 500.01,
     "main_account": "11020907", "voucher": "V2", "journal": "J2", "source_row": 2, "source_file": "gl.xlsx"},
    {"store_code": "603", "gl_date": "2026-07-01", "gl_signed_amount": 1500.00, "gl_amount": 1500.00,
     "main_account": "11020907", "voucher": "V3", "journal": "J3", "source_row": 3, "source_file": "gl.xlsx"},
])
r = pgl.reconcile_pos_to_gl_by_bucket(pos, gl, tolerance=0.50, max_bucket_tolerance=25.00)
statuses = dict(zip(r["store_summary"]["Store Code"], r["store_summary"]["Status"]))
assert statuses == {"601": "OK", "602": "OK", "603": "REVIEW"}, statuses
print("[PASS] Store-wise Status is tolerance-based: exact match -> OK, SAR 0.01 diff -> OK "
      "(the exact bug that was reported), SAR 500 real gap -> REVIEW.")

gl_row = r["gl_summary"].iloc[0]
assert round(float(gl_row["GL Total"]), 2) == 3000.01
assert round(float(gl_row["POS Total"]), 2) == 3500.00
print("[PASS] GL-wise summary is a full GL Total vs POS Total comparison, correctly netted.")

pos2 = pd.DataFrame([{"store_code": "613", "pos_date": "2026-07-01", "pos_amount": 300.00,
                       "provider": "TAP", "reference": "B1", "auth_code": "B1", "source_row": 1, "merchant_id": "M1"}])
gl2 = pd.DataFrame([
    {"store_code": "613", "gl_date": "2026-07-01", "gl_signed_amount": 200.00, "gl_amount": 200.00,
     "main_account": "11020904", "voucher": "V1", "journal": "J1", "source_row": 1, "source_file": "gl.xlsx"},
    {"store_code": "613", "gl_date": "2026-07-01", "gl_signed_amount": 100.00, "gl_amount": 100.00,
     "main_account": "11020908", "voucher": "V2", "journal": "J2", "source_row": 2, "source_file": "gl.xlsx"},
])
r2 = pgl.reconcile_pos_to_gl_by_bucket(pos2, gl2)
assert round(float(r2["gl_summary"]["Difference"].iloc[0]), 2) == 0.0
print("[PASS] Store 613 TAP dual-account (11020904 + 11020908) composites correctly.")

empty_pos = pd.DataFrame(columns=["store_code", "pos_date", "pos_amount", "provider",
                                   "reference", "auth_code", "source_row", "merchant_id"])
empty_gl = pd.DataFrame(columns=["store_code", "gl_date", "gl_signed_amount", "gl_amount",
                                  "main_account", "voucher", "journal", "source_row", "source_file"])
r3 = pgl.reconcile_pos_to_gl_by_bucket(empty_pos, empty_gl)
assert r3["store_summary"].empty and r3["gl_summary"].empty and r3["detail"].empty
assert r3["summary"]["Overall Status"].iloc[0] == "RECONCILED"
print("[PASS] Completely empty pos+gl input no longer crashes.")

pos4 = pd.DataFrame([{"store_code": "601", "pos_date": "2026-07-01", "pos_amount": 100.0,
                       "provider": "MADA", "reference": "D1", "auth_code": "D1", "source_row": 1, "merchant_id": "M1"}])
r4 = pgl.reconcile_pos_to_gl_by_bucket(pos4, empty_gl)
assert r4["store_summary"].iloc[0]["Status"] == "REVIEW"
assert round(float(r4["store_summary"].iloc[0]["Difference"]), 2) == 100.0
print("[PASS] POS uploaded with GL completely empty: no crash, correct REVIEW.")

gl5 = pd.DataFrame([{"store_code": "601", "gl_date": "2026-07-01", "gl_signed_amount": 100.0, "gl_amount": 100.0,
                      "main_account": "11020907", "voucher": "V1", "journal": "J1", "source_row": 1, "source_file": "gl.xlsx"}])
r5 = pgl.reconcile_pos_to_gl_by_bucket(empty_pos, gl5)
assert r5["store_summary"].iloc[0]["Status"] == "REVIEW"
assert round(float(r5["store_summary"].iloc[0]["Difference"]), 2) == -100.0
print("[PASS] GL uploaded with POS completely empty: no crash, correct REVIEW.")

pos6 = pd.DataFrame([{"store_code": "601", "pos_date": "2026-07-01", "pos_amount": 300.00,
                       "provider": "STCPAY", "reference": "C1", "auth_code": "C1", "source_row": 1, "merchant_id": "M1"}])
gl6 = pd.DataFrame([{"store_code": "601", "gl_date": "2026-07-01", "gl_signed_amount": 300.00, "gl_amount": 300.00,
                      "main_account": "11020950", "voucher": "V1", "journal": "J1", "source_row": 1, "source_file": "gl.xlsx"}])
r6 = pgl.reconcile_pos_to_gl_by_bucket(pos6, gl6)
assert len(r6["gl_summary"]) == 2
assert set(r6["gl_summary"]["GL Account"]) == {"11020950", "UNMAPPED"}
print("[PASS] Unmapped provider / unmapped GL account still correctly split, unchanged.")

print("REGRESSION POS GL SUMMARY AND EMPTY INPUT PASS")

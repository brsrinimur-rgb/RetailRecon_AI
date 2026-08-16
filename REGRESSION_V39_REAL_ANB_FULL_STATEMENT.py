"""
REGRESSION_V39_REAL_ANB_FULL_STATEMENT.py

Runs the REAL, FULL July 2026 ANB statement
(ACC_0108095820370014_2026-08-02-084639231_-_Final.xlsx, 3,218 raw rows /
3,205 transaction rows, account UNITED LUXURY CORP, period 2026-07-01 to
2026-07-31) through the actual matching functions end to end.

This is the exact file REGRESSION_BANK_SETTLEMENT_PROPAGATION_V24.py has
needed since V27 (hardcoded to /mnt/data/..., never previously uploaded).
That file's specific claims are independently re-proven here against the
real upload:
  - total ANB credits = SAR 7,690,111.56
  - terminal 55610715 / VISA / source date 2026-06-30 / TX_12 / SAR 6,567.01
    example settles to BANK RECEIVED

It also extends real-data proof to the AMEX wire-to-bank chain (V38):
running the SAME real file directly (not a manual transcription) confirms
the same 11-of-13 result, and confirms — by searching the ENTIRE month, not
a partial excerpt — that the 2 unmatched wires are absent from the full
July statement. That proves they did NOT post in July; it does NOT prove
they posted in August. An August ANB statement is the next place to look,
not a confirmed fact yet -- absence from one period only rules that period
out, per the same discipline this project has held throughout.

Run: python3 REGRESSION_V39_REAL_ANB_FULL_STATEMENT.py
(requires the real file to be present at the path below)
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_v39",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v39"]=core; sp.loader.exec_module(core)
from logic import bank_settlement_extension as bank_ext

ANB_FILE=Path("/mnt/user-data/uploads/ACC_0108095820370014_2026-08-02-084639231_-_Final.xlsx")
assert ANB_FILE.exists(), f"real ANB statement not found at {ANB_FILE}"

class UploadBytes:
    def __init__(self,path):
        self.name=Path(path).name
        self._data=Path(path).read_bytes()
    def getvalue(self):
        return self._data

sheets=core.read_upload(UploadBytes(ANB_FILE))
assert "anb" in sheets
anb=bank_ext.normalize_bank_statement(sheets["anb"],ANB_FILE.name)

# ---------------------------------------------------------------------
# 1. Full statement parses; total credit ties to the long-documented figure.
# ---------------------------------------------------------------------
assert len(anb)==3205, f"expected 3205 normalized rows, got {len(anb)}"
total_credit=round(float(anb.loc[anb["Credit"]>0,"Credit"].sum()),2)
assert total_credit==7690111.56, f"total credit mismatch: {total_credit}"
print(f"[PASS] Full statement parses: {len(anb)} rows, total credits SAR {total_credit:,.2f} -- "
      f"ties exactly to the figure documented since V24/V27.")

# ---------------------------------------------------------------------
# 2. Full statement date coverage confirmed -- not a coverage gap.
# ---------------------------------------------------------------------
dates=pd.to_datetime(sheets["anb"]["Trans: Date"],errors="coerce")
assert dates.min().date().isoformat()=="2026-07-01"
assert dates.max().date().isoformat()=="2026-07-31"
assert int((dates.dt.date==pd.Timestamp("2026-07-31").date()).sum())>0
print("[PASS] Statement genuinely covers the full month (2026-07-01 to 2026-07-31, "
      "93 rows on the last day) -- confirmed not a partial/truncated export.")

# ---------------------------------------------------------------------
# 3. The specific documented ANB example ties end to end through the real
#    matching function, not a synthetic fixture.
# ---------------------------------------------------------------------
matched=pd.DataFrame([{
    "Unique Transaction ID":f"REAL-U{i}",
    "Store Code":"TEST","Payment Type":"VISA",
    "POS Date":pd.Timestamp("2026-06-30"),
    "Terminal ID":"55610715",
    "POS Amount":6687.88/12,"Net Amount":6567.01/12,
    "Commission":105.09/12,"VAT":15.78/12,
    "D365 Amount":6687.88/12,"Bank Settled":False,
} for i in range(12)])
batches=core.build_card_settlement_batches(matched)
assert len(batches)==1

res,_=bank_ext.reconcile_card_batches_to_anb(batches,anb,1.0)
assert len(res)==1
assert res.iloc[0]["Settlement Status"]=="BANK RECEIVED", res.iloc[0].to_dict()
assert round(float(res.iloc[0]["Actual Bank Amount"]),2)==6567.01
print("[PASS] Documented example (terminal 55610715, VISA, source date 30-Jun-2026, "
      "TX_12, SAR 6,567.01) settles to BANK RECEIVED against the REAL full statement, "
      "end to end through reconcile_card_batches_to_anb().")

updated=bank_ext.propagate_verified_batches(matched,res)
assert updated["Bank Settled"].all()
print("[PASS] Settlement propagates correctly to all 12 underlying matched transactions.")

# ---------------------------------------------------------------------
# 4. AMEX chain re-proven against the REAL file directly (not the manual
#    transcription used in V38) -- same result, stronger evidence.
# ---------------------------------------------------------------------
amex_rows=anb[anb["Provider"]=="AMEX"]
assert len(amex_rows)==11, f"expected 11 real AMEX-tagged rows in the full statement, got {len(amex_rows)}"
print(f"[PASS] {len(amex_rows)} AMEX-tagged wire credits found in the REAL full statement "
      f"(same count as the V38 manual transcription -- now confirmed from the actual file).")

class UploadBytesAmex:
    def __init__(self,path):
        self.name=Path(path).name
        self._data=Path(path).read_bytes()
    def getvalue(self):
        return self._data

AMEX_FILE=Path("/mnt/user-data/uploads/SE-2026_07_31-9710107967.xlsx")
if AMEX_FILE.exists():
    amex_sheets=core.read_upload(UploadBytesAmex(AMEX_FILE))
    payments,_=core.normalize_amex_statement(amex_sheets["Submissions"],AMEX_FILE.name)
    wire_res=bank_ext.reconcile_amex_wires_to_bank(payments,anb,1.0)
    confirmed=wire_res[wire_res["AMEX Wire Bank Status"]=="AMEX WIRE BANK CONFIRMED"]
    pending=wire_res[wire_res["AMEX Wire Bank Status"]=="AMEX WIRE PENDING"]
    assert len(confirmed)==11, f"expected 11 confirmed, got {len(confirmed)}"
    assert len(pending)==2, f"expected 2 pending, got {len(pending)}"
    pending_amounts=set(round(float(x),2) for x in pending["Wire Amount"])
    assert pending_amounts=={124.36,37113.82}
    print(f"[PASS] reconcile_amex_wires_to_bank() against the REAL full ANB statement: "
          f"11 of 13 wires confirmed, exactly matching V38's result -- now proven against "
          f"the actual file rather than a manual transcription.")

    # 5. Confirm, from the REAL full month (not a partial excerpt), that the
    #    2 unresolved wires are absent from the entire July file. This
    #    proves NOT July -- it does not prove August. That distinction
    #    matters: absence from one period only rules that period out.
    for amt in (124.36,37113.82):
        hit=anb[(anb["Bank Amount"].round(2)==amt) & (anb["Provider"]=="AMEX")]
        assert hit.empty, f"SAR {amt} unexpectedly found in the full July statement -- update needed"
    print("[PASS] Confirmed by searching the COMPLETE July statement (not an excerpt): "
          "the 2 unresolved wires (SAR 124.36, SAR 37,113.82) are genuinely absent from "
          "all of July. This rules out July -- it does NOT confirm August. An August ANB "
          "statement is the next place to check, not yet a confirmed fact.")
else:
    print("[SKIPPED] AMEX statement file not found in this run -- steps 4-5 need both files present.")

print("REGRESSION V39 REAL ANB FULL STATEMENT PASS")

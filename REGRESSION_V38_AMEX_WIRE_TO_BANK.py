"""
REGRESSION_V38_AMEX_WIRE_TO_BANK.py

Tests against the REAL ANB bank statement excerpt pasted into this
engagement (2026-07, account showing AMEX Sarie/SIBC wire credits). Every
row below is transcribed character-for-character from that real excerpt --
not synthetic.

Proves:
  1. parse_anb_narration() now tags Provider="AMEX" on this real narration
     shape (it did not before this fix -- confirmed empty/untagged).
  2. reconcile_amex_wires_to_bank() ties AMEX's own declared wire amounts
     (from core.normalize_amex_statement()'s real, already-proven Payments
     frame) to these real bank credits, gross-to-gross, respecting the
     confirmed 0-3(+lag) day window.
  3. All 11 of the 13 real AMEX wires that fall within this excerpt tie
     correctly; the 2 wires NOT present in this excerpt (SAR 124.36 and
     SAR 37,113.82 -- simply outside what was pasted) correctly stay
     PENDING rather than being falsely matched or silently dropped.

Run: python3 REGRESSION_V38_AMEX_WIRE_TO_BANK.py
(requires the real AMEX statement file to also be present, for the
Payments frame this test ties against)
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_v38",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v38"]=core; sp.loader.exec_module(core)
from logic import bank_settlement_extension as bank_ext

AMEX_FILE=Path("/mnt/user-data/uploads/SE-2026_07_31-9710107967.xlsx")
assert AMEX_FILE.exists(), f"real AMEX statement not found at {AMEX_FILE}"

class UploadBytes:
    def __init__(self,path):
        self.name=Path(path).name
        self._data=Path(path).read_bytes()
    def getvalue(self):
        return self._data

sheets=core.read_upload(UploadBytes(AMEX_FILE))
payments,submissions=core.normalize_amex_statement(sheets["Submissions"],AMEX_FILE.name)
assert len(payments)==13

# ---------------------------------------------------------------------
# Real ANB statement excerpt, transcribed exactly from what was pasted.
# Narration/Narration1/Narration2/Narration3 kept verbatim (Arabic text
# included), matching the real ANB column layout
# (Trans: Date, Value Date, Txt ID, Amount Dr., Amount Cr., Balance,
#  Narration, Narration 1, Narration 2, Narration 3).
# ---------------------------------------------------------------------
raw_rows = [
    # (Trans Date, Value Date, Txt ID, Amount Cr., Narration1(sender), Narration2(ref), Narration3(purpose))
    ("2026-07-12","2026-07-12","SD8756367",52263.47,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD8756367 - UTIREF#SIBCPMT261930002 QST+200418507832., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:22:10",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT261930002 QST+200418507832","Amex Saudi Arabia Ltd Service"),
    ("2026-07-13","2026-07-13","SD1447545",19676.88,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD1447545 - UTIREF#SIBCPMT261940003 QST+300418732710., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:14:35",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT261940003 QST+300418732710","Amex Saudi Arabia Ltd Service"),
    ("2026-07-15","2026-07-15","SD6001308",14482.50,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD6001308 - UTIREF#SIBCPMT261960002 QST+500419195642., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:16:24",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT261960002 QST+500419195642","Amex Saudi Arabia Ltd Service"),
    ("2026-07-19","2026-07-19","SD4831704",54978.46,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD4831704 - UTIREF#SIBCPMT262000002 QST+900420081860., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:03:56",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT262000002 QST+900420081860","Amex Saudi Arabia Ltd Service"),
    ("2026-07-19","2026-07-19","SD4831739",1384.52,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD4831739 - UTIREF#SIBCPMT261990003 QST+800419872445., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:03:58",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT261990003 QST+800419872445","Amex Saudi Arabia Ltd Service"),
    ("2026-07-19","2026-07-19","SD4831756",39488.95,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD4831756 - UTIREF#SIBCPMT261980001 QST+700419672267., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:03:58",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT261980001 QST+700419672267","Amex Saudi Arabia Ltd Service"),
    ("2026-07-20","2026-07-20","SD7249349",54550.75,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD7249349 - UTIREF#SIBCPMT262010002 QST+000420330868., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 10:14:07",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT262010002 QST+000420330868","Amex Saudi Arabia Ltd Service"),
    ("2026-07-26","2026-07-26","SD0088666",15061.81,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD0088666 - UTIREF#SIBCPMT26207000C QST+600421760372., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 09:53:40",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT26207000C QST+600421760372","Amex Saudi Arabia Ltd Service"),
    ("2026-07-28","2026-07-28","SD5984236",2949.60,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD5984236 - UTIREF#SIBCPMT262090005 QST+800422283067., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 09:55:43",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT262090005 QST+800422283067","Amex Saudi Arabia Ltd Service"),
    ("2026-07-29","2026-07-29","SD8940827",2561.70,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض :Amex Saudi Arabia Ltd Ser.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD8940827 - UTIREF#SIBCPMT262100004QST+900422565223., نوع المعاملة : 00017, مدينة : 0101121212009 Amex (Saudi Arabia) Ltd. PO Box 6624 Riyadh 11452 Saudi Arabia, وقت بدء المعاملة : 11:23:53",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT262100004QST+900422565223","Amex Saudi Arabia Ltd Ser"),
    ("2026-07-30","2026-07-30","SD1891035",38620.00,
     "تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., AC-0101121212009. الغرض : Amex Saudi Arabia Ltd Service.البنك المرسل : SAUDI INVESTEMENT BANK. العملة : SAR. سعر الصرف : 1. رقم المرجع : SD1891035 - UTIREF#SIBCPMT26211001F QST+000422797922., نوع المعاملة : 00033, مدينة : RIYADH, وقت بدء المعاملة : 09:55:48",
     "Amex (Saudi Arabia) Ltd.","SIBCPMT26211001F QST+000422797922","Amex Saudi Arabia Ltd Service"),
]

bank_rows=[]
for txn_date,value_date,txn_id,cr,narration,n1,n2,n3 in raw_rows:
    evidence=bank_ext.parse_anb_narration([narration,n1,n2,n3])
    bank_rows.append({
        "Bank":"ANB",
        "Bank Date":pd.to_datetime(value_date),
        "Bank Amount":cr,
        "Credit":cr,
        "Debit":0.0,
        "Bank Source File":"anb_july2026_real_excerpt.xlsx",
        "Bank Source Row":len(bank_rows)+1,
        **evidence,
    })
bank=pd.DataFrame(bank_rows)

# ---------------------------------------------------------------------
# 1. Provider tagging fix, confirmed on the real narration text.
# ---------------------------------------------------------------------
assert (bank["Provider"]=="AMEX").all(), bank[["Bank Date","Provider"]].to_string()
print(f"[PASS] parse_anb_narration() now tags Provider=AMEX on all {len(bank)} real "
      f"Sarie/SIBC wire rows -- previously untagged (empty string).")

assert bank.iloc[0]["Narration Wire Reference"]=="UTIREF#SIBCPMT261930002"
print("[PASS] Wire reference (UTIREF#...) extracted correctly from real narration text.")

# ---------------------------------------------------------------------
# 2. Wire-to-bank matching against these real credits.
# ---------------------------------------------------------------------
res=bank_ext.reconcile_amex_wires_to_bank(payments,bank,1.0)
assert len(res)==13

confirmed=res[res["AMEX Wire Bank Status"]=="AMEX WIRE BANK CONFIRMED"]
pending=res[res["AMEX Wire Bank Status"]=="AMEX WIRE PENDING"]

assert len(confirmed)==11, (
    f"expected 11 of 13 real wires confirmed against this excerpt, got {len(confirmed)}\n"
    f"{res[['Date','Wire Amount','AMEX Wire Bank Status']].to_string()}"
)
assert len(pending)==2, f"expected 2 wires (SAR 124.36, SAR 37,113.82) to stay pending, got {len(pending)}"

pending_amounts=set(round(float(x),2) for x in pending["Wire Amount"])
assert pending_amounts=={124.36,37113.82}, pending_amounts
print(f"[PASS] 11 of 13 real AMEX wires tie exactly to real ANB credits in this excerpt; "
      f"the 2 wires outside the excerpt (SAR 124.36, SAR 37,113.82) correctly stay PENDING, "
      f"not falsely matched.")

# Spot-check the lag pattern found by hand: 2026-07-16 payment -> 2026-07-19
# bank credit (3-day lag, Thu->Sun across the Fri/Sat Saudi weekend).
lag_row=confirmed[confirmed["Date"]==pd.Timestamp("2026-07-16")]
assert len(lag_row)==1
assert lag_row.iloc[0]["Bank Date"]==pd.Timestamp("2026-07-19")
print("[PASS] 3-day weekend lag (16-Jul payment -> 19-Jul bank credit) correctly ties within "
      "the existing 0-3 day window -- no lag widening needed for this real data.")

print("REGRESSION V38 AMEX WIRE TO BANK PASS (against real pasted ANB statement excerpt)")

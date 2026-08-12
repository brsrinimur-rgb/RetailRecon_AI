from pathlib import Path
import sys,importlib.util,pandas as pd
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("corev16",root/"core.py")
core=importlib.util.module_from_spec(sp);sys.modules["corev16"]=core;sp.loader.exec_module(core)

rows=[]
for store in ["601","609"]:
    for day,pay,amt in [
        ("2026-08-01","MADA",100.0),
        ("2026-08-02","VISA",200.0),
        ("2026-08-03","MASTERCARD",300.0),
        ("2026-08-04","AMEX",400.0),
        ("2026-08-08","MADA",999.0),
    ]:
        rows.append({
            "Store Code":store,"Date":pd.Timestamp(day),"Status":"Matched","Difference":0.0,
            "Bank Settled":True,"Payment Type":pay,"D365 Amount":amt,"POS Amount":amt,
            "Commission":0.0,"VAT":0.0
        })
r=pd.DataFrame(rows)
j=core.create_jv(r,{},pd.DataFrame(),accounting_date="2026-08-08",
                 from_date="2026-08-01",to_date="2026-08-07")
assert not j.empty
assert set(j["Group"])=={"CC","AMEX"},set(j["Group"])
assert j["Store Code"].nunique()==2
assert j["Journal Batch"].nunique()==4
assert (pd.to_datetime(j["JV From Date"])==pd.Timestamp("2026-08-01")).all()
assert (pd.to_datetime(j["JV To Date"])==pd.Timestamp("2026-08-07")).all()
# CC gross per store = 100 + 200 + 300; Aug-08 amount excluded.
cc=j[(j["Store Code"]=="601")&(j["Group"]=="CC")]
assert set(cc["Gross Amount"].round(2))=={600.0}
assert not j["Description"].astype(str).str.contains("999").any()
assert j["Description"].astype(str).str.contains("01-Aug-2026 to 07-Aug-2026").all()
assert all("-CC-" in x for x in j.loc[j["Group"]=="CC","Journal Batch"].unique())
print("JV DATE RANGE V16 PASS")

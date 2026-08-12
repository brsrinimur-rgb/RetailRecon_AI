import pandas as pd
matched=pd.DataFrame([
 {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Status":"Matched","Difference":0.0,"Bank Settled":True},
 {"Store Code":"601","Date":pd.Timestamp("2026-08-02"),"Status":"Matched","Difference":0.0,"Bank Settled":False},
 {"Store Code":"603","Date":pd.Timestamp("2026-08-03"),"Status":"Matched","Difference":2.0,"Bank Settled":True},
 {"Store Code":"606","Date":pd.Timestamp("2026-08-04"),"Status":"Matched","Difference":0.5,"Bank Settled":True},
 {"Store Code":"609","Date":pd.Timestamp("2026-08-08"),"Status":"Matched","Difference":0.0,"Bank Settled":True},
])
from_date=pd.Timestamp("2026-08-01").date()
to_date=pd.Timestamp("2026-08-07").date()
scope=matched.copy()
scope["_Date"]=pd.to_datetime(scope["Date"]).dt.date
scope=scope[(scope["_Date"]>=from_date)&(scope["_Date"]<=to_date)].copy()
scope["_Matched"]=scope["Status"].astype(str).eq("Matched")
scope["_Difference"]=pd.to_numeric(scope["Difference"],errors="coerce")
scope["_Tolerance_OK"]=scope["_Difference"].abs().le(1.0)
scope["_Bank_Settled"]=scope["Bank Settled"].fillna(False).astype(bool)
scope["_Ready"]=scope["_Matched"]&scope["_Tolerance_OK"]&scope["_Bank_Settled"]
assert len(scope)==4
assert int(scope["_Ready"].sum())==2
assert int(scope.loc[scope["Store Code"]=="601","_Ready"].sum())==1
assert int(scope.loc[scope["Store Code"]=="603","_Ready"].sum())==0
assert int(scope.loc[scope["Store Code"]=="606","_Ready"].sum())==1
assert "609" not in set(scope["Store Code"].astype(str))
print("JV ELIGIBILITY BREAKDOWN V17 PASS")

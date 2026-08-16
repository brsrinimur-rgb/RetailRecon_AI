import pandas as pd
scope=pd.DataFrame([
 {"Store Code":"601","Status":"Matched","Difference":0.0,"Bank Settled":True},
 {"Store Code":"603","Status":"Matched","Difference":0.0,"Bank Settled":False},
])
scope["_Matched"]=scope["Status"].astype(str).eq("Matched")
scope["_Difference"]=pd.to_numeric(scope["Difference"],errors="coerce")
scope["_Tolerance_OK"]=scope["_Difference"].abs().le(1.0)
if "Bank Settled" in scope.columns:
    scope["_Bank_Settled"]=scope["Bank Settled"].fillna(False).astype(bool)
else:
    scope["_Bank_Settled"]=pd.Series(False,index=scope.index,dtype=bool)
if "Settlement Stage" in scope.columns:
    scope["_Settlement_Stage"]=scope["Settlement Stage"].fillna("").astype(str)
else:
    scope["_Settlement_Stage"]=pd.Series("",index=scope.index,dtype="object")
scope["_Ready"]=scope["_Matched"] & scope["_Tolerance_OK"] & scope["_Bank_Settled"]
assert scope["_Settlement_Stage"].tolist()==["",""]
assert scope["_Ready"].tolist()==[True,False]
print("JV MISSING SETTLEMENT STAGE V27 PASS")

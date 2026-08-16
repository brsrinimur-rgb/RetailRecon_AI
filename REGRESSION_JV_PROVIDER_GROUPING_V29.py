import pandas as pd

DEFAULT={
 "MADA":"CC","VISA":"CC","MASTERCARD":"CC",
 "AMEX":"AMEX","TABBY":"TABBY","TAMARA":"TAMARA","TAP":"TAP"
}
def norm(v):
    s=str(v or "").strip().upper().replace(" ","")
    return {"P":"MADA","P1":"MADA","VC":"VISA","MC":"MASTERCARD","AX":"AMEX"}.get(s,s)
def apply(df,mapping):
    out=df.copy()
    out["JV Group"]=out["Payment Type"].apply(norm).map(mapping)
    out["JV Group"]=out["JV Group"].fillna(out["Payment Type"].apply(norm))
    return out

df=pd.DataFrame([
 {"Store Code":"601","Payment Type":"MADA","D365 Amount":100},
 {"Store Code":"601","Payment Type":"VISA","D365 Amount":200},
 {"Store Code":"601","Payment Type":"MASTERCARD","D365 Amount":300},
 {"Store Code":"601","Payment Type":"AMEX","D365 Amount":400},
 {"Store Code":"601","Payment Type":"TABBY","D365 Amount":500},
])
x=apply(df,DEFAULT)
assert set(x[x["Payment Type"].isin(["MADA","VISA","MASTERCARD"])]["JV Group"])=={"CC"}
assert x.loc[x["Payment Type"]=="AMEX","JV Group"].iloc[0]=="AMEX"

custom=DEFAULT.copy()
custom["MADA"]="MADA"
custom["VISA"]="VISA"
custom["MASTERCARD"]="MASTERCARD"
y=apply(df,custom)
assert set(y[y["Payment Type"].isin(["MADA","VISA","MASTERCARD"])]["JV Group"])=={"MADA","VISA","MASTERCARD"}

print("JV PROVIDER GROUPING V29 PASS")

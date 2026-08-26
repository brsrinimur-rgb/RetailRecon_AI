
from __future__ import annotations
import pandas as pd
import numpy as np

def build_settlement_carry_forward(matched, period_end=None, previous=None):
    """
    Build settlement carry-forward without changing the original transaction period.

    Rules:
    - Matched but not bank-settled by period end -> OPEN - CARRY FORWARD.
    - Bank received after period end -> SETTLED IN NEXT PERIOD.
    - Original transaction date/period is never overwritten.
    - Previous carry-forward rows may be supplied and are preserved.
    """
    parts=[]
    if previous is not None and not previous.empty:
        p=previous.copy()
        if "Carry Forward Source" not in p.columns:
            p["Carry Forward Source"]="Prior Period"
        parts.append(p)

    if matched is None or matched.empty:
        return pd.concat(parts,ignore_index=True,sort=False) if parts else pd.DataFrame()

    x=matched.copy()
    x["_TxnDate"]=pd.to_datetime(x.get("Date"),errors="coerce")
    pe=pd.to_datetime(period_end,errors="coerce")
    if pd.isna(pe):
        pe=x["_TxnDate"].max()
    if pd.isna(pe):
        return pd.concat(parts,ignore_index=True,sort=False) if parts else pd.DataFrame()
    pe=pe.normalize()

    if "Bank Settled" in x.columns:
        settled=x["Bank Settled"].fillna(False).astype(bool)
    else:
        settled=pd.Series(False,index=x.index,dtype=bool)

    bank_date=pd.to_datetime(
        x.get("Settlement Bank Date",x.get("Bank Date",pd.Series(pd.NaT,index=x.index))),
        errors="coerce"
    )
    original_period=x["_TxnDate"].dt.to_period("M").astype(str)
    next_period=(pe+pd.offsets.MonthBegin(1)).to_period("M").strftime("%Y-%m")

    # Open at period end.
    open_mask=(x["_TxnDate"].dt.normalize()<=pe) & (~settled | bank_date.isna() | (bank_date.dt.normalize()>pe))
    cf=x[open_mask].copy()
    if cf.empty:
        return pd.concat(parts,ignore_index=True,sort=False) if parts else pd.DataFrame()

    cf["_BankDate"]=bank_date.loc[cf.index]
    cf["Original Transaction Date"]=cf["_TxnDate"]
    cf["Original Period"]=original_period.loc[cf.index]
    cf["Carry Forward Period"]=next_period
    cf["Resolution Period"]=cf["_BankDate"].dt.to_period("M").astype(str).replace("NaT","")
    cf["Carry Forward Source"]="Settlement Control"

    settled_next=cf["_BankDate"].notna() & (cf["_BankDate"].dt.normalize()>pe)
    cf["Carry Forward Status"]=np.where(
        settled_next,
        "SETTLED IN NEXT PERIOD",
        "OPEN - CARRY FORWARD"
    )
    cf["Outstanding Amount"]=pd.to_numeric(
        cf.get("D365 Amount",cf.get("POS Amount",0)),errors="coerce"
    ).fillna(0.0)
    cf.loc[settled_next,"Outstanding Amount"]=0.0

    cf=cf.drop(columns=["_TxnDate","_BankDate"],errors="ignore")
    parts.append(cf)
    return pd.concat(parts,ignore_index=True,sort=False) if parts else pd.DataFrame()

def monthly_carry_forward_summary(carry_forward):
    if carry_forward is None or carry_forward.empty:
        return pd.DataFrame()
    x=carry_forward.copy()
    if "Carry Forward Period" not in x.columns:
        return pd.DataFrame()
    x["_Amount"]=pd.to_numeric(x.get("D365 Amount",x.get("Outstanding Amount",0)),errors="coerce").fillna(0.0)
    x["_Outstanding"]=pd.to_numeric(x.get("Outstanding Amount",0),errors="coerce").fillna(0.0)
    group_cols=[c for c in ["Carry Forward Period","Store Code","Payment Type"] if c in x.columns]
    if not group_cols:
        return pd.DataFrame()
    return (
        x.groupby(group_cols,dropna=False)
        .agg(
            Transactions=("_Amount","size"),
            Original_Amount=("_Amount","sum"),
            Closing_Outstanding=("_Outstanding","sum"),
        )
        .reset_index()
    )

def engine_health():
    return {
        "module":"carry_forward_extension",
        "legacy_preserved":True,
        "rule":"Original period preserved; unsettled month-end items carry forward until bank receipt is verified.",
    }

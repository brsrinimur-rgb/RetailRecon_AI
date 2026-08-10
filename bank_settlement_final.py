
from __future__ import annotations
import re
import pandas as pd
import numpy as np

def clean_amount(v):
    if pd.isna(v) or v == "": return 0.0
    s=str(v).strip().replace(",","")
    neg=s.startswith("(") and s.endswith(")")
    if neg: s=s[1:-1]
    s=re.sub(r"(?i)sar","",s)
    s=re.sub(r"[^0-9.\-]","",s)
    try: n=float(s)
    except: return 0.0
    return -abs(n) if neg else n

def clean_text(v):
    return "" if pd.isna(v) else str(v).strip()

def norm_pay(v):
    s=re.sub(r"[^A-Z0-9]","",clean_text(v).upper())
    mp={"P":"MADA","P1":"MADA","MADA":"MADA","GCCNET":"GCC NET","KNET":"GCC NET",
        "VC":"VISA","VISA":"VISA","VISACARD":"VISA","MC":"MASTER","MASTER":"MASTER",
        "MASTERCARD":"MASTER","AMEX":"AMEX","TABBY":"TABBY","TAMARA":"TAMARA","TAP":"TAP"}
    return mp.get(s,s)

def as_date(v):
    x=pd.to_datetime(v, errors="coerce")
    return x.date() if not pd.isna(x) else pd.NaT

def parse_anb_narration2(v):
    # Merchant_Terminal_DDMMYY. The DDMMYY is ANB's batch/reference date,
    # NOT assumed to be the original POS transaction date.
    m=re.search(r"(\d{6,})_(\d{6,})_(\d{6})$", clean_text(v))
    if not m: return "", "", pd.NaT
    merchant,terminal,dmy=m.groups()
    try: ref_date=pd.to_datetime(dmy,format="%d%m%y").date()
    except: ref_date=pd.NaT
    return merchant,terminal,ref_date

def parse_anb_narration3(v):
    s=clean_text(v).upper()
    parts=s.split("_")
    pay=norm_pay(parts[0]) if parts else ""
    tx=0
    m=re.search(r"_TX_(\d+)",s)
    if m: tx=int(m.group(1))
    nums=[]
    for p in parts[1:]:
        try: nums.append(float(p.replace(",","")))
        except: pass
    return pay,tx,nums

def anb_expected_batches(pos):
    """Group POS for ANB verification: Terminal + POS transaction date + payment type."""
    x=pos.copy()
    x["Payment Type"]=x["Payment Type"].map(norm_pay)
    x["POS Transaction Date"]=x["Transaction Date"].map(as_date)
    x["POS Gross"]=pd.to_numeric(x["POS Gross"] if "POS Gross" in x else x["Amount"],errors="coerce").fillna(0)
    keys=["Terminal ID","POS Transaction Date","Payment Type"]
    return (x.groupby(keys,dropna=False)
             .agg(Store_Code=("Store Code","first"), POS_Transactions=("POS Gross","size"),
                  POS_Gross=("POS Gross","sum"))
             .reset_index()
             .rename(columns={"Store_Code":"Store Code","POS_Transactions":"POS Transactions","POS_Gross":"POS Gross"}))

def verify_anb(pos_batches, bank_batches, tolerance=1.0):
    """ANB: Terminal + payment type + grouped gross + TX count. Bank Value/Posting Date gives receipt date."""
    bank=bank_batches.copy().reset_index(drop=True); used=set(); rows=[]
    for _,p in pos_batches.iterrows():
        cand=bank[(bank["Terminal ID"].astype(str)==str(p["Terminal ID"])) &
                  (bank["Payment Type"].map(norm_pay)==norm_pay(p["Payment Type"])) &
                  (~bank.index.isin(used))].copy()
        if cand.empty:
            rows.append({**p.to_dict(),"Provider":"ANB","Bank Settled":False,"Settlement Status":"Awaiting Bank Settlement"})
            continue
        cand["_diff"]=(pd.to_numeric(cand["Bank Gross"],errors="coerce").fillna(0)-float(p["POS Gross"])).abs()
        idx=cand["_diff"].idxmin(); b=bank.loc[idx]; used.add(idx)
        diff=float(b["Bank Gross"])-float(p["POS Gross"])
        count_ok=True
        if "Bank TX Count" in b and pd.notna(b["Bank TX Count"]) and int(b["Bank TX Count"])>0:
            count_ok=int(b["Bank TX Count"])==int(p["POS Transactions"])
        status="Bank Verified" if abs(diff)<=tolerance and count_ok else ("TX Count Difference" if abs(diff)<=tolerance else "Bank Amount Difference")
        bd=as_date(b.get("Bank Date",b.get("Bank Posting Date",b.get("Value Date"))))
        pdte=as_date(p["POS Transaction Date"])
        delay=(pd.Timestamp(bd)-pd.Timestamp(pdte)).days if not pd.isna(bd) and not pd.isna(pdte) else np.nan
        rows.append({**p.to_dict(),"Provider":"ANB","Bank Date":bd,"Bank Amount":float(b["Bank Gross"]),
                     "Bank Difference":diff,"Bank Settled":status=="Bank Verified","Settlement Status":status,
                     "Settlement Delay Days":delay,"Delay Bucket":f"T+{int(delay)}" if pd.notna(delay) and delay>=0 else "Unknown"})
    return pd.DataFrame(rows)

def build_tap_payouts(tap):
    """TAP: payout_id -> sum(net_amount), preserving charge IDs for row-level write-back."""
    x=tap.copy()
    pid=next((c for c in x.columns if c.lower().replace(" ","_") in ("payout_id","payoutid")),None)
    net=next((c for c in x.columns if c.lower().replace(" ","_") in ("net_amount","netamount")),None)
    pdate=next((c for c in x.columns if c.lower().replace(" ","_") in ("payout_date","payoutdate")),None)
    charge=next((c for c in x.columns if c.lower().replace(" ","_") in ("charge_id","chargeid")),None)
    if not pid or not net:
        raise ValueError("TAP file requires payout_id and net_amount.")

    x["_net"]=x[net].map(clean_amount)
    x["_pdate"]=x[pdate].map(as_date) if pdate else pd.NaT
    if charge:
        x["_ref"]=x[charge].fillna("").astype(str).str.strip()
    else:
        x["_ref"]=""

    out=(x.groupby(pid,dropna=False)
           .agg(**{
               "Payout Date":("_pdate","first"),
               "Transactions":("_net","size"),
               "Expected Bank Credit":("_net","sum"),
               "Provider References":("_ref",lambda s:"|".join(sorted({v for v in s if v})))
           })
           .reset_index()
           .rename(columns={pid:"Payout ID"}))
    return out


def build_tabby_payouts(tabby, transfer_fee=5.0):
    """
    TABBY: one SAR 5 transfer fee per merchant/store payout.
    Preserves Order Number references so verified payouts can update matched rows.
    """
    x=tabby.copy()
    store=next((c for c in x.columns if c.lower().strip() in ("store","store name","merchant","merchant name")),None)
    date=next((c for c in x.columns if "transfer date" in c.lower() or "payout date" in c.lower()),None)
    amt=next((c for c in x.columns if c.lower().strip() in ("transferred amount","transfer amount","payable to merchant","payout amount")),None)
    order=next((c for c in x.columns if c.lower().strip() in ("order number","merchant order number","merchant order id")),None)

    if not amt:
        raise ValueError("TABBY payout file requires Transferred Amount/Payable to Merchant.")

    x["_amt"]=x[amt].map(clean_amount)
    x["_date"]=x[date].map(as_date) if date else pd.NaT
    x["_order"]=x[order].fillna("").astype(str).str.replace(r"\.0$","",regex=True).str.strip() if order else ""

    keys=[]
    if store: keys.append(store)
    if date: keys.append("_date")
    if not keys:
        x["_payout_row"]=range(len(x))
        keys=["_payout_row"]

    out=(x.groupby(keys,dropna=False)
           .agg(**{
               "Transferred Amount":("_amt","sum"),
               "Provider References":("_order",lambda s:"|".join(sorted({v for v in s if v})))
           })
           .reset_index())

    if store:
        out=out.rename(columns={store:"Store Name"})
    if "_date" in out:
        out=out.rename(columns={"_date":"Transfer Date"})

    out["Transfer Fee"]=float(transfer_fee)
    out["Expected Bank Credit"]=out["Transferred Amount"]-out["Transfer Fee"]
    return out


def build_tamara_payouts(tamara):
    """
    TAMARA: expected bank credit = Payable to Merchant exactly.
    Also extracts Tamara/Merchant Order references from the detail section when present.
    """
    x=tamara.copy()

    # Summary amount
    payable=next((c for c in x.columns if c.lower().strip() in ("payable to merchant","payable_to_merchant")),None)
    if not payable:
        raise ValueError("TAMARA file requires Payable to Merchant.")

    payable_vals=pd.to_numeric(x[payable],errors="coerce").fillna(0)
    expected=float(payable_vals[payable_vals!=0].sum())

    # Avoid double counting if both product-level lines and a Total line exist.
    type_col=next((c for c in x.columns if c.lower().strip()=="type"),None)
    if type_col:
        total_mask=x[type_col].astype(str).str.strip().str.upper().eq("TOTAL")
        if total_mask.any():
            total_vals=pd.to_numeric(x.loc[total_mask,payable],errors="coerce").dropna()
            if not total_vals.empty:
                expected=float(total_vals.iloc[-1])

    # Recover detail-table references even when read_upload promoted the summary header.
    refs=set()
    values=x.astype(object)
    detail_header_idx=None
    for idx,row in values.iterrows():
        rowvals={str(v).strip() for v in row.tolist() if pd.notna(v)}
        if "Tamara Order ID" in rowvals or "Merchant Order Number" in rowvals:
            detail_header_idx=idx
            break

    if detail_header_idx is not None:
        hdr=[str(v).strip() if pd.notna(v) else "" for v in values.loc[detail_header_idx].tolist()]
        detail=values.loc[detail_header_idx+1:].copy()
        detail.columns=hdr
        for c in ["Tamara Order ID","Merchant Order ID","Merchant Order Number"]:
            if c in detail.columns:
                for v in detail[c].dropna().astype(str):
                    s=v.strip().replace(".0","")
                    if s and s.upper() not in {"NAN","NONE"}:
                        refs.add(s)

    # Filename/source can supply channel/date later; one uploaded invoice is one payout.
    return pd.DataFrame([{
        "Expected Bank Credit":expected,
        "Provider References":"|".join(sorted(refs))
    }])


def verify_provider_payouts(expected, bank, provider, tolerance=0.01, bank_date_col="Date", credit_col="Credit", details_col="Transaction Details"):
    """TAP/TABBY/TAMARA payout-to-bank verification. Each payout consumes one bank credit."""
    b=bank.copy().reset_index(drop=True)
    b["_credit"]=b[credit_col].map(clean_amount)
    b["_date"]=b[bank_date_col].map(as_date)
    if details_col in b:
        b["_details"]=b[details_col].map(clean_text).str.upper()
        b=b[b["_details"].str.contains(provider.upper(),na=False)].copy()
    used=set(); rows=[]
    for _,p in expected.iterrows():
        amount=float(p["Expected Bank Credit"])
        cand=b[~b.index.isin(used)].copy()
        if cand.empty:
            rows.append({**p.to_dict(),"Provider":provider,"Bank Settled":False,"Settlement Status":"Awaiting Bank Settlement"})
            continue
        cand["_diff"]=(cand["_credit"]-amount).abs()
        idx=cand["_diff"].idxmin(); r=b.loc[idx]; diff=float(r["_credit"])-amount
        if abs(diff)<=tolerance:
            used.add(idx); status="Bank Verified"; settled=True
        else:
            # Do not consume a materially different credit; payout remains open.
            status="Awaiting Bank Settlement"; settled=False
        source_date=p.get("Payout Date",p.get("Transfer Date",pd.NaT))
        bd=r["_date"] if settled else pd.NaT
        delay=(pd.Timestamp(bd)-pd.Timestamp(source_date)).days if settled and not pd.isna(source_date) else np.nan
        rows.append({**p.to_dict(),"Provider":provider,"Bank Date":bd,
                     "Actual Bank Credit":float(r["_credit"]) if settled else np.nan,
                     "Bank Difference":diff if settled else np.nan,"Bank Settled":settled,
                     "Settlement Status":status,"Bank Receipt Delay Days":delay})
    return pd.DataFrame(rows)

def jv_bank_gate(recon):
    """Normal JV eligibility requires existing reconciliation match AND bank verification."""
    x=recon.copy()
    matched=x.get("Status",pd.Series("",index=x.index)).astype(str).str.upper().eq("MATCHED")
    diff=pd.to_numeric(x.get("Total Difference",x.get("Difference",0)),errors="coerce").fillna(0).abs().le(1.0)
    settled=x.get("Bank Settled",pd.Series(False,index=x.index)).fillna(False).astype(bool)
    x["JV Bank Gate Passed"]=matched & diff & settled
    return x


# ======================== RetailRecon integrated adapters =====================
def normalize_anb_bank_batches(df):
    d=df.copy()
    d.columns=[str(c).strip() for c in d.columns]
    lc={str(c).strip().lower():c for c in d.columns}

    def pick(names):
        for n in names:
            if n in lc:
                return lc[n]
        return None

    date_col=pick(["value date","trans: date","trans date","transaction date","date"])
    credit_col=pick(["amount cr.","amount cr","credit","credit amount","amount credit"])
    n2_col=pick(["narration 2","narration2"])
    n3_col=pick(["narration 3","narration3"])

    if not credit_col or not n2_col:
        raise ValueError("ANB statement requires Amount Cr. and Narration 2.")

    rows=[]
    for _,r in d.iterrows():
        credit=clean_amount(r.get(credit_col))
        if credit<=0:
            continue
        merchant,terminal,ref_date=parse_anb_narration2(r.get(n2_col))
        if not terminal:
            continue
        pay,tx_count,_=parse_anb_narration3(r.get(n3_col) if n3_col else "")
        rows.append({
            "Merchant ID":merchant,
            "Terminal ID":terminal,
            "ANB Reference Date":ref_date,
            "Payment Type":pay,
            "Bank TX Count":tx_count,
            "Bank Gross":credit,
            "Bank Date":as_date(r.get(date_col)) if date_col else pd.NaT,
            "Narration 2":clean_text(r.get(n2_col)),
            "Narration 3":clean_text(r.get(n3_col)) if n3_col else "",
        })
    return pd.DataFrame(rows)

def retail_pos_to_anb_batches(pos):
    if pos is None or pos.empty:
        return pd.DataFrame()
    x=pos.copy()
    x["Store Code"]=x.get("POS Store","")
    x["Payment Type"]=x.get("POS Payment","")
    x["Transaction Date"]=x.get("POS Date",pd.NaT)
    x["POS Gross"]=pd.to_numeric(x.get("POS Amount",0),errors="coerce").fillna(0)
    if "Terminal ID" not in x.columns:
        x["Terminal ID"]=""
    return anb_expected_batches(x)

def apply_anb_verification_to_matched(matched, verification):
    if matched is None or matched.empty or verification is None or verification.empty:
        return matched
    out=matched.copy()
    defaults={
        "Bank Settled":False,"Bank Name":"","Bank Date":pd.NaT,
        "Bank Amount":np.nan,"Settlement Status":"Awaiting Bank Settlement"
    }
    for c,v in defaults.items():
        if c not in out.columns:
            out[c]=v

    for _,v in verification.iterrows():
        if not bool(v.get("Bank Settled",False)):
            continue
        mask=(
            out["Terminal ID"].astype(str).eq(str(v.get("Terminal ID",""))) &
            out["Payment Type"].map(norm_pay).eq(norm_pay(v.get("Payment Type",""))) &
            pd.to_datetime(out["POS Date"],errors="coerce").dt.normalize().eq(
                pd.to_datetime(v.get("POS Transaction Date"),errors="coerce")
            )
        )
        out.loc[mask,"Bank Settled"]=True
        out.loc[mask,"Bank Name"]="ANB Bank"
        out.loc[mask,"Bank Date"]=v.get("Bank Date",pd.NaT)
        out.loc[mask,"Bank Amount"]=v.get("Bank Amount",np.nan)
        out.loc[mask,"Settlement Status"]=v.get("Settlement Status","Bank Verified")
        out.loc[mask,"Settlement Delay Days"]=v.get("Settlement Delay Days",np.nan)
    return out


def apply_provider_verification_to_matched(matched, verification, provider):
    """
    Apply verified TAP/TABBY/TAMARA payout results back to matched reconciliation rows.

    Uses explicit provider/order references only. If a payout has no transaction
    references, it remains visible as payout-level verification but is not used
    to mark individual rows Bank Settled (no guessing).
    """
    if matched is None or matched.empty or verification is None or verification.empty:
        return matched

    out=matched.copy()
    for c,default in {
        "Bank Settled":False,
        "Bank Name":"",
        "Bank Date":pd.NaT,
        "Bank Amount":np.nan,
        "Settlement Status":"Awaiting Bank Settlement"
    }.items():
        if c not in out.columns:
            out[c]=default

    paymask=out["Payment Type"].map(norm_pay).eq(norm_pay(provider))
    ref1=out.get("Provider Reference",pd.Series("",index=out.index)).fillna("").astype(str).str.replace(r"\.0$","",regex=True).str.strip()
    ref2=out.get("Provider Order Reference",pd.Series("",index=out.index)).fillna("").astype(str).str.replace(r"\.0$","",regex=True).str.strip()

    for _,v in verification.iterrows():
        if not bool(v.get("Bank Settled",False)):
            continue

        refs={
            r.strip().replace(".0","")
            for r in str(v.get("Provider References","") or "").split("|")
            if r.strip()
        }
        if not refs:
            continue

        mask=paymask & (ref1.isin(refs) | ref2.isin(refs))
        if not mask.any():
            continue

        out.loc[mask,"Bank Settled"]=True
        out.loc[mask,"Bank Name"]="Al Rajhi Bank"
        out.loc[mask,"Bank Date"]=v.get("Bank Date",pd.NaT)
        out.loc[mask,"Bank Amount"]=v.get("Actual Bank Credit",np.nan)
        out.loc[mask,"Settlement Status"]="Bank Verified"

    return out

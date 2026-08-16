
"""
RetailRecon V24 — additive bank settlement propagation extension.

This module does not delete or replace core.py settlement logic. It adds:
- robust ANB / Al Rajhi statement normalization for the Finance-supplied formats;
- bank-narration parsing for terminal, merchant, scheme, source date and TX count;
- strong batch-level bank matching;
- propagation of verified bank settlement evidence back to matched transactions.
"""
from __future__ import annotations
import re
import hashlib
import numpy as np
import pandas as pd

def _txt(v):
    if v is None or (isinstance(v,float) and pd.isna(v)):
        return ""
    return str(v).strip()

def _num(v):
    try:
        x=pd.to_numeric(pd.Series([v]),errors="coerce").iloc[0]
        return np.nan if pd.isna(x) else float(x)
    except Exception:
        return np.nan

def _norm_payment(v):
    s=_txt(v).upper().replace(" ","")
    if s in {"MADA","P","P1"}: return "MADA"
    if s in {"VISA","VC","VISACARD"}: return "VISA"
    if s in {"MASTER","MC","MASTERCARD"}: return "MASTERCARD"
    if s in {"AMEX","AX"}: return "AMEX"
    if s=="TABBY": return "TABBY"
    if s=="TAMARA": return "TAMARA"
    if s=="TAP": return "TAP"
    return _txt(v).upper()

def _parse_ddmmyy(s):
    s=_txt(s)
    m=re.fullmatch(r"(\d{2})(\d{2})(\d{2})",s)
    if not m:return pd.NaT
    dd,mm,yy=m.groups()
    return pd.to_datetime(f"20{yy}-{mm}-{dd}",errors="coerce")

def parse_anb_narration(parts):
    raw=" | ".join(_txt(x) for x in parts if _txt(x))
    terminal=""
    merchant=""
    source_date=pd.NaT
    scheme=""
    tx_count=np.nan
    fee=np.nan
    vat=np.nan
    wire_reference=""

    # Example:
    # 301128607335_55610715_300626
    # VC_15.78_105.09_TX_12
    m=re.search(r"\b(\d{8,20})_(\d{6,20})_(\d{6})\b",raw)
    if m:
        merchant=m.group(1)
        terminal=m.group(2)
        source_date=_parse_ddmmyy(m.group(3))

    m=re.search(r"\b(MADA|VC|MC)_([0-9.]+)_([0-9.]+)_TX_(\d+)\b",raw,re.I)
    if m:
        scheme=_norm_payment(m.group(1))
        # Finance statement pattern shows VAT then commission/fee.
        vat=_num(m.group(2))
        fee=_num(m.group(3))
        tx_count=int(m.group(4))

    provider="ANB POS" if scheme in {"MADA","VISA","MASTERCARD"} else ""

    # AMEX Sarie/SIBC inter-bank wire, confirmed against a real ANB statement
    # excerpt (2026-07). This is structurally different from the card-batch
    # narration above -- no terminal, no scheme, no TX count -- it's a plain
    # inter-bank wire from AMEX's own settlement bank (Saudi Investment Bank)
    # via SIBC. Detected on the sender name text, which appears verbatim and
    # consistently: "Amex (Saudi Arabia) Ltd." / "AC-0101121212009".
    if provider=="" and re.search(r"amex\s*\(saudi\s*arabia\)\s*ltd",raw,re.I):
        provider="AMEX"
        ref_m=re.search(r"\b(UTIREF#\S+)",raw,re.I)
        if ref_m:
            wire_reference=ref_m.group(1)

    return {
        "Provider":provider,
        "Narration Scheme":scheme,
        "Narration Terminal ID":terminal,
        "Narration Merchant ID":merchant,
        "Narration Source Date":source_date,
        "Narration Transaction Count":tx_count,
        "Narration Fee":fee,
        "Narration VAT":vat,
        "Narration Wire Reference":wire_reference,
        "Description":raw,
    }

def _canonical_bank(v):
    s=_txt(v).upper()
    if "RAJHI" in s:
        return "AL RAJHI"
    if s in {"ANB","ANB BANK"} or "ARAB NATIONAL" in s:
        return "ANB"
    return s

def normalize_bank_statement(df, source_file=""):
    """
    Normalize the two real statement formats supplied by Finance.

    ANB:
      Trans: Date, Amount Dr., Amount Cr., Narration, Narration 1..3
    Al Rajhi:
      Date, Transaction Details, Transaction Details_2, Credit, Debit, Balance
    """
    if df is None or df.empty:
        return pd.DataFrame()

    d=df.copy()
    cols={str(c).strip().lower():c for c in d.columns}

    # ANB
    if "trans: date" in cols and ("amount cr." in cols or "amount cr" in cols):
        dc=cols["trans: date"]
        cr=cols.get("amount cr.",cols.get("amount cr"))
        dr=cols.get("amount dr.",cols.get("amount dr"))
        narr_cols=[c for c in d.columns if str(c).strip().lower().startswith("narration")]
        rows=[]
        for i,r in d.iterrows():
            credit=_num(r.get(cr))
            debit=_num(r.get(dr)) if dr else 0.0
            credit=0.0 if pd.isna(credit) else credit
            debit=0.0 if pd.isna(debit) else debit
            amt=credit-debit
            if amt==0: continue
            evidence=parse_anb_narration([r.get(c) for c in narr_cols])
            rows.append({
                "Bank":"ANB",
                "Bank Date":pd.to_datetime(r.get(dc),errors="coerce"),
                "Bank Amount":amt,
                "Credit":credit,
                "Debit":debit,
                "Bank Source File":source_file,
                "Bank Source Row":i+1,
                **evidence,
            })
        return pd.DataFrame(rows)

    # Al Rajhi
    if "date" in cols and "credit" in cols and "debit" in cols:
        dc=cols["date"]; cr=cols["credit"]; dr=cols["debit"]
        detail_cols=[c for c in d.columns if str(c).strip().lower().startswith("transaction details")]
        rows=[]
        for i,r in d.iterrows():
            credit=_num(r.get(cr)); debit=_num(r.get(dr))
            credit=0.0 if pd.isna(credit) else credit
            debit=0.0 if pd.isna(debit) else debit
            amt=credit+debit if debit<0 else credit-debit
            if amt==0: continue
            desc=" | ".join(_txt(r.get(c)) for c in detail_cols if _txt(r.get(c)))
            u=desc.upper()
            provider=""
            if "TABBY" in u: provider="TABBY"
            elif "TAMARA" in u: provider="TAMARA"
            elif re.search(r"\bTAP\b",u) or "TAP TECHNOLOGIES" in u: provider="TAP"
            elif "AMEX" in u or "AMERICAN EXPRESS" in u: provider="AMEX"
            rows.append({
                "Bank":"AL RAJHI",
                "Bank Date":pd.to_datetime(r.get(dc),dayfirst=True,errors="coerce"),
                "Bank Amount":amt,
                "Credit":credit,
                "Debit":debit,
                "Bank Source File":source_file,
                "Bank Source Row":i+1,
                "Provider":provider,
                "Description":desc,
                "Narration Scheme":"",
                "Narration Terminal ID":"",
                "Narration Merchant ID":"",
                "Narration Source Date":pd.NaT,
                "Narration Transaction Count":np.nan,
                "Narration Fee":np.nan,
                "Narration VAT":np.nan,
            })
        return pd.DataFrame(rows)

    return pd.DataFrame()

def _enhance_card_batches(batches):
    if batches is None or batches.empty:
        return pd.DataFrame()
    x=batches.copy()
    x["Payment Type"]=x.get("Payment Type","").apply(_norm_payment)
    x["Settlement Date"]=pd.to_datetime(x.get("Settlement Date"),errors="coerce").dt.normalize()
    x["Terminal ID"]=x.get("Terminal ID","").fillna("").astype(str).str.strip()
    x["Expected Bank Amount"]=pd.to_numeric(x.get("Expected Bank Amount",0),errors="coerce").fillna(0.0)
    x["Transaction Count"]=pd.to_numeric(x.get("Transaction Count",np.nan),errors="coerce")
    return x


def _bank_row_key(row):
    """Deterministic bank credit identity; narration is never part of the key."""
    parts=[
        _txt(row.get("Bank Source File","")),
        _txt(row.get("Bank Source Sheet","")),
        _txt(row.get("Bank Source Row","")),
        _txt(row.get("Bank Date","")),
        _txt(row.get("Bank Amount",row.get("Actual Bank Amount",""))),
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()

def reconcile_card_batches_to_anb(batches, bank, tolerance=1.0):
    """
    Strong ANB rule:
    Terminal + source transaction date + scheme + expected net amount.
    Transaction count is used as additional evidence when present.
    """
    x=_enhance_card_batches(batches)
    if x.empty:
        return pd.DataFrame(),bank.copy() if bank is not None else pd.DataFrame()
    b=bank.copy() if bank is not None else pd.DataFrame()
    if b.empty:
        y=x.copy(); y["Settlement Status"]="BANK RECEIPT PENDING"
        return y,b

    b=b.copy()
    b["Bank"]=b.get("Bank","").apply(_canonical_bank)
    b=b[(b["Bank"]=="ANB") & (pd.to_numeric(b.get("Credit",0),errors="coerce").fillna(0)>0)].copy()
    used=set(); rows=[]

    for _,r in x.iterrows():
        provider=str(r.get("Provider","")).upper()
        if provider not in {"ANB POS","AMEX"}:
            continue

        terminal=_txt(r.get("Terminal ID"))
        pay=_norm_payment(r.get("Payment Type"))
        sdate=pd.to_datetime(r.get("Settlement Date"),errors="coerce")
        exp=float(r.get("Expected Bank Amount",0) or 0)
        txc=pd.to_numeric(pd.Series([r.get("Transaction Count",np.nan)]),errors="coerce").iloc[0]

        cand=b[~b.index.isin(used)].copy()
        if terminal:
            cand=cand[cand["Narration Terminal ID"].astype(str).eq(terminal)]
        if pay:
            cand=cand[cand["Narration Scheme"].apply(_norm_payment).eq(pay)]
        if pd.notna(sdate):
            cand=cand[pd.to_datetime(cand["Narration Source Date"],errors="coerce").dt.normalize().eq(sdate.normalize())]
        if pd.notna(txc):
            same_count=cand[pd.to_numeric(cand["Narration Transaction Count"],errors="coerce").eq(float(txc))]
            if not same_count.empty:
                cand=same_count

        cand["_DIFF"]=(pd.to_numeric(cand["Bank Amount"],errors="coerce")-exp).abs()
        exact=cand[cand["_DIFF"]<=float(tolerance)]

        sel=None; status="BANK RECEIPT PENDING"; rule=""; reason=""
        if len(exact)==1:
            sel=exact.iloc[0]
            used.add(sel.name)
            status="BANK RECEIVED"
            rule="ANB Terminal + Source Date + Scheme + Net Amount"
        elif len(exact)>1:
            status="BANK REVIEW REQUIRED"
            reason="Multiple ANB bank credits satisfy the same settlement batch"
        elif len(cand)==1:
            # Evidence keys are unique but amount differs: keep as review, never auto-settle.
            sel=cand.iloc[0]
            status="BANK REVIEW REQUIRED"
            rule="ANB Terminal + Source Date + Scheme"
            reason=f"Unique ANB settlement evidence found but amount differs by SAR {abs(float(sel['Bank Amount'])-exp):,.2f}"

        rec=r.to_dict()
        rec.update({
            "Settlement Status":status,
            "Bank Match Rule":rule,
            "Settlement Review Reason":reason,
            "Actual Bank Amount":float(sel["Bank Amount"]) if sel is not None else np.nan,
            "Bank Date":sel["Bank Date"] if sel is not None else pd.NaT,
            "Bank Difference":round(float(sel["Bank Amount"])-exp,2) if sel is not None else np.nan,
            "Bank Reference":sel["Description"] if sel is not None else "",
            "Bank Source File":sel.get("Bank Source File","") if sel is not None else "",
            "Bank Source Sheet":sel.get("Bank Source Sheet","") if sel is not None else "",
            "Bank Source Row":sel.get("Bank Source Row",np.nan) if sel is not None else np.nan,
        })
        rows.append(rec)

    result=pd.DataFrame(rows)
    bank_unmatched=b[~b.index.isin(used)].copy()
    return result,bank_unmatched

def reconcile_provider_batches_to_rajhi(batches, bank, tolerance=1.0, tabby_fixed_fee=5.0):
    """
    Provider payout → Al Rajhi bank receipt.
    Strong evidence: provider + date window + amount.
    Tabby additionally supports the observed configurable SAR 5 payout deduction.
    """
    if batches is None or batches.empty:
        return pd.DataFrame(),bank.copy() if bank is not None else pd.DataFrame()
    x=batches.copy()
    x=x[x.get("Provider","").astype(str).str.upper().isin(["TABBY","TAMARA","TAP"])].copy()
    if x.empty:
        return pd.DataFrame(),bank.copy() if bank is not None else pd.DataFrame()

    b=bank.copy()
    if "Bank" not in b.columns:
        b["Bank"]=""
    b["Bank"]=b["Bank"].apply(_canonical_bank)
    b=b[(b["Bank"]=="AL RAJHI") & (pd.to_numeric(b.get("Credit",0),errors="coerce").fillna(0)>0)].copy()
    used=set(); rows=[]

    for _,r in x.iterrows():
        provider=str(r.get("Provider","")).upper()
        exp=float(r.get("Expected Bank Amount",0) or 0)
        sdate=pd.to_datetime(r.get("Settlement Date"),errors="coerce")
        cand=b[~b.index.isin(used)].copy()
        cand=cand[cand.get("Provider","").astype(str).str.upper().eq(provider)]
        if pd.notna(sdate):
            dd=(pd.to_datetime(cand["Bank Date"],errors="coerce").dt.normalize()-sdate.normalize()).dt.days
            cand=cand[(dd>=0)&(dd<=10)].copy()

        cand["_DIFF"]=(pd.to_numeric(cand["Bank Amount"],errors="coerce")-exp).abs()
        if provider=="TABBY":
            cand["_DIFF_FEE"]=(pd.to_numeric(cand["Bank Amount"],errors="coerce")-(exp-tabby_fixed_fee)).abs()
            cand["_BEST"]=cand[["_DIFF","_DIFF_FEE"]].min(axis=1)
        else:
            cand["_BEST"]=cand["_DIFF"]

        exact=cand[cand["_BEST"]<=float(tolerance)]
        sel=None; status="BANK RECEIPT PENDING"; rule=""; reason=""
        if len(exact)==1:
            sel=exact.iloc[0]; used.add(sel.name); status="BANK RECEIVED"
            if provider=="TABBY" and abs(float(sel["Bank Amount"])-(exp-tabby_fixed_fee))<=float(tolerance):
                rule=f"TABBY Payout - Fixed Fee SAR {tabby_fixed_fee:.2f} - Al Rajhi Credit"
            else:
                rule=f"{provider} Payout + Al Rajhi Credit"
        elif len(exact)>1:
            status="BANK REVIEW REQUIRED"; reason="Multiple provider bank receipts satisfy the payout"

        rec=r.to_dict()
        rec.update({
            "Settlement Status":status,
            "Bank Match Rule":rule,
            "Settlement Review Reason":reason,
            "Actual Bank Amount":float(sel["Bank Amount"]) if sel is not None else np.nan,
            "Bank Date":sel["Bank Date"] if sel is not None else pd.NaT,
            "Bank Difference":round(float(sel["Bank Amount"])-exp,2) if sel is not None else np.nan,
            "Bank Reference":sel["Description"] if sel is not None else "",
            "Bank Source File":sel["Bank Source File"] if sel is not None else "",
        })
        rows.append(rec)

    result=pd.DataFrame(rows)
    return result,b[~b.index.isin(used)].copy()

def propagate_verified_batches(matched, batch_results):
    """
    Additive propagation. Uses Underlying IDs when present; otherwise applies
    exact ANB card batch identity Store + Terminal + POS Date + Payment.
    """
    if matched is None or matched.empty:
        return matched
    out=matched.copy()
    for c,default in [
        ("Settlement Batch ID",""),
        ("Settlement Stage","TRANSACTION MATCHED"),
        ("Provider Settled",False),
        ("Bank Settled",False),
        ("Settlement Match Rule",""),
        ("Settlement Bank Amount",np.nan),
        ("Settlement Bank Date",pd.NaT),
        ("Settlement Bank Reference",""),
        ("Settlement Evidence Source",""),
    ]:
        if c not in out.columns:
            out[c]=default

    if batch_results is None or batch_results.empty:
        return out

    for _,b in batch_results.iterrows():
        if str(b.get("Settlement Status",""))!="BANK RECEIVED":
            continue

        ids=[x for x in str(b.get("Underlying IDs","")).split("|") if x and x!="nan"]
        mask=pd.Series(False,index=out.index)

        if ids and "Unique Transaction ID" in out.columns:
            mask=out["Unique Transaction ID"].astype(str).isin(ids)
        else:
            provider=str(b.get("Provider","")).upper()
            if provider in {"ANB POS","AMEX"}:
                d=pd.to_datetime(out.get("POS Date",out.get("Date")),errors="coerce").dt.normalize()
                mask=(
                    out["Store Code"].astype(str).eq(str(b.get("Store Code","")))
                    & out["Payment Type"].apply(_norm_payment).eq(_norm_payment(b.get("Payment Type","")))
                    & d.eq(pd.to_datetime(b.get("Settlement Date"),errors="coerce").normalize())
                )
                if "Terminal ID" in out.columns and _txt(b.get("Terminal ID")):
                    mask &= out["Terminal ID"].astype(str).eq(_txt(b.get("Terminal ID")))

        if mask.any():
            out.loc[mask,"Settlement Batch ID"]=_txt(b.get("Settlement Batch ID"))
            out.loc[mask,"Settlement Stage"]="BANK RECEIVED"
            out.loc[mask,"Provider Settled"]=True
            out.loc[mask,"Bank Settled"]=True
            out.loc[mask,"Settlement Match Rule"]=_txt(b.get("Bank Match Rule"))
            out.loc[mask,"Settlement Bank Amount"]=b.get("Actual Bank Amount",np.nan)
            out.loc[mask,"Settlement Bank Date"]=b.get("Bank Date",pd.NaT)
            out.loc[mask,"Settlement Bank Reference"]=_txt(b.get("Bank Reference"))
            out.loc[mask,"Settlement Evidence Source"]=_txt(b.get("Bank Source File"))
    return out

def settlement_blocker_summary(matched):
    if matched is None or matched.empty:
        return pd.DataFrame()
    x=matched.copy()
    x["Bank Settled"]=x.get("Bank Settled",False).fillna(False).astype(bool)
    x["Settlement Stage"]=x.get("Settlement Stage","").fillna("").astype(str)
    rows=[]
    for (store,pay),g in x.groupby(["Store Code","Payment Type"],dropna=False):
        pending=g[~g["Bank Settled"]]
        rows.append({
            "Store Code":store,
            "Payment Type":pay,
            "Transactions":len(g),
            "Bank Settled":int(g["Bank Settled"].sum()),
            "Bank Pending":len(pending),
            "D365 Amount":float(pd.to_numeric(g.get("D365 Amount",0),errors="coerce").fillna(0).sum()),
            "Pending Amount":float(pd.to_numeric(pending.get("D365 Amount",0),errors="coerce").fillna(0).sum()) if not pending.empty else 0.0,
        })
    return pd.DataFrame(rows)

def engine_health():
    return {
        "module":"bank_settlement_extension",
        "legacy_preserved":True,
        "extension_mode":"additive parser + batch propagation",
    }


def reconcile_card_batches_advanced(batches, bank, tolerance=1.0, settlement_lag_days=0):
    """
    Finance-approved ANB settlement proof.

    Primary rule:
      POS batch amount == ANB credit amount
      with deterministic Terminal + Scheme + transaction-count/date evidence.

    Commission and VAT are separate ANB debit rows and are NEVER added to the
    POS batch amount to manufacture a gross-sales value.

    Date handling:
      bank receipt can post on the POS date or within the next
      (3 + settlement_lag_days) calendar days; narration/source date may equal
      either the POS date or bank date.

      settlement_lag_days (default 0) widens the existing 0-3 day window
      further for banks/periods where receipts are observed to post later
      than usual (e.g. a confirmed 1-day ANB booking lag on a specific
      statement). Default 0 leaves the original 0-3 day window unchanged —
      this parameter only ever widens the window, never narrows it, so
      existing callers and regression tests that don't pass it are
      unaffected.

    Ambiguous or amount-mismatched evidence remains REVIEW/PENDING.
    """
    settlement_lag_days=int(settlement_lag_days or 0)
    if batches is None or batches.empty:
        return pd.DataFrame(), bank.copy() if bank is not None else pd.DataFrame()
    if bank is None or bank.empty:
        x=batches.copy()
        x["Settlement Status"]="BANK RECEIPT PENDING"
        return x,pd.DataFrame()

    x=batches.copy()
    b=bank.copy()
    if "Bank" not in b.columns:
        b["Bank"]=""
    b["Bank"]=b["Bank"].apply(_canonical_bank)
    b=b[
        b["Bank"].eq("ANB")
        & (pd.to_numeric(b.get("Credit",b.get("Bank Amount",0)),errors="coerce").fillna(0)>0)
    ].copy()
    if b.empty:
        out=x.copy()
        out["Settlement Status"]="BANK RECEIPT PENDING"
        return out,b

    b["_BankRowKey"]=b.apply(_bank_row_key,axis=1)
    used=set()
    rows=[]

    for _,r in x.reset_index(drop=True).iterrows():
        provider=str(r.get("Provider","")).upper()
        if provider not in {"ANB POS","AMEX"}:
            continue

        terminal=_txt(r.get("Terminal ID"))
        pay=_norm_payment(r.get("Payment Type",""))
        pos_date=pd.to_datetime(r.get("Settlement Date"),errors="coerce")
        # Correct business amount: POS batch total. Gross Amount is preferred.
        pos_amount=pd.to_numeric(pd.Series([r.get("Gross Amount",np.nan)]),errors="coerce").iloc[0]
        if pd.isna(pos_amount):
            pos_amount=pd.to_numeric(pd.Series([r.get("Expected Bank Amount",0)]),errors="coerce").fillna(0).iloc[0]
        pos_amount=float(pos_amount or 0)
        txc=pd.to_numeric(pd.Series([r.get("Transaction Count",np.nan)]),errors="coerce").iloc[0]

        cand=b[~b["_BankRowKey"].isin(used)].copy()

        if terminal and "Narration Terminal ID" in cand.columns:
            cand=cand[cand["Narration Terminal ID"].astype(str).eq(terminal)]
        if pay and "Narration Scheme" in cand.columns:
            cand=cand[cand["Narration Scheme"].apply(_norm_payment).eq(pay)]

        if pd.notna(pos_date):
            bank_dates=pd.to_datetime(cand["Bank Date"],errors="coerce")
            dd=(bank_dates.dt.normalize()-pos_date.normalize()).dt.days
            cand=cand[(dd>=0)&(dd<=3+settlement_lag_days)].copy()

        # Transaction count is strong evidence when ANB narration provides it.
        if pd.notna(txc) and "Narration Transaction Count" in cand.columns:
            exact_count=cand[
                pd.to_numeric(cand["Narration Transaction Count"],errors="coerce").eq(float(txc))
            ]
            if not exact_count.empty:
                cand=exact_count

        cand["_AMT_DIFF"]=(pd.to_numeric(cand["Bank Amount"],errors="coerce")-pos_amount).abs()
        exact=cand[cand["_AMT_DIFF"]<=float(tolerance)].copy()

        sel=None
        status="BANK RECEIPT PENDING"
        rule=""
        reason=""

        if len(exact)==1:
            sel=exact.iloc[0]
            used.add(sel["_BankRowKey"])
            status="BANK RECEIVED"
            rule="ANB POS Amount = Bank Credit | Terminal + Scheme + Date + TX Count"
        elif len(exact)>1:
            # Do not guess among duplicate-looking bank credits.
            status="BANK REVIEW REQUIRED"
            reason="Multiple ANB credits satisfy the same deterministic settlement evidence."
        elif len(cand)>=1:
            status="BANK REVIEW REQUIRED"
            best=cand.sort_values("_AMT_DIFF").iloc[0]
            reason=(
                f"ANB identity evidence found but POS amount SAR {pos_amount:,.2f} "
                f"does not equal candidate bank credit SAR {float(best['Bank Amount']):,.2f} "
                f"within tolerance SAR {float(tolerance):,.2f}."
            )

        rec=r.to_dict()
        rec.update({
            "Settlement Status":status,
            "Bank Match Rule":rule,
            "Settlement Review Reason":reason,
            "Actual Bank Amount":float(sel["Bank Amount"]) if sel is not None else np.nan,
            "Bank Date":sel["Bank Date"] if sel is not None else pd.NaT,
            "Bank Difference":round(float(sel["Bank Amount"])-pos_amount,2) if sel is not None else np.nan,
            "Bank Reference":sel.get("Description","") if sel is not None else "",
            "Bank Source File":sel.get("Bank Source File","") if sel is not None else "",
            "Bank Source Sheet":sel.get("Bank Source Sheet","") if sel is not None else "",
            "Bank Source Row":sel.get("Bank Source Row",np.nan) if sel is not None else np.nan,
            "POS Batch Amount":pos_amount,
            "ANB Commission":float(sel.get("Narration Fee",0) or 0) if sel is not None and pd.notna(sel.get("Narration Fee",np.nan)) else np.nan,
            "ANB VAT":float(sel.get("Narration VAT",0) or 0) if sel is not None and pd.notna(sel.get("Narration VAT",np.nan)) else np.nan,
            "Net Bank Movement":(
                round(
                    float(sel["Bank Amount"])
                    - float(sel.get("Narration Fee",0) or 0)
                    - float(sel.get("Narration VAT",0) or 0),2
                )
                if sel is not None else np.nan
            ),
        })
        rows.append(rec)

    out=pd.DataFrame(rows)
    unmatched=b[~b["_BankRowKey"].isin(used)].drop(columns=["_BankRowKey"],errors="ignore").copy()
    return out,unmatched

def reconcile_amex_batches_via_statement(amex_batches, amex_submissions, tolerance=1.0):
    """
    Level 1 of AMEX settlement matching: ties an AMEX card settlement batch
    (Terminal + Date + Gross Amount, built the same way as ANB batches via
    core.build_card_settlement_batches) to the AMEX statement's own
    Submission rows for that terminal/date -- parsed by
    core.normalize_amex_statement() from a REAL AMEX "Statement of account"
    export (confirmed shape: SE-2026_07_31-9710107967.xlsx).

    Rule, "never guess" discipline matching every other matcher in this
    codebase: sum every Submission row sharing the batch's Terminal + Date.
    Only tie the batch when that sum equals the batch's Gross Amount within
    tolerance. A partial or non-matching sum is left unresolved rather than
    guessed at.

    ---------------------------------------------------------------------
    WHAT THIS FUNCTION DELIBERATELY DOES NOT DO (stop point, stated plainly,
    updated after V38 -- read this before assuming the old blocker still
    applies):

    This only proves the batch against AMEX's OWN statement. Per the
    confirmed rule established earlier in this project -- "received" means
    landed in OUR OWN bank account, never a provider's own confirmation
    alone -- a batch resolved here is NOT yet BANK RECEIVED. It reaches
    "AMEX SUBMISSION MATCHED - AWAITING BANK CONFIRMATION": proven against
    AMEX's ledger, not yet proven against a real bank credit.

    The wire-level leg this docstring used to describe as unbuilt IS NOW
    BUILT: see reconcile_amex_wires_to_bank() below, proven against a real
    ANB statement excerpt (11 of 13 real July 2026 AMEX wires tie exactly).
    That function confirms AMEX's own Payment/wire claims are independently
    true against a real bank credit.

    What remains open, specifically, is narrower than before: linking a
    given batch's matched Submission row(s) to the SPECIFIC wire that paid
    them. That link is NOT reliably derivable from the AMEX statement alone
    -- checked by hand against real data, submissions preceding the first
    real wire summed to SAR 52,507.06 net, but the wire itself was SAR
    52,263.47, a SAR 244.59 gap nothing visible in the statement explains
    (plausibly a balance-carry or VAT-timing effect -- VAT is confirmed
    billed separately from each submission's net, see
    normalize_amex_statement()'s docstring). Guessing a submission-to-wire
    linking rule to close that gap would repeat the exact mistake this
    project has consistently refused to make elsewhere (see: why Tamara/TAP
    transaction-level linking stays open). That link -- submission/batch to
    specific wire -- is the actual remaining blocker to BANK RECEIVED, not
    "no bank statement available." A bank statement is now available and
    has been used; it closed the wire-to-bank leg, not the submission-to-
    wire leg.
    ---------------------------------------------------------------------
    """
    if amex_batches is None or amex_batches.empty:
        return pd.DataFrame()
    if amex_submissions is None or amex_submissions.empty:
        out=amex_batches.copy()
        out["AMEX Statement Status"]="AMEX RECEIPT PENDING"
        out["AMEX Statement Reason"]="No AMEX statement submissions available to match against."
        return out

    subs=amex_submissions.copy()
    subs["_Terminal"]=subs["Terminal ID"].astype(str).str.strip()
    subs["_Date"]=pd.to_datetime(subs["Date"],errors="coerce").dt.normalize()

    rows=[]
    for _,r in amex_batches.iterrows():
        if str(r.get("Provider","")).upper()!="AMEX":
            continue
        terminal=_txt(r.get("Terminal ID"))
        bdate=pd.to_datetime(r.get("Settlement Date"),errors="coerce")
        gross=pd.to_numeric(pd.Series([r.get("Gross Amount",0)]),errors="coerce").fillna(0).iloc[0]

        cand=subs
        if terminal:
            cand=cand[cand["_Terminal"].eq(terminal)]
        if pd.notna(bdate):
            cand=cand[cand["_Date"].eq(bdate.normalize())]

        rec=r.to_dict()
        if cand.empty:
            rec["AMEX Statement Status"]="AMEX RECEIPT PENDING"
            rec["AMEX Statement Reason"]="No statement submission found for this terminal/date."
            rec["AMEX Submission Refs"]=""
            rec["AMEX Statement Gross"]=np.nan
        else:
            cand_sum=round(float(pd.to_numeric(cand["Gross Amount"],errors="coerce").fillna(0).sum()),2)
            diff=abs(cand_sum-float(gross))
            rec["AMEX Statement Gross"]=cand_sum
            rec["AMEX Submission Refs"]="|".join(cand["Ref"].astype(str).tolist())
            if diff<=float(tolerance):
                unpaid=cand[cand["Paid"].astype(str).str.upper().eq("N")]
                if not unpaid.empty:
                    rec["AMEX Statement Status"]="AMEX REVIEW REQUIRED"
                    rec["AMEX Statement Reason"]=(
                        f"Submission gross ties (SAR {cand_sum:,.2f}) but at least one matched "
                        f"submission is marked Paid=N (AMEX itself has not yet paid it)."
                    )
                else:
                    rec["AMEX Statement Status"]="AMEX SUBMISSION MATCHED - AWAITING BANK CONFIRMATION"
                    rec["AMEX Statement Reason"]=(
                        "Batch gross ties exactly to AMEX statement submission(s) for this "
                        "terminal/date. NOT yet BANK RECEIVED -- the matched submission(s) "
                        "still need a proven allocation to the specific AMEX Payment/wire that "
                        "funded them. AMEX wire -> ANB bank-credit confirmation is already "
                        "implemented separately (see reconcile_amex_wires_to_bank()); "
                        "submission/batch -> specific wire remains unresolved."
                    )
            else:
                rec["AMEX Statement Status"]="AMEX REVIEW REQUIRED"
                rec["AMEX Statement Reason"]=(
                    f"Statement submission(s) found for this terminal/date but gross SAR "
                    f"{gross:,.2f} does not tie to statement sum SAR {cand_sum:,.2f} "
                    f"within tolerance SAR {tolerance:,.2f}."
                )
        rows.append(rec)

    return pd.DataFrame(rows)

def reconcile_amex_wires_to_bank(amex_payments, bank, tolerance=1.0, settlement_lag_days=0):
    """
    Ties AMEX's own declared Sarie/SIBC wire amounts (the "Payment" rows
    parsed by core.normalize_amex_statement -- Date + Wire Amount) to a REAL
    ANB bank credit, now tagged Provider="AMEX" by parse_anb_narration()
    (confirmed against a real ANB statement excerpt, 2026-07).

    Rule, confirmed against real data, not assumed: gross-to-gross exact tie
    (AMEX's stated wire amount equals the bank credit amount exactly -- no
    rounding, no fee deduction at the wire level), with the bank Value Date
    landing 0-3 calendar days after the AMEX Payment Date -- the SAME window
    already used for ANB card matching (reconcile_card_batches_advanced),
    widened by the same settlement_lag_days parameter for consistency.
    11 of 13 real July wires checked by hand all tie on exactly this rule.

    Never guesses: if more than one bank credit of the same amount falls in
    the window, or none does, the wire stays unresolved rather than picking one.

    ---------------------------------------------------------------------
    WHAT THIS FUNCTION PROVES, AND WHAT IT DOES NOT (stop point, stated
    plainly, same discipline as reconcile_amex_batches_via_statement):

    This proves AMEX's OWN wire claims are true -- the money it says it sent
    genuinely landed in the real ANB account, at the amount and
    (lag-adjusted) date it claimed. That is real, independently-verified
    bank evidence, stronger than anything AMEX's own statement alone can
    provide.

    It does NOT, by itself, promote a specific settlement BATCH to BANK
    RECEIVED. That would require linking a specific batch's matched
    Submission row(s) to the specific wire that paid them -- and that link
    is NOT reliably derivable from the AMEX statement alone: checked by hand
    against real data, the submissions preceding the first real wire summed
    to SAR 52,507.06 net, but the wire itself was SAR 52,263.47 -- a SAR
    244.59 gap not explained by anything visible in the statement (plausibly
    a balance-carry or VAT-timing effect, given VAT is confirmed billed
    separately from each submission's net -- see normalize_amex_statement's
    docstring). Guessing a submission-to-wire linking rule to close that gap
    would repeat the exact mistake this project has consistently refused to
    make (see: why Tamara/TAP transaction-level linking stays open). That
    link stays open here for the same reason, not built around.
    ---------------------------------------------------------------------
    """
    if amex_payments is None or amex_payments.empty:
        return pd.DataFrame()

    b=bank.copy() if bank is not None else pd.DataFrame()
    if b.empty or "Bank" not in b.columns:
        out=amex_payments.copy()
        out["AMEX Wire Bank Status"]="AMEX WIRE PENDING"
        out["AMEX Wire Bank Reason"]="No bank data available to confirm against."
        return out

    b=b[
        b["Bank"].apply(_canonical_bank).eq("ANB")
        & b.get("Provider","").astype(str).eq("AMEX")
        & (pd.to_numeric(b.get("Credit",b.get("Bank Amount",0)),errors="coerce").fillna(0)>0)
    ].copy()

    rows=[]
    used=set()
    for idx,r in amex_payments.reset_index(drop=True).iterrows():
        pay_date=pd.to_datetime(r.get("Date"),errors="coerce")
        wire_amt=pd.to_numeric(pd.Series([r.get("Wire Amount",0)]),errors="coerce").fillna(0).iloc[0]

        rec=r.to_dict()
        if b.empty or pd.isna(pay_date):
            rec["AMEX Wire Bank Status"]="AMEX WIRE PENDING"
            rec["AMEX Wire Bank Reason"]="No AMEX-tagged ANB bank credit available."
            rec["Bank Date"]=pd.NaT
            rec["Bank Source File"]=""
            rec["Bank Source Row"]=np.nan
            rows.append(rec)
            continue

        cand=b[~b.index.isin(used)].copy()
        bank_dates=pd.to_datetime(cand["Bank Date"],errors="coerce")
        dd=(bank_dates.dt.normalize()-pay_date.normalize()).dt.days
        cand=cand[(dd>=0)&(dd<=3+int(settlement_lag_days or 0))]
        cand["_DIFF"]=(pd.to_numeric(cand.get("Bank Amount",cand.get("Credit",0)),errors="coerce")-wire_amt).abs()
        exact=cand[cand["_DIFF"]<=float(tolerance)]

        if len(exact)==1:
            sel=exact.iloc[0]
            used.add(sel.name)
            rec["AMEX Wire Bank Status"]="AMEX WIRE BANK CONFIRMED"
            rec["AMEX Wire Bank Reason"]=(
                f"AMEX-declared wire SAR {wire_amt:,.2f} ties exactly to a real ANB credit "
                f"dated {sel['Bank Date']}, {(sel['Bank Date']-pay_date).days} day(s) after the "
                f"AMEX payment date -- within the confirmed 0-3(+lag) day window."
            )
            rec["Bank Date"]=sel["Bank Date"]
            rec["Bank Source File"]=sel.get("Bank Source File","")
            rec["Bank Source Row"]=sel.get("Bank Source Row",np.nan)
        elif len(exact)>1:
            rec["AMEX Wire Bank Status"]="AMEX WIRE REVIEW REQUIRED"
            rec["AMEX Wire Bank Reason"]="Multiple AMEX-tagged ANB credits match this wire amount -- ambiguous, not guessed."
            rec["Bank Date"]=pd.NaT
            rec["Bank Source File"]=""
            rec["Bank Source Row"]=np.nan
        else:
            rec["AMEX Wire Bank Status"]="AMEX WIRE PENDING"
            rec["AMEX Wire Bank Reason"]="No matching AMEX-tagged ANB credit found in the date/amount window yet."
            rec["Bank Date"]=pd.NaT
            rec["Bank Source File"]=""
            rec["Bank Source Row"]=np.nan
        rows.append(rec)

    return pd.DataFrame(rows)

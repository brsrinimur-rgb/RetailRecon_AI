from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

PAYMENT_ALIASES = {
    "MADA": ["mada"],
    "VISA": ["visa", "visacard", "vc"],
    "MASTERCARD": ["mastercard", "master card", "master", "mc"],
    "AMEX": ["amex", "american express"],
    "TABBY": ["tabby"],
    "TAMARA": ["tamara"],
    "TAP": ["tap"],
    "CASH": ["cash"],
    "FLOOSS": ["flooss"],
    "PAYLATER": ["paylater", "pay later"],
    "DEEMA": ["deema"],
}

MONTHS = {
    "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,
    "apr":4,"april":4,"may":5,"jun":6,"june":6,"jul":7,"july":7,
    "aug":8,"august":8,"sep":9,"sept":9,"september":9,
    "oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12,
}

class CopilotContext:
    def __init__(
        self,
        store_codes=None,
        payment=None,
        date_from=None,
        date_to=None,
        date_mode="",
        last_intent="",
        last_scope_label="",
    ):
        self.store_codes=list(store_codes or [])
        self.payment=payment
        self.date_from=date_from
        self.date_to=date_to
        self.date_mode=date_mode
        self.last_intent=last_intent
        self.last_scope_label=last_scope_label

def _norm_store(v):
    s=str(v or "").strip()
    if s.endswith(".0"): s=s[:-2]
    return s

def _safe_date(v):
    d=pd.to_datetime(v,errors="coerce")
    return d.normalize() if pd.notna(d) else pd.NaT

def _fmt_sar(v):
    try:return f"SAR {float(v):,.2f}"
    except:return "SAR 0.00"

def _fmt_date(v):
    d=pd.to_datetime(v,errors="coerce")
    return d.strftime("%d-%b-%Y") if pd.notna(d) else ""

def _find_store_codes(q):
    # Finance/store codes in this application are generally 3 digits.
    hits=re.findall(r"(?<!\d)(\d{3})(?!\d)",q)
    stop={"000","100","200","365"}
    return [x for x in hits if x not in stop]

def _find_payment(q):
    ql=q.lower()
    for payment, aliases in PAYMENT_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", ql) for a in aliases):
            return payment
    return None

def _parse_named_date(text, default_year=None):
    text=text.strip().lower().replace(","," ")
    # 9 aug 2026 / 9 august
    m=re.search(r"\b(\d{1,2})\s+([a-z]{3,9})(?:\s+(\d{4}))?\b",text)
    if m and m.group(2) in MONTHS:
        day=int(m.group(1)); month=MONTHS[m.group(2)]
        year=int(m.group(3)) if m.group(3) else int(default_year or pd.Timestamp.today().year)
        return pd.Timestamp(year=year,month=month,day=day)
    # 2026-08-09
    m=re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",text)
    if m:
        return pd.Timestamp(int(m.group(1)),int(m.group(2)),int(m.group(3)))
    return None

def _parse_date_scope(q, data_min=None, data_max=None, prior=None):
    ql=q.lower()
    today=pd.Timestamp.today().normalize()
    default_year=(data_max.year if pd.notna(data_max) else today.year)

    if "yesterday" in ql:
        d=today-pd.Timedelta(days=1)
        return d,d,"on"
    if re.search(r"\btoday\b",ql):
        return today,today,"on"

    # from X to Y
    m=re.search(r"\bfrom\s+(.+?)\s+(?:to|until|through)\s+(.+?)(?:$|[?.])",ql)
    if m:
        d1=_parse_named_date(m.group(1),default_year)
        d2=_parse_named_date(m.group(2),default_year)
        if d1 is not None and d2 is not None:
            return min(d1,d2),max(d1,d2),"range"

    # as of / up to / through
    m=re.search(r"\b(?:as of|up to|through|until)\s+(.+?)(?:$|[?.])",ql)
    if m:
        d=_parse_named_date(m.group(1),default_year)
        if d is not None:
            start=data_min if pd.notna(data_min) else None
            return start,d,"as_of"

    # on date
    m=re.search(r"\bon\s+(.+?)(?:$|[?.])",ql)
    if m:
        d=_parse_named_date(m.group(1),default_year)
        if d is not None:
            return d,d,"on"

    # plain named date after sales/details etc. Treat as on-date unless phrase says as of.
    d=_parse_named_date(ql,default_year)
    if d is not None:
        return d,d,"on"

    # month scope
    for name,month in MONTHS.items():
        if re.search(rf"\b{name}\b",ql):
            year_match=re.search(r"\b(20\d{2})\b",ql)
            year=int(year_match.group(1)) if year_match else default_year
            start=pd.Timestamp(year=year,month=month,day=1)
            end=start+pd.offsets.MonthEnd(1)
            return start,end,"month"

    if prior and prior.date_from is not None:
        return prior.date_from,prior.date_to,prior.date_mode
    return None,None,""

def interpret_query(question, result, prior: CopilotContext|None=None):
    prior=prior or CopilotContext()
    q=question.strip()
    ql=q.lower()

    tender=result.get("tender",pd.DataFrame()) if result else pd.DataFrame()
    all_dates=pd.to_datetime(tender.get("Date",pd.Series(dtype="datetime64[ns]")),errors="coerce").dropna()
    data_min=all_dates.min().normalize() if not all_dates.empty else pd.NaT
    data_max=all_dates.max().normalize() if not all_dates.empty else pd.NaT

    stores=_find_store_codes(q)
    if not stores:
        stores=prior.store_codes.copy()

    payment=_find_payment(q) or prior.payment
    d1,d2,dmode=_parse_date_scope(q,data_min,data_max,prior)

    # intent
    greeting_match = (
        re.search(r"\b(?:hello|hi|hey)\b", ql) is not None
        or any(x in ql for x in ["good morning","good afternoon","good evening"])
    )
    if greeting_match and len(ql.split())<=4:
        intent="greeting"
    elif any(x in ql for x in ["pending correction","correction approval","corrections pending"]):
        intent="corrections"
    elif any(x in ql for x in ["jv status","journal status","ready for d365","ready to post","posting status"]):
        intent="jv"
    elif any(x in ql for x in ["close status","month end","period close","ready to close"]):
        intent="close"
    elif any(x in ql for x in ["merchant mapping","terminal mapping","store mapping","mapping required"]):
        intent="mapping"
    elif any(x in ql for x in ["commission","fee","fees","vat","net amount"]):
        intent="commission"
    elif any(x in ql for x in ["not settled","unsettled","bank missing","money not received","not received","settlement delay","delayed"]):
        intent="unsettled"
    elif any(x in ql for x in ["missing pos","missing settlement"]):
        intent="missing_pos"
    elif any(x in ql for x in ["missing d365","provider only"]):
        intent="missing_d365"
    elif any(x in ql for x in ["exception","anything wrong","issues","problem","unmatched"]):
        intent="exceptions"
    elif any(x in ql for x in ["refund","refunds"]):
        intent="refunds"
    elif any(x in ql for x in ["compare","comparison","versus"," vs "]):
        intent="compare"
    elif re.search(r"\b(receipt|auth|authorization)\b",ql) and re.search(r"\d{5,}",ql):
        intent="lookup"
    elif any(x in ql for x in ["show transactions","transaction details","show details","details"]):
        # "sales details" should still be sales summary unless follow-up context is present
        intent="transactions" if prior.last_intent else "sales"
    elif any(x in ql for x in ["sales","sale","revenue","tender","payment mix"]):
        intent="sales"
    elif any(x in ql for x in ["summary","briefing","overview","dashboard"]):
        intent="summary"
    else:
        intent=prior.last_intent or "summary"

    ctx=CopilotContext(
        store_codes=stores,
        payment=payment,
        date_from=d1,
        date_to=d2,
        date_mode=dmode,
        last_intent=intent,
    )
    return intent,ctx

def _filter_tender(df,ctx):
    if df is None or df.empty:return pd.DataFrame()
    x=df.copy()
    if ctx.store_codes and "Store Code" in x.columns:
        x=x[x["Store Code"].map(_norm_store).isin(ctx.store_codes)]
    if ctx.payment and "D365 Payment" in x.columns:
        x=x[x["D365 Payment"].astype(str).str.upper().eq(ctx.payment)]
    if "Date" in x.columns:
        dates=pd.to_datetime(x["Date"],errors="coerce")
        if ctx.date_from is not None:
            x=x[dates>=ctx.date_from]
            dates=pd.to_datetime(x["Date"],errors="coerce")
        if ctx.date_to is not None:
            x=x[dates<=ctx.date_to]
    return x

def _filter_recon(df,ctx,date_col="Date",payment_col=None,store_col="Store Code"):
    if df is None or df.empty:return pd.DataFrame()
    x=df.copy()
    if ctx.store_codes and store_col in x.columns:
        x=x[x[store_col].map(_norm_store).isin(ctx.store_codes)]
    if ctx.payment:
        candidates=[payment_col] if payment_col else []
        candidates += ["Payment Type","D365 Payment","D365 Tender","POS Payment","POS Tender"]
        col=next((c for c in candidates if c and c in x.columns),None)
        if col:
            x=x[x[col].astype(str).str.upper().eq(ctx.payment)]
    if date_col in x.columns:
        dates=pd.to_datetime(x[date_col],errors="coerce")
        if ctx.date_from is not None:
            x=x[dates>=ctx.date_from]
            dates=pd.to_datetime(x[date_col],errors="coerce")
        if ctx.date_to is not None:
            x=x[dates<=ctx.date_to]
    return x

def _scope_text(ctx):
    parts=[]
    if ctx.store_codes:
        parts.append("Store " + ", ".join(ctx.store_codes))
    if ctx.payment:
        parts.append(ctx.payment)
    if ctx.date_from is not None and ctx.date_to is not None:
        if ctx.date_from==ctx.date_to:
            parts.append(_fmt_date(ctx.date_from))
        elif ctx.date_mode=="as_of":
            parts.append(f"up to {_fmt_date(ctx.date_to)}")
        else:
            parts.append(f"{_fmt_date(ctx.date_from)} to {_fmt_date(ctx.date_to)}")
    elif ctx.date_to is not None:
        parts.append(f"up to {_fmt_date(ctx.date_to)}")
    return " | ".join(parts) if parts else "current loaded reconciliation"

def _sales_answer(result,ctx,detail=False):
    tender=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    if tender.empty:
        return {
            "text":f"I couldn't find D365 Store Tender sales for {_scope_text(ctx)} in the active reconciliation.",
            "table":pd.DataFrame()
        }

    tender["D365 Amount"]=pd.to_numeric(tender.get("D365 Amount",0),errors="coerce").fillna(0.0)
    grp=tender.groupby(tender["D365 Payment"].astype(str).str.upper(),dropna=False)["D365 Amount"].sum().sort_values(ascending=False)

    gross=float(tender["D365 Amount"].sum())
    positive=float(tender.loc[tender["D365 Amount"]>0,"D365 Amount"].sum())
    refunds=float(tender.loc[tender["D365 Amount"]<0,"D365 Amount"].sum())

    scope=_scope_text(ctx)
    lines=[f"Here are the D365 Store Tender sales for **{scope}**.",
           f"Net tender total is **{_fmt_sar(gross)}**. Positive sales total **{_fmt_sar(positive)}** and refunds/negative tenders total **{_fmt_sar(refunds)}**."]
    if not ctx.payment:
        mix=", ".join(f"{p}: {_fmt_sar(v)}" for p,v in grp.items() if abs(float(v))>0)
        if mix: lines.append("Payment breakdown: "+mix+".")
    else:
        lines.append(f"{ctx.payment} total is **{_fmt_sar(gross)}** across **{len(tender):,}** transaction line(s).")

    if detail:
        cols=[c for c in ["Store Code","Date","Receipt ID","Auth Code","D365 Payment","D365 Amount","Cash Classification","Cash Amount"] if c in tender.columns]
        return {"text":" ".join(lines), "table":tender[cols].sort_values(["Date","Receipt ID"] if "Date" in cols else cols[:1])}
    return {"text":" ".join(lines), "table":pd.DataFrame({"Payment Type":grp.index,"Amount":grp.values})}

def _exceptions_answer(result,ctx):
    us=_filter_recon(result.get("unmatched_sales",pd.DataFrame()),ctx)
    up=_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")
    amount_us=pd.to_numeric(us.get("D365 Amount",us.get("D365 Total",0)),errors="coerce").fillna(0).abs().sum() if not us.empty else 0
    amount_up=pd.to_numeric(up.get("POS Amount",up.get("POS Total",0)),errors="coerce").fillna(0).abs().sum() if not up.empty else 0
    text=(f"For **{_scope_text(ctx)}**, I found **{len(us):,} D365-side exception(s)** "
          f"worth about **{_fmt_sar(amount_us)}** and **{len(up):,} provider-side exception(s)** "
          f"worth about **{_fmt_sar(amount_up)}**.")
    table=pd.concat([
        us.assign(Exception_Side="D365") if not us.empty else pd.DataFrame(),
        up.assign(Exception_Side="Provider/POS") if not up.empty else pd.DataFrame()
    ],ignore_index=True,sort=False)
    return {"text":text,"table":table.head(500)}

def _unsettled_answer(result,ctx):
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    if m.empty:
        return {"text":f"No matched transactions are available for {_scope_text(ctx)}.","table":pd.DataFrame()}
    if "Bank Settled" not in m.columns:
        return {"text":"Bank settlement status is not available in the current reconciliation data.","table":pd.DataFrame()}
    unsettled=m[~m["Bank Settled"].fillna(False).astype(bool)].copy()
    amt=pd.to_numeric(unsettled.get("Sales Amount",unsettled.get("D365 Amount",0)),errors="coerce").fillna(0).sum() if not unsettled.empty else 0
    text=f"For **{_scope_text(ctx)}**, **{len(unsettled):,} matched transaction(s)** totaling **{_fmt_sar(amt)}** are not yet bank settled."
    return {"text":text,"table":unsettled.head(500)}

def _commission_answer(result,ctx):
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    if m.empty:
        return {"text":f"No matched settlement data is available for {_scope_text(ctx)}.","table":pd.DataFrame()}
    commission=pd.to_numeric(m.get("Commission",0),errors="coerce").fillna(0).sum()
    vat=pd.to_numeric(m.get("VAT",0),errors="coerce").fillna(0).sum()
    net=pd.to_numeric(m.get("Net Amount",0),errors="coerce").fillna(0).sum()
    text=(f"For **{_scope_text(ctx)}**, recorded commission is **{_fmt_sar(commission)}**, "
          f"VAT is **{_fmt_sar(vat)}**, and provider/bank net amount is **{_fmt_sar(net)}**.")
    cols=[c for c in ["Store Code","Date","Receipt ID","Auth Code","Payment Type","Sales Amount","Commission","VAT","Net Amount","Bank Settled"] if c in m.columns]
    return {"text":text,"table":m[cols].head(500)}

def _refunds_answer(result,ctx):
    tender=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    if tender.empty:
        return {"text":f"No D365 tender data found for {_scope_text(ctx)}.","table":pd.DataFrame()}
    amt=pd.to_numeric(tender.get("D365 Amount",0),errors="coerce").fillna(0)
    refunds=tender[amt<0].copy()
    total=amt[amt<0].sum()
    return {"text":f"For **{_scope_text(ctx)}**, I found **{len(refunds):,} negative/refund tender line(s)** totaling **{_fmt_sar(total)}**.",
            "table":refunds.head(500)}

def _lookup_answer(result,ctx,question):
    upper=question.upper()
    # Prefer the token following receipt/auth wording, including short test/demo IDs.
    specific=re.search(r"\b(?:RECEIPT|AUTH|AUTHORIZATION)\s*(?:ID|CODE|NO|NUMBER)?\s*[:#-]?\s*([A-Z0-9-]{2,})\b",upper)
    nums=re.findall(r"\b[A-Z0-9-]{5,}\b",upper)
    candidates=([specific.group(1)] if specific else []) + [n for n in nums if not re.fullmatch(r"20\d{2}",n)]
    if not candidates:
        return {"text":"Please give me the Receipt ID or Auth Code you want me to investigate.","table":pd.DataFrame()}
    token=candidates[-1]
    frames=[]
    for label,key in [("D365 Tender","tender"),("Matched","matched"),("Unmatched D365","unmatched_sales"),("Unmatched POS","unmatched_pos")]:
        df=result.get(key,pd.DataFrame())
        if df is None or df.empty: continue
        mask=pd.Series(False,index=df.index)
        for c in ["Receipt ID","Receiptid","Auth Code","Provider Reference","ARN","Slip No"]:
            if c in df.columns:
                mask |= df[c].astype(str).str.upper().str.contains(re.escape(token),na=False)
        hit=df[mask].copy()
        if not hit.empty:
            hit.insert(0,"Dataset",label)
            frames.append(hit)
    if not frames:
        return {"text":f"I couldn't find Receipt/Auth reference **{token}** in the active reconciliation.","table":pd.DataFrame()}
    table=pd.concat(frames,ignore_index=True,sort=False)
    return {"text":f"I found **{len(table):,} record(s)** for **{token}** across the active reconciliation datasets.","table":table.head(500)}

def _summary_answer(result,ctx):
    sales=_sales_answer(result,ctx,False)
    ex=_exceptions_answer(result,ctx)
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    settled=int(m["Bank Settled"].fillna(False).astype(bool).sum()) if (not m.empty and "Bank Settled" in m.columns) else 0
    total_matched=len(m)
    text=sales["text"]+" "+ex["text"]
    if total_matched:
        text+=f" Of **{total_matched:,} matched/review transaction(s)** in scope, **{settled:,}** are bank settled."
    return {"text":text,"table":sales["table"]}

def _compare_answer(result,ctx,question):
    stores=_find_store_codes(question)
    if len(stores)<2:
        return {"text":"For a comparison, please mention at least two store codes, for example: `compare 601 and 603 sales as of 9 Aug 2026`.","table":pd.DataFrame()}
    tender=result.get("tender",pd.DataFrame()).copy()
    rows=[]
    for s in stores:
        c=CopilotContext(store_codes=[s],payment=ctx.payment,date_from=ctx.date_from,date_to=ctx.date_to,date_mode=ctx.date_mode)
        x=_filter_tender(tender,c)
        amt=pd.to_numeric(x.get("D365 Amount",0),errors="coerce").fillna(0).sum() if not x.empty else 0
        rows.append({"Store Code":s,"Sales/Tender Total":amt,"Transaction Lines":len(x)})
    table=pd.DataFrame(rows)
    best=table.sort_values("Sales/Tender Total",ascending=False).iloc[0]
    return {"text":f"For {_scope_text(ctx)}, **Store {best['Store Code']}** has the higher tender total at **{_fmt_sar(best['Sales/Tender Total'])}**.","table":table}

def answer_question(question, result, db_module=None, prior_context=None):
    if not result:
        return {
            "text":"I don't have an active reconciliation yet. Please run POS Reconciliation first; then I can answer questions about sales, cash, MADA/Visa/Mastercard, providers, exceptions, bank settlement, commission, corrections and JV status.",
            "table":pd.DataFrame(),
            "context":prior_context or CopilotContext(),
            "intent":"no_data",
        }

    intent,ctx=interpret_query(question,result,prior_context)
    ql=question.lower()

    if intent=="greeting":
        payload={"text":"Good morning. I can help with the active RetailRecon data — ask me about a store, date, payment type, settlement, exceptions, commission, refunds, corrections or JV/D365 status.","table":pd.DataFrame()}
    elif intent=="sales":
        payload=_sales_answer(result,ctx,detail=False)
    elif intent=="transactions":
        payload=_sales_answer(result,ctx,detail=True)
    elif intent in {"exceptions","missing_pos","missing_d365"}:
        if intent=="missing_pos":
            df=_filter_recon(result.get("unmatched_sales",pd.DataFrame()),ctx)
            payload={"text":f"For **{_scope_text(ctx)}**, there are **{len(df):,} D365 transaction(s)** currently without a matching POS/provider settlement.","table":df.head(500)}
        elif intent=="missing_d365":
            df=_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")
            payload={"text":f"For **{_scope_text(ctx)}**, there are **{len(df):,} provider/POS transaction(s)** currently without a matching D365 Store Tender record.","table":df.head(500)}
        else:
            payload=_exceptions_answer(result,ctx)
    elif intent=="unsettled":
        payload=_unsettled_answer(result,ctx)
    elif intent=="commission":
        payload=_commission_answer(result,ctx)
    elif intent=="refunds":
        payload=_refunds_answer(result,ctx)
    elif intent=="lookup":
        payload=_lookup_answer(result,ctx,question)
    elif intent=="compare":
        payload=_compare_answer(result,ctx,question)
    elif intent=="corrections":
        if db_module is None:
            payload={"text":"Correction status is unavailable because the database module is not connected.","table":pd.DataFrame()}
        else:
            df=db_module.load_correction_log()
            if not df.empty and "Status" in df.columns:
                pending=df[df["Status"].astype(str).str.upper().eq("PENDING APPROVAL")]
            else:
                pending=df
            payload={"text":f"There are **{len(pending):,} correction request(s)** pending approval.","table":pending.head(500)}
    elif intent=="jv":
        if db_module is None:
            payload={"text":"JV status is unavailable because the database module is not connected.","table":pd.DataFrame()}
        else:
            df=db_module.load_jv()
            if df.empty:
                payload={"text":"No JV batches are currently stored.","table":df}
            else:
                approved=int(df.get("Approval Status",pd.Series(dtype=str)).astype(str).str.upper().eq("APPROVED").sum()) if "Approval Status" in df.columns else 0
                posted=int(df.get("Posted",pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if "Posted" in df.columns else 0
                payload={"text":f"I found **{len(df):,} JV row(s)** in the control table; **{approved:,}** are approved and **{posted:,}** are marked posted.","table":df.head(500)}
    elif intent=="close":
        if db_module is None:
            payload={"text":"Close-calendar status is unavailable because the database module is not connected.","table":pd.DataFrame()}
        else:
            try:
                cal=db_module.load_close_calendar()
                payload={"text":f"The close calendar currently contains **{len(cal):,} control item(s)**. Review the table below for current ownership/status.","table":cal}
            except Exception:
                payload={"text":"I couldn't read the close calendar from the current database.","table":pd.DataFrame()}
    elif intent=="mapping":
        up=result.get("unmatched_pos",pd.DataFrame())
        if up is None or up.empty:
            payload={"text":"There are no current provider-side mapping exceptions.","table":pd.DataFrame()}
        else:
            status=up.get("Status",pd.Series("",index=up.index)).astype(str)
            mask=status.str.contains("Mapping Required",case=False,na=False)
            df=up[mask].copy()
            payload={"text":f"I found **{len(df):,} provider transaction(s)** requiring terminal, merchant or store mapping.","table":df.head(500)}
    else:
        payload=_summary_answer(result,ctx)

    payload["context"]=ctx
    payload["intent"]=intent
    return payload

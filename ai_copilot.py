from __future__ import annotations

import re
import difflib
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

def _store_name_map(db_module=None):
    """
    Store Code -> known display/provider names, so a question can name a
    store ("Tahlia Mall sales") instead of only its numeric code. Combines
    the confirmed D365 store display names (core.D365_STORE_DISPLAY) with
    whatever provider store names Finance has mapped in the Store Mapping
    Master, so both "official" and provider-file naming work.
    """
    names={}
    try:
        import core as _core
        for code,info in _core.D365_STORE_DISPLAY.items():
            n=str(info.get("store_name","")).strip()
            if n:
                names.setdefault(code,set()).add(n)
    except Exception:
        pass
    if db_module is not None:
        try:
            sm=db_module.load_store_mapping_master()
            if not sm.empty and {"Store Code","Provider Store Name"}.issubset(sm.columns):
                for _,r in sm.iterrows():
                    code=_norm_store(r.get("Store Code",""))
                    n=str(r.get("Provider Store Name","")).strip()
                    if code and n:
                        names.setdefault(code,set()).add(n)
        except Exception:
            pass
    return names

def _best_store_name(store_code, db_module=None):
    code=_norm_store(store_code)
    if not code:
        return ""
    try:
        import core as _core
        info=_core.D365_STORE_DISPLAY.get(code,{})
        n=str(info.get("store_name","")).strip()
        if n:
            return n
    except Exception:
        pass
    names=_store_name_map(db_module).get(code,set())
    cleaned=[str(x).strip() for x in names if str(x).strip()]
    return " / ".join(sorted(dict.fromkeys(cleaned))) if cleaned else ""

def _store_label(store_code, db_module=None):
    code=_norm_store(store_code)
    name=_best_store_name(code,db_module)
    return f"Store {code} – {name}" if name else f"Store {code}"

def _add_store_name_column(df, db_module=None, store_col="Store Code"):
    if df is None or df.empty or store_col not in df.columns:
        return df
    out=df.copy()
    names=out[store_col].map(lambda x:_best_store_name(x,db_module))
    if "Store Name" in out.columns:
        old=out["Store Name"].astype(str)
        out["Store Name"]=names.where(names.astype(str).str.len()>0,old)
    else:
        out.insert(list(out.columns).index(store_col)+1,"Store Name",names)
    return out

def _find_store_codes_by_name(q,db_module=None):
    """
    Match known store names inside free text. Requires the matched name to
    be at least 4 characters so a generic single word (e.g. "Mall") never
    becomes a false-positive store match on its own.
    """
    name_map=_store_name_map(db_module)
    if not name_map:
        return []
    ql=q.lower()
    hits=[]
    for code,names in name_map.items():
        for n in names:
            nl=n.lower().strip()
            if len(nl)>=4 and nl in ql:
                hits.append(code)
                break
    return hits

# Fuzzy-match candidates: only full canonical words, never short codes like
# "vc"/"mc"/"p1" - typo-tolerance on a 2-letter abbreviation is too noisy to
# be reliable (almost anything is "close" to a 2-letter string).
_PAYMENT_FUZZY_CANDIDATES = {
    a: p for p, aliases in PAYMENT_ALIASES.items() for a in aliases if len(a) >= 4 and " " not in a
}

def _find_payment(q):
    ql=q.lower()
    for payment, aliases in PAYMENT_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", ql) for a in aliases):
            return payment
    # Typo tolerance: "mastercart", "vise", "tammara", "amx" etc. Cutoff 0.72
    # was chosen to catch realistic single/double-character typos on real
    # payment names without matching ordinary finance vocabulary (checked
    # against words like "sales","store","total","refund","settle", etc.).
    for tok in re.findall(r"[a-z]{3,}", ql):
        match=difflib.get_close_matches(tok, _PAYMENT_FUZZY_CANDIDATES.keys(), n=1, cutoff=0.72)
        if match:
            return _PAYMENT_FUZZY_CANDIDATES[match[0]]
    return None

def _parse_named_date(text, default_year=None):
    text=text.strip().lower().replace(","," ")
    year_default=int(default_year or pd.Timestamp.today().year)

    # 9 aug 2026 / 9 august
    m=re.search(r"\b(\d{1,2})\s+([a-z]{3,9})(?:\s+(\d{4}))?\b",text)
    if m and m.group(2) in MONTHS:
        day=int(m.group(1)); month=MONTHS[m.group(2)]
        year=int(m.group(3)) if m.group(3) else year_default
        return pd.Timestamp(year=year,month=month,day=day)

    # aug 9 2026 / august 9
    m=re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:\s+(\d{4}))?\b",text)
    if m and m.group(1) in MONTHS:
        month=MONTHS[m.group(1)]; day=int(m.group(2))
        year=int(m.group(3)) if m.group(3) else year_default
        return pd.Timestamp(year=year,month=month,day=day)

    # ISO 2026-08-09
    m=re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",text)
    if m:
        return pd.Timestamp(int(m.group(1)),int(m.group(2)),int(m.group(3)))

    # Natural finance question numeric date: D/M/YYYY (separate from source-file parser).
    m=re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b",text)
    if m:
        day,month,year=map(int,m.groups())
        try:
            return pd.Timestamp(year=year,month=month,day=day)
        except Exception:
            return None

    return None

def _parse_date_scope(q, data_min=None, data_max=None, prior=None):
    ql=q.lower().strip()
    today=pd.Timestamp.today().normalize()
    default_year=(data_max.year if pd.notna(data_max) else today.year)

    if "yesterday" in ql:
        d=today-pd.Timedelta(days=1)
        return d,d,"on"
    if re.search(r"\btoday\b",ql):
        return today,today,"on"

    # Relative periods, anchored on "today" the same way yesterday/today
    # already are above (system clock, not the dataset's max date - the
    # dataset itself may only cover a partial period).
    if re.search(r"\b(mtd|month[\s-]?to[\s-]?date)\b",ql):
        return today.replace(day=1),today,"range"
    if re.search(r"\b(ytd|year[\s-]?to[\s-]?date)\b",ql):
        return today.replace(month=1,day=1),today,"range"
    if re.search(r"\bthis\s+week\b",ql):
        start=today-pd.Timedelta(days=today.weekday())
        return start,today,"range"
    if re.search(r"\blast\s+week\b",ql):
        this_week_start=today-pd.Timedelta(days=today.weekday())
        end=this_week_start-pd.Timedelta(days=1)
        start=end-pd.Timedelta(days=6)
        return start,end,"range"
    if re.search(r"\bthis\s+month\b",ql):
        return today.replace(day=1),today,"range"
    if re.search(r"\blast\s+month\b",ql):
        first_this_month=today.replace(day=1)
        end=first_this_month-pd.Timedelta(days=1)
        start=end.replace(day=1)
        return start,end,"range"

    # 1-5 Aug 2026 / 1 – 5 August 2026
    m=re.search(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([a-z]{3,9})(?:\s+(20\d{2}))?\b",ql)
    if m and m.group(3) in MONTHS:
        year=int(m.group(4)) if m.group(4) else int(default_year)
        month=MONTHS[m.group(3)]
        d1=pd.Timestamp(year=year,month=month,day=int(m.group(1)))
        d2=pd.Timestamp(year=year,month=month,day=int(m.group(2)))
        return min(d1,d2),max(d1,d2),"range"

    # 1/8/2026 - 5/8/2026
    m=re.search(r"\b(\d{1,2}/\d{1,2}/20\d{2})\s*[-–]\s*(\d{1,2}/\d{1,2}/20\d{2})\b",ql)
    if m:
        d1=_parse_named_date(m.group(1),default_year)
        d2=_parse_named_date(m.group(2),default_year)
        if d1 is not None and d2 is not None:
            return min(d1,d2),max(d1,d2),"range"

    # between X and Y
    m=re.search(r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:$|[?.])",ql)
    if m:
        d1=_parse_named_date(m.group(1),default_year)
        d2=_parse_named_date(m.group(2),default_year)
        if d1 is not None and d2 is not None:
            return min(d1,d2),max(d1,d2),"range"

    # from X to/until/through Y
    m=re.search(r"\bfrom\s+(.+?)\s+(?:to|until|through)\s+(.+?)(?:$|[?.])",ql)
    if m:
        d1=_parse_named_date(m.group(1),default_year)
        d2=_parse_named_date(m.group(2),default_year)
        if d1 is not None and d2 is not None:
            return min(d1,d2),max(d1,d2),"range"

    # Bare range: "1 Aug 2026 to 5 Aug 2026", "Aug 1 through Aug 5"
    m=re.search(r"(.+?)\s+(?:to|through|until)\s+(.+?)(?:$|[?.])",ql)
    if m:
        d1=_parse_named_date(m.group(1),default_year)
        d2=_parse_named_date(m.group(2),default_year)
        if d1 is not None and d2 is not None:
            # If one side omits year but the other has it, align years.
            explicit_years=re.findall(r"\b(20\d{2})\b",ql)
            if explicit_years:
                yr=int(explicit_years[-1])
                if not re.search(r"\b20\d{2}\b",m.group(1)):
                    d1=d1.replace(year=yr)
                if not re.search(r"\b20\d{2}\b",m.group(2)):
                    d2=d2.replace(year=yr)
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

    # Plain named date = one day.
    d=_parse_named_date(ql,default_year)
    if d is not None:
        return d,d,"on"

    # Month scope
    for name,month in MONTHS.items():
        if re.search(rf"\b{name}\b",ql):
            year_match=re.search(r"\b(20\d{2})\b",ql)
            year=int(year_match.group(1)) if year_match else default_year
            start=pd.Timestamp(year=year,month=month,day=1)
            end=start+pd.offsets.MonthEnd(1)
            return start,end,"month"

    # Keep prior date range on follow-up.
    if prior and prior.date_from is not None:
        return prior.date_from,prior.date_to,prior.date_mode
    return None,None,""

def interpret_query(question, result, prior: CopilotContext|None=None, db_module=None):
    prior=prior or CopilotContext()
    q=question.strip()
    ql=q.lower()

    tender=result.get("tender",pd.DataFrame()) if result else pd.DataFrame()
    all_dates=pd.to_datetime(tender.get("Date",pd.Series(dtype="datetime64[ns]")),errors="coerce").dropna()
    data_min=all_dates.min().normalize() if not all_dates.empty else pd.NaT
    data_max=all_dates.max().normalize() if not all_dates.empty else pd.NaT

    stores=_find_store_codes(q)
    if not stores:
        stores=_find_store_codes_by_name(q,db_module)
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
    elif any(x in ql for x in [
        "settlement batch","settlement batches","bank receipt pending","provider settled",
        "which settlements","bank received batches","payout pending","settlement propagation"
    ]):
        intent="settlement_batch"
    elif any(x in ql for x in [
        "gl status","gl verified","d365 gl","gl mismatch","gl exception","gl exceptions",
        "unexplained gl","explain gl","gl balance","clearing balance","clearing movement",
        "which stores gl","gl not found","jv to gl","source to gl"
    ]):
        intent="gl_control"
    elif any(x in ql for x in [
        "biggest risk","highest risk","risk today","risks today","top risk","top risks",
        "priority exception","priority exceptions","what needs attention","needs attention",
        "anomaly","anomalies","control risk"
    ]):
        intent="risk"
    elif any(x in ql for x in ["store performance","store score","store control score","which store is worst","which store needs attention"]):
        intent="store_performance"
    elif any(x in ql for x in ["provider performance","provider score","payment performance","which provider","provider delay"]):
        intent="provider_performance"
    elif any(x in ql for x in [
        "matched and unmatched","matched & unmatched","match and unmatched","matched/unmatched",
        "reconciliation status","match status","match rate","how much matched","how much unmatched",
        "matched amount","unmatched amount"
    ]):
        intent="reconciliation_status"
    elif any(x in ql for x in ["can i close","ready to close","close readiness","can we close","period close"]):
        intent="close_readiness"
    elif any(x in ql for x in ["finance briefing","today's finance briefing","today finance briefing","management briefing","cfo briefing"]):
        intent="management_brief"
    elif any(x in ql for x in ["bank settled","awaiting bank","settlement delay","oldest unsettled","settlement status","how much is settled"]):
        intent="settlement_intelligence"
    elif any(x in ql for x in ["commission error","commission errors","commission validation","commission amount","vat on commission","commission difference"]):
        intent="commission_intelligence"
    elif any(x in ql for x in ["refund total","refunds by","refund ratio","largest refund","highest refund","show refunds","refund intelligence"]):
        intent="refund_intelligence"
    elif any(x in ql for x in ["duplicate files","duplicate auth","missing dates","unmapped terminal","unmapped merchant","unknown stores","data quality","today's upload","today upload"]):
        intent="data_quality"
    elif any(x in ql for x in ["source file","source files","where did this come from","evidence","data source"]):
        intent="source_evidence"
    elif any(x in ql for x in ["help","what can you answer","what can i ask","capabilities"]):
        intent="copilot_help"
    elif any(x in ql for x in ["exception","anything wrong","issues","problem","unmatched"]):
        intent="exceptions"
    elif any(x in ql for x in [
        "tell date","tell me the date","what date","which date","what dates","which dates",
        "date range","what period","which period","show date","current date range",
        "what's the date","whats the date"
    ]):
        intent="date_range"
    elif (
        payment=="CASH"
        and any(x in ql for x in [
            "cash","sales","sale","refund","refunds","net","highest","lowest",
            "top","rank","ranking","average","largest","details","transactions",
            "trend","daily","all store","all stores"
        ])
    ):
        intent="cash_report"
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
        if prior.last_intent=="cash_report" and any(x in ql for x in [
            "highest","lowest","top","rank","ranking","details","transactions",
            "show","only","daily","trend","store"
        ]):
            intent="cash_report"
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

def _sales_answer(result,ctx,detail=False,db_module=None):
    tender=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    if tender.empty:
        return {"text":f"I couldn't find D365 Store Tender sales for {_scope_text(ctx)} in the active reconciliation.","table":pd.DataFrame()}
    tender=tender.copy()
    tender["D365 Amount"]=pd.to_numeric(tender.get("D365 Amount",0),errors="coerce").fillna(0.0)
    if "Store Code" in tender.columns:
        tender["Store Code"]=tender["Store Code"].map(_norm_store)
        tender=_add_store_name_column(tender,db_module,"Store Code")
    grp=tender.groupby(tender["D365 Payment"].astype(str).str.upper(),dropna=False)["D365 Amount"].sum().sort_values(ascending=False)
    gross=float(tender["D365 Amount"].sum())
    positive=float(tender.loc[tender["D365 Amount"]>0,"D365 Amount"].sum())
    refunds=float(tender.loc[tender["D365 Amount"]<0,"D365 Amount"].sum())
    if len(ctx.store_codes)==1:
        parts=[_store_label(ctx.store_codes[0],db_module)]
        if ctx.payment: parts.append(ctx.payment)
        if ctx.date_from is not None and ctx.date_to is not None:
            if ctx.date_from==ctx.date_to: parts.append(_fmt_date(ctx.date_from))
            elif ctx.date_mode=="as_of": parts.append(f"up to {_fmt_date(ctx.date_to)}")
            else: parts.append(f"{_fmt_date(ctx.date_from)} to {_fmt_date(ctx.date_to)}")
        elif ctx.date_to is not None: parts.append(f"up to {_fmt_date(ctx.date_to)}")
        scope=" | ".join(parts)
    else:
        scope=_scope_text(ctx)
    lines=[f"Here are the D365 Store Tender sales for **{scope}**.",f"Net tender total is **{_fmt_sar(gross)}**. Positive sales total **{_fmt_sar(positive)}** and refunds/negative tenders total **{_fmt_sar(refunds)}**."]
    if not ctx.payment:
        mix=", ".join(f"{p}: {_fmt_sar(v)}" for p,v in grp.items() if abs(float(v))>0)
        if mix: lines.append("Payment breakdown: "+mix+".")
    else:
        lines.append(f"{ctx.payment} total is **{_fmt_sar(gross)}** across **{len(tender):,}** transaction line(s).")
    if detail:
        cols=[c for c in ["Store Code","Store Name","Date","Receipt ID","Auth Code","D365 Payment","D365 Amount","Cash Classification","Cash Amount"] if c in tender.columns]
        sorts=[c for c in ["Date","Receipt ID"] if c in cols]
        table=tender[cols].sort_values(sorts) if sorts else tender[cols]
        return {"text":" ".join(lines),"table":table}
    if "Store Code" in tender.columns:
        base=tender.copy(); base["Payment Type"]=base["D365 Payment"].astype(str).str.upper()
        summary=base.groupby(["Store Code","Store Name","Payment Type"],dropna=False).agg(Amount=("D365 Amount","sum"), **{"Transaction Count":("D365 Amount","size")}).reset_index()
    else:
        summary=pd.DataFrame({"Payment Type":grp.index,"Amount":grp.values})
    return {"text":" ".join(lines),"table":summary}

def _cash_report(result,ctx,question="",db_module=None):
    """
    Advanced D365 Store Tender cash analytics.

    Source of truth: D365 Store Tender CASH only.
    Positive value = Cash Sales.
    Negative value = Cash Refund.
    No POS/provider settlement is expected for CASH.
    """
    ql=str(question or "").lower()

    # Force cash regardless of prior payment wording.
    cash_ctx=CopilotContext(
        store_codes=ctx.store_codes,
        payment="CASH",
        date_from=ctx.date_from,
        date_to=ctx.date_to,
        date_mode=ctx.date_mode,
        last_intent="cash_report",
    )
    cash=_filter_tender(result.get("tender",pd.DataFrame()),cash_ctx)

    if cash.empty:
        return {
            "text":f"I couldn't find Cash transactions in D365 Store Tender for **{_scope_text(cash_ctx)}**.",
            "table":pd.DataFrame(),
        }

    cash=cash.copy()
    cash["Store Code"]=cash["Store Code"].map(_norm_store)
    cash["Date"]=pd.to_datetime(cash["Date"],errors="coerce")
    cash["Cash Signed Amount"]=pd.to_numeric(
        cash.get("Cash Amount",cash.get("D365 Amount",0)),errors="coerce"
    ).fillna(0.0)
    cash["Cash Classification"]=np.where(
        cash["Cash Signed Amount"]>0,"Cash Sales",
        np.where(cash["Cash Signed Amount"]<0,"Cash Refund","")
    )

    # Optional store-name enrichment from master data.
    name_map={}
    if db_module is not None:
        try:
            sm=db_module.load_store_mapping_master()
            if not sm.empty and {"Store Code","Provider Store Name"}.issubset(sm.columns):
                sm=sm.copy()
                sm["Store Code"]=sm["Store Code"].map(_norm_store)
                grouped=sm.groupby("Store Code")["Provider Store Name"].apply(
                    lambda s:" / ".join(dict.fromkeys(
                        [str(x).strip() for x in s if str(x).strip()]
                    ))
                )
                name_map=grouped.to_dict()
        except Exception:
            name_map={}

    # Same scope across ALL payment types for Cash Mix % denominator.
    all_ctx=CopilotContext(
        store_codes=ctx.store_codes,
        payment=None,
        date_from=ctx.date_from,
        date_to=ctx.date_to,
        date_mode=ctx.date_mode,
    )
    all_tender=_filter_tender(result.get("tender",pd.DataFrame()),all_ctx)
    if not all_tender.empty:
        all_tender=all_tender.copy()
        all_tender["Store Code"]=all_tender["Store Code"].map(_norm_store)
        all_tender["Amt"]=pd.to_numeric(all_tender.get("D365 Amount",0),errors="coerce").fillna(0.0)
        positive_total_by_store=(
            all_tender[all_tender["Amt"]>0]
            .groupby("Store Code")["Amt"].sum()
            .to_dict()
        )
        all_stores=set(all_tender["Store Code"].dropna().astype(str))
    else:
        positive_total_by_store={}
        all_stores=set()

    rows=[]
    for store,g in cash.groupby("Store Code",dropna=False):
        a=g["Cash Signed Amount"]
        sales=a[a>0]
        refunds=a[a<0]
        cash_sales=float(sales.sum())
        refund_abs=float(abs(refunds.sum()))
        net=float(a.sum())
        total_positive=float(positive_total_by_store.get(str(store),0.0))
        cash_mix=(cash_sales/total_positive*100.0) if total_positive else 0.0
        refund_ratio=(refund_abs/cash_sales*100.0) if cash_sales else (100.0 if refund_abs else 0.0)

        rows.append({
            "Store Code":str(store),
            "Store Name":name_map.get(str(store),""),
            "Cash Sales":cash_sales,
            "Cash Refunds":refund_abs,
            "Net Cash":net,
            "Sales Count":int((a>0).sum()),
            "Refund Count":int((a<0).sum()),
            "Total Cash Transactions":int((a!=0).sum()),
            "Average Cash Sale":float(sales.mean()) if not sales.empty else 0.0,
            "Largest Cash Sale":float(sales.max()) if not sales.empty else 0.0,
            "Largest Cash Refund":float(abs(refunds.min())) if not refunds.empty else 0.0,
            "Cash Refund Ratio %":refund_ratio,
            "Cash Mix % of Positive Tender Sales":cash_mix,
            "First Cash Date":g["Date"].min(),
            "Last Cash Date":g["Date"].max(),
        })

    summary=pd.DataFrame(rows)
    if summary.empty:
        return {"text":"No cash activity found in the selected scope.","table":summary}

    # Ranking/filter behavior from natural language.
    if any(x in ql for x in ["highest","top","rank","ranking"]):
        summary=summary.sort_values(["Net Cash","Cash Sales"],ascending=[False,False])
        m=re.search(r"\btop\s+(\d+)\b",ql)
        if m:
            summary=summary.head(max(1,int(m.group(1))))
    elif "lowest" in ql:
        summary=summary.sort_values(["Net Cash","Cash Sales"],ascending=[True,True])
    else:
        summary=summary.sort_values("Store Code")

    # Transaction drill-down.
    wants_transactions=any(x in ql for x in [
        "transaction details","transactions","receipt details","show details","details for"
    ]) or (ctx.store_codes and "details" in ql)

    if wants_transactions:
        cols=[c for c in [
            "Store Code","Date","Receipt ID","Auth Code","Cash Classification",
            "Cash Signed Amount","Customer Name","Staff","Sales Person",
            "D365 Amount","D365 Row"
        ] if c in cash.columns]
        details=cash[cols].sort_values(["Store Code","Date","Receipt ID"])
        sales_total=float(cash.loc[cash["Cash Signed Amount"]>0,"Cash Signed Amount"].sum())
        refund_total=float(abs(cash.loc[cash["Cash Signed Amount"]<0,"Cash Signed Amount"].sum()))
        net_total=float(cash["Cash Signed Amount"].sum())
        text=(
            f"Here are the cash transaction details for **{_scope_text(cash_ctx)}**. "
            f"Cash Sales are **{_fmt_sar(sales_total)}**, Cash Refunds are **{_fmt_sar(refund_total)}**, "
            f"and Net Cash is **{_fmt_sar(net_total)}** across **{len(cash):,}** cash transaction(s). "
            "These values come directly from D365 Store Tender; cash does not require POS/provider settlement."
        )
        return {"text":text,"table":details.head(2000)}

    # Daily trend.
    if any(x in ql for x in ["daily","day by day","trend"]):
        tmp=cash.copy()
        tmp["Cash Sales"]=tmp["Cash Signed Amount"].clip(lower=0)
        tmp["Cash Refunds"]=(-tmp["Cash Signed Amount"].clip(upper=0))
        daily=tmp.groupby(["Date","Store Code"],as_index=False).agg(
            Cash_Sales=("Cash Sales","sum"),
            Cash_Refunds=("Cash Refunds","sum"),
            Net_Cash=("Cash Signed Amount","sum"),
            Transactions=("Cash Signed Amount","size"),
        )
        daily=daily.rename(columns={
            "Cash_Sales":"Cash Sales","Cash_Refunds":"Cash Refunds",
            "Net_Cash":"Net Cash"
        })
        return {
            "text":f"Here is the day-by-day cash trend for **{_scope_text(cash_ctx)}**.",
            "table":daily.sort_values(["Date","Store Code"]).head(2000),
        }

    total_sales=float(summary["Cash Sales"].sum())
    total_refunds=float(summary["Cash Refunds"].sum())
    total_net=float(summary["Net Cash"].sum())
    total_count=int(summary["Total Cash Transactions"].sum())
    highest=summary.sort_values("Net Cash",ascending=False).iloc[0]
    refund_rank=summary[summary["Cash Refunds"]>0].sort_values(
        "Cash Refund Ratio %",ascending=False
    )
    negative_stores=summary[summary["Net Cash"]<0]
    cash_store_codes=set(summary["Store Code"].astype(str))
    no_cash_stores=sorted(all_stores-cash_store_codes)

    lines=[
        f"Here is the cash analysis for **{_scope_text(cash_ctx)}**.",
        f"Cash Sales are **{_fmt_sar(total_sales)}**, Cash Refunds are **{_fmt_sar(total_refunds)}**, "
        f"and Net Cash is **{_fmt_sar(total_net)}** across **{total_count:,}** cash transaction(s).",
        f"**Store {highest['Store Code']}** has the highest Net Cash at **{_fmt_sar(highest['Net Cash'])}**.",
    ]
    if not refund_rank.empty:
        rr=refund_rank.iloc[0]
        lines.append(
            f"**Store {rr['Store Code']}** has the highest cash refund ratio in this selected scope "
            f"at **{float(rr['Cash Refund Ratio %']):,.2f}%**."
        )
    if not negative_stores.empty:
        lines.append(
            f"**{len(negative_stores)} store(s)** have negative Net Cash in the selected period and should be reviewed."
        )
    if no_cash_stores:
        lines.append(
            f"**{len(no_cash_stores)} store(s)** in the selected D365 tender scope have no cash activity."
        )
    lines.append(
        "Cash is sourced directly from D365 Store Tender: positive Cash = Cash Sales, "
        "negative Cash = Cash Refund. No POS/provider settlement is expected for cash."
    )

    return {"text":" ".join(lines),"table":summary.reset_index(drop=True)}


def _date_range_answer(result,ctx):
    """
    Answer "tell date" / "what date" style follow-ups: report the date span
    of the CURRENT analysis scope (store/payment/date context retained from
    the prior turn) without recomputing or repeating totals.
    """
    df=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    dates=pd.to_datetime(df.get("Date",pd.Series(dtype="datetime64[ns]")),errors="coerce").dropna()
    scope=_scope_text(ctx)
    if dates.empty:
        return {
            "text":f"I don't have any transactions in scope for **{scope}** to determine a date range.",
            "table":pd.DataFrame(),
        }
    d_min,d_max=dates.min(),dates.max()
    if d_min==d_max:
        text=f"The current analysis for **{scope}** is for a single date: **{_fmt_date(d_min)}**."
    else:
        text=f"The current analysis date range for **{scope}** is **{_fmt_date(d_min)} to {_fmt_date(d_max)}**."
    return {"text":text,"table":pd.DataFrame()}

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

def _summary_answer(result,ctx,db_module=None):
    sales=_sales_answer(result,ctx,False,db_module)
    ex=_exceptions_answer(result,ctx)
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    settled=int(m["Bank Settled"].fillna(False).astype(bool).sum()) if (not m.empty and "Bank Settled" in m.columns) else 0
    total_matched=len(m)
    text=sales["text"]+" "+ex["text"]
    if total_matched:
        text+=f" Of **{total_matched:,} matched/review transaction(s)** in scope, **{settled:,}** are bank settled."
    return {"text":text,"table":sales["table"]}

def _compare_answer(result,ctx,question,db_module=None):
    stores=_find_store_codes(question)
    if len(stores)<2:
        stores=list(dict.fromkeys(stores+_find_store_codes_by_name(question,db_module)))
    if len(stores)<2:
        return {"text":"For a comparison, please mention at least two store codes, for example: `compare 601 and 603 sales as of 9 Aug 2026`.","table":pd.DataFrame()}
    tender=result.get("tender",pd.DataFrame()).copy()
    rows=[]
    for s in stores:
        c=CopilotContext(store_codes=[s],payment=ctx.payment,date_from=ctx.date_from,date_to=ctx.date_to,date_mode=ctx.date_mode)
        x=_filter_tender(tender,c)
        amt=pd.to_numeric(x.get("D365 Amount",0),errors="coerce").fillna(0).sum() if not x.empty else 0
        rows.append({"Store Code":s,"Store Name":_best_store_name(s,db_module),"Sales/Tender Total":amt,"Transaction Lines":len(x)})
    table=pd.DataFrame(rows)
    best=table.sort_values("Sales/Tender Total",ascending=False).iloc[0]
    return {"text":f"For {_scope_text(ctx)}, **Store {best['Store Code']}** has the higher tender total at **{_fmt_sar(best['Sales/Tender Total'])}**.","table":table}

def _allowed_store_codes(user_context):
    """
    Optional role-aware scope.
    Finance/Admin roles remain unrestricted.
    A future Store User can be restricted by setting:
      user_context["store_codes"] = ["601", ...]
    This keeps the Copilot aligned with application permissions without
    changing existing finance-user behavior.
    """
    if not user_context:
        return None
    stores=user_context.get("store_codes") or user_context.get("stores")
    if stores:
        return {_norm_store(x) for x in stores if _norm_store(x)}
    return None

def _restrict_df_to_stores(df, allowed):
    if df is None or df.empty or not allowed:
        return df
    x=df.copy()
    for col in ["Store Code","POS Store","Store"]:
        if col in x.columns:
            return x[x[col].map(_norm_store).isin(allowed)].copy()
    return x

def _apply_user_scope(result, user_context):
    allowed=_allowed_store_codes(user_context)
    if not allowed or not result:
        return result
    scoped={}
    for k,v in result.items():
        if isinstance(v,pd.DataFrame):
            scoped[k]=_restrict_df_to_stores(v,allowed)
        else:
            scoped[k]=v
    return scoped


def _reconciliation_status_answer(result,ctx,question="",db_module=None):
    matched=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    missing_pos=_filter_recon(result.get("unmatched_sales",pd.DataFrame()),ctx)
    missing_d365=_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")
    def _sum(df,cols):
        if df is None or df.empty:return 0.0
        for c in cols:
            if c in df.columns:return float(pd.to_numeric(df[c],errors="coerce").fillna(0).abs().sum())
        return 0.0
    ma=_sum(matched,["D365 Amount","Sales Amount","POS Amount"]); ua=_sum(missing_pos,["D365 Amount","Sales Amount"]); pa=_sum(missing_d365,["POS Amount","Net Amount"])
    mc,uc,pc=len(matched),len(missing_pos),len(missing_d365)
    rate=mc/(mc+uc)*100 if mc+uc else 0.0
    scope=_store_label(ctx.store_codes[0],db_module) if len(ctx.store_codes)==1 else _scope_text(ctx)
    if ctx.payment:scope+=f" | {ctx.payment}"
    table=pd.DataFrame([{"Category":"Matched","Amount":ma,"Transactions":mc},{"Category":"Unmatched D365 / Missing POS","Amount":ua,"Transactions":uc},{"Category":"Unmatched POS / Missing D365","Amount":pa,"Transactions":pc},{"Category":"Total Exceptions","Amount":ua+pa,"Transactions":uc+pc}])
    return {"text":f"Here is the reconciliation status for **{scope}**. **Matched:** {_fmt_sar(ma)} across **{mc:,}** transaction(s). **Unmatched D365 / Missing POS:** {_fmt_sar(ua)} across **{uc:,}** transaction(s). **Unmatched POS / Missing D365:** {_fmt_sar(pa)} across **{pc:,}** transaction(s). **Total Exceptions:** {_fmt_sar(ua+pa)} across **{uc+pc:,}** transaction(s). **D365 transaction match rate:** {rate:,.2f}%.","table":table}

def _risk_answer(result,ctx,question="",db_module=None):
    """
    Finance-control risk view built only from active application data.
    It does not make fraud accusations; it prioritizes review items.
    """
    ql=str(question or "").lower()
    us=_filter_recon(result.get("unmatched_sales",pd.DataFrame()),ctx)
    up=_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)

    rows=[]

    # Missing POS / provider settlement.
    if not us.empty:
        amt=pd.to_numeric(us.get("D365 Amount",0),errors="coerce").fillna(0).abs()
        for idx,r in us.iterrows():
            rows.append({
                "Risk Type":"Missing POS/Provider",
                "Store Code":_norm_store(r.get("Store Code","")),
                "Date":r.get("Date",pd.NaT),
                "Payment Type":str(r.get("D365 Payment","")),
                "Reference":str(r.get("Auth Code","") or r.get("Receipt ID","")),
                "Amount":float(abs(pd.to_numeric(pd.Series([r.get("D365 Amount",0)]),errors="coerce").fillna(0).iloc[0])),
                "Age Days":max(0,(pd.Timestamp.today().normalize()-pd.to_datetime(r.get("Date"),errors="coerce").normalize()).days) if pd.notna(pd.to_datetime(r.get("Date"),errors="coerce")) else 0,
                "Reason":str(r.get("Reason","Missing settlement")),
            })

    # Provider/POS without D365 or mapping/date issues.
    if not up.empty:
        for idx,r in up.iterrows():
            status=str(r.get("Exception Status",r.get("Status","Provider/POS exception")))
            rows.append({
                "Risk Type":status,
                "Store Code":_norm_store(r.get("POS Store","")),
                "Date":r.get("POS Date",pd.NaT),
                "Payment Type":str(r.get("POS Payment","")),
                "Reference":str(r.get("Auth Code","") or r.get("Provider Reference","")),
                "Amount":float(abs(pd.to_numeric(pd.Series([r.get("POS Amount",0)]),errors="coerce").fillna(0).iloc[0])),
                "Age Days":max(0,(pd.Timestamp.today().normalize()-pd.to_datetime(r.get("POS Date"),errors="coerce").normalize()).days) if pd.notna(pd.to_datetime(r.get("POS Date"),errors="coerce")) else 0,
                "Reason":str(r.get("Reason",status)),
            })

    # Matched but bank not settled.
    if not m.empty and "Bank Settled" in m.columns:
        u=m[~m["Bank Settled"].fillna(False).astype(bool)].copy()
        for idx,r in u.iterrows():
            rows.append({
                "Risk Type":"Bank Settlement Outstanding",
                "Store Code":_norm_store(r.get("Store Code","")),
                "Date":r.get("Date",pd.NaT),
                "Payment Type":str(r.get("Payment Type","")),
                "Reference":str(r.get("Auth Code","")),
                "Amount":float(abs(pd.to_numeric(pd.Series([r.get("D365 Amount",r.get("Sales Amount",0))]),errors="coerce").fillna(0).iloc[0])),
                "Age Days":max(0,(pd.Timestamp.today().normalize()-pd.to_datetime(r.get("Posting Date",r.get("Date")),errors="coerce").normalize()).days) if pd.notna(pd.to_datetime(r.get("Posting Date",r.get("Date")),errors="coerce")) else 0,
                "Reason":"Matched transaction has not yet been verified against bank settlement.",
            })

    risk=pd.DataFrame(rows)
    if not risk.empty and "Store Code" in risk.columns:
        risk=_add_store_name_column(risk,db_module,"Store Code")
    if risk.empty:
        return {"text":f"I found no open reconciliation or bank-settlement risks for **{_scope_text(ctx)}** in the active data.","table":risk}

    # Priority score: materiality + aging + issue class.
    type_weight={
        "Bank Settlement Outstanding":30,
        "Missing POS/Provider":25,
        "Missing D365":20,
        "Terminal Mapping Required":15,
        "Merchant Mapping Required":15,
        "Store Mapping Required":15,
        "Date Validation Required":10,
        "Duplicate Provider/POS":10,
    }
    risk["Priority Score"]=(
        risk["Risk Type"].map(type_weight).fillna(10)
        + np.minimum(risk["Age Days"].fillna(0),30)
        + np.minimum(np.log10(risk["Amount"].clip(lower=1))*10,40)
    ).round(1)
    risk["Priority"]=pd.cut(
        risk["Priority Score"],
        bins=[-np.inf,25,45,65,np.inf],
        labels=["Low","Medium","High","Critical"]
    ).astype(str)
    risk=risk.sort_values(["Priority Score","Amount"],ascending=[False,False]).reset_index(drop=True)

    topn=10
    mtop=re.search(r"\btop\s+(\d+)\b",ql)
    if mtop:
        topn=max(1,min(100,int(mtop.group(1))))
    if any(x in ql for x in ["biggest","highest","largest","top"]):
        show=risk.head(topn)
    else:
        show=risk.head(50)

    total=float(risk["Amount"].sum())
    critical=int((risk["Priority"]=="Critical").sum())
    top=show.iloc[0]
    text=(
        f"For **{_scope_text(ctx)}**, I found **{len(risk):,} open finance-control risk item(s)** "
        f"with gross exposure of about **{_fmt_sar(total)}**. "
        f"**{critical:,}** item(s) are currently Critical by amount/age/control priority. "
        f"The highest-priority item is **{top['Risk Type']}** for **{_store_label(top['Store Code'],db_module) if top['Store Code'] else 'Unmapped Store'}**, "
        f"amount **{_fmt_sar(top['Amount'])}**, age **{int(top['Age Days'])} day(s)**."
    )
    return {"text":text,"table":show}

def _store_performance_answer(result,ctx,db_module=None):
    tender=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    us=_filter_recon(result.get("unmatched_sales",pd.DataFrame()),ctx)
    up=_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)

    stores=set()
    for df,col in [(tender,"Store Code"),(us,"Store Code"),(up,"POS Store"),(m,"Store Code")]:
        if df is not None and not df.empty and col in df.columns:
            stores |= set(df[col].map(_norm_store).dropna().astype(str))
    rows=[]
    for s in sorted(x for x in stores if x):
        ts=tender[tender["Store Code"].map(_norm_store)==s] if not tender.empty and "Store Code" in tender.columns else pd.DataFrame()
        ms=m[m["Store Code"].map(_norm_store)==s] if not m.empty and "Store Code" in m.columns else pd.DataFrame()
        uss=us[us["Store Code"].map(_norm_store)==s] if not us.empty and "Store Code" in us.columns else pd.DataFrame()
        ups=up[up["POS Store"].map(_norm_store)==s] if not up.empty and "POS Store" in up.columns else pd.DataFrame()
        sales=float(pd.to_numeric(ts.get("D365 Amount",0),errors="coerce").fillna(0).sum()) if not ts.empty else 0
        matched_amt=float(pd.to_numeric(ms.get("D365 Amount",0),errors="coerce").fillna(0).sum()) if not ms.empty else 0
        open_amt=0.0
        if not uss.empty:
            open_amt+=float(pd.to_numeric(uss.get("D365 Amount",0),errors="coerce").fillna(0).abs().sum())
        if not ups.empty:
            open_amt+=float(pd.to_numeric(ups.get("POS Amount",0),errors="coerce").fillna(0).abs().sum())
        bank_open=0
        if not ms.empty and "Bank Settled" in ms.columns:
            bank_open=int((~ms["Bank Settled"].fillna(False).astype(bool)).sum())
        exc=len(uss)+len(ups)
        score=max(0.0,100.0-min(60.0,exc*5.0)-min(30.0,bank_open*3.0)-min(10.0,(open_amt/max(abs(sales),1))*100))
        rows.append({
            "Store Code":s,
            "Store Name":_best_store_name(s,db_module),
            "D365 Tender Total":sales,
            "Matched Amount":matched_amt,
            "Open Exception Amount":open_amt,
            "Exception Count":exc,
            "Bank Outstanding Count":bank_open,
            "Control Score":round(score,1),
        })
    table=pd.DataFrame(rows)
    if table.empty:
        return {"text":"No store performance data is available in the active reconciliation.","table":table}
    table=table.sort_values(["Control Score","Open Exception Amount"],ascending=[True,False])
    worst=table.iloc[0]
    text=(
        f"Store control performance is calculated from current reconciliation exceptions and bank-outstanding items. "
        f"Store **{worst['Store Code']}** currently needs the most attention with a control score of "
        f"**{worst['Control Score']:.1f}/100** and open exception exposure of **{_fmt_sar(worst['Open Exception Amount'])}**."
    )
    return {"text":text,"table":table}

def _provider_performance_answer(result,ctx):
    pos=result.get("pos",pd.DataFrame())
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    up=_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")
    rows=[]
    providers=set()
    if pos is not None and not pos.empty:
        if "Provider" in pos.columns:
            providers |= set(pos["Provider"].astype(str).str.upper().replace({"":"POS"}))
        if "POS Payment" in pos.columns:
            providers |= set(pos["POS Payment"].astype(str).str.upper())
    if not m.empty and "Payment Type" in m.columns:
        providers |= set(m["Payment Type"].astype(str).str.upper())
    for p in sorted(x for x in providers if x and x!="NAN"):
        mm=m[m["Payment Type"].astype(str).str.upper()==p] if not m.empty and "Payment Type" in m.columns else pd.DataFrame()
        uu=up[up["POS Payment"].astype(str).str.upper()==p] if not up.empty and "POS Payment" in up.columns else pd.DataFrame()
        settled=int(mm["Bank Settled"].fillna(False).astype(bool).sum()) if not mm.empty and "Bank Settled" in mm.columns else 0
        total=len(mm)
        delay=pd.to_numeric(mm.get("Settlement Delay Days",pd.Series(dtype=float)),errors="coerce").dropna()
        rows.append({
            "Provider / Payment":p,
            "Matched Transactions":total,
            "Bank Settled":settled,
            "Awaiting Bank":max(total-settled,0),
            "Provider-side Exceptions":len(uu),
            "Average Settlement Delay Days":round(float(delay.mean()),2) if not delay.empty else np.nan,
            "Commission":float(pd.to_numeric(mm.get("Commission",0),errors="coerce").fillna(0).sum()) if not mm.empty else 0.0,
            "VAT":float(pd.to_numeric(mm.get("VAT",0),errors="coerce").fillna(0).sum()) if not mm.empty else 0.0,
        })
    table=pd.DataFrame(rows)
    if table.empty:
        return {"text":"No provider/payment performance data is available in the current reconciliation.","table":table}
    worst=table.sort_values(["Awaiting Bank","Provider-side Exceptions"],ascending=False).iloc[0]
    text=(
        f"Provider/payment performance is based on the active reconciliation. "
        f"**{worst['Provider / Payment']}** currently has the largest open workload with "
        f"**{int(worst['Awaiting Bank'])}** awaiting-bank item(s) and "
        f"**{int(worst['Provider-side Exceptions'])}** provider-side exception(s)."
    )
    return {"text":text,"table":table.sort_values(["Awaiting Bank","Provider-side Exceptions"],ascending=False)}



def _fc_num(df, cols, absolute=False):
    if df is None or df.empty: return 0.0
    for c in cols:
        if c in df.columns:
            s=pd.to_numeric(df[c],errors="coerce").fillna(0)
            return float(s.abs().sum() if absolute else s.sum())
    return 0.0

def _fc_date_series(df, candidates):
    if df is None or df.empty:return pd.Series(dtype="datetime64[ns]")
    for c in candidates:
        if c in df.columns:return pd.to_datetime(df[c],errors="coerce")
    return pd.Series(pd.NaT,index=df.index)

def _fc_source_answer(result,ctx,db_module=None):
    frames=[
        ("D365 Store Tender",_filter_tender(result.get("tender",pd.DataFrame()),ctx)),
        ("Matched Reconciliation",_filter_recon(result.get("matched",pd.DataFrame()),ctx)),
        ("D365 Missing POS/Provider",_filter_recon(result.get("unmatched_sales",pd.DataFrame()),ctx)),
        ("POS/Provider Missing D365",_filter_recon(result.get("unmatched_pos",pd.DataFrame()),ctx,date_col="POS Date")),
    ]
    rows=[]
    for label,df in frames:
        if df is None or df.empty: continue
        sources=[]
        if "Source" in df.columns:sources=[x for x in df["Source"].dropna().astype(str).unique() if x.strip()]
        rows.append({"Data Source":label,"Rows":len(df),"Source Files":" | ".join(sources[:20])})
    tab=pd.DataFrame(rows)
    return {"text":f"These are the active evidence sources for **{_scope_text(ctx)}**. I only use data loaded in RetailRecon AI and do not invent missing source evidence.","table":tab}

def _fc_data_quality(result,ctx,db_module=None):
    tender=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    pos=result.get("pos",pd.DataFrame()).copy()
    issues=[]
    def add(name,count,detail):
        if count: issues.append({"Control":name,"Issue Count":int(count),"Action":detail})
    if not tender.empty:
        if "Auth Code" in tender.columns:
            a=tender["Auth Code"].astype(str).str.strip()
            add("Duplicate D365 Auth Code",int(a[a.ne("")].duplicated(keep=False).sum()),"Review duplicated authorization references before close.")
        d=_fc_date_series(tender,["Date"])
        add("Missing D365 Date",int(d.isna().sum()),"Correct/validate Store Tender transaction date.")
    if pos is not None and not pos.empty:
        if "Auth Code" in pos.columns:
            a=pos["Auth Code"].astype(str).str.strip()
            add("Duplicate POS/Provider Auth Code",int(a[a.ne("")].duplicated(keep=False).sum()),"Validate whether these are genuine repeated transactions or duplicate uploads.")
        d=_fc_date_series(pos,["POS Date","Date"])
        add("Missing Provider/POS Date",int(d.isna().sum()),"Validate provider transaction-date mapping.")
        for c,label in [("POS Store","Unmapped Store"),("Terminal ID","Missing Terminal ID"),("Merchant ID","Missing Merchant ID")]:
            if c in pos.columns:add(label,int(pos[c].fillna("").astype(str).str.strip().isin(["","nan","None"]).sum()),"Complete master-data mapping.")
    tab=pd.DataFrame(issues)
    if tab.empty:return {"text":f"I found no obvious upload/data-quality issues for **{_scope_text(ctx)}** in the active data.","table":tab}
    return {"text":f"I found **{int(tab['Issue Count'].sum()):,}** data-quality/control flags across **{len(tab)}** control type(s). Review these before final close or D365 posting.","table":tab}

def _fc_settlement(result,ctx,db_module=None):
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    if m.empty:return {"text":f"I don't have matched settlement data for **{_scope_text(ctx)}**.","table":pd.DataFrame()}
    settled=m[m["Bank Settled"].fillna(False).astype(bool)] if "Bank Settled" in m.columns else pd.DataFrame()
    openx=m[~m["Bank Settled"].fillna(False).astype(bool)] if "Bank Settled" in m.columns else m
    sa=_fc_num(settled,["Net Amount","D365 Amount","Sales Amount"],True)
    oa=_fc_num(openx,["Net Amount","D365 Amount","Sales Amount"],True)
    delay=pd.to_numeric(m.get("Settlement Delay Days",pd.Series(dtype=float)),errors="coerce")
    tab=pd.DataFrame([
      {"Status":"Bank Settled","Amount":sa,"Transactions":len(settled)},
      {"Status":"Awaiting Bank","Amount":oa,"Transactions":len(openx)},
    ])
    avg=float(delay.mean()) if not delay.dropna().empty else None
    oldest=""
    if not openx.empty:
        ds=_fc_date_series(openx,["Posting Date","POS Date","Date"])
        if ds.notna().any(): oldest=_fmt_date(ds.min())
    text=f"For **{_scope_text(ctx)}**, bank-settled amount is **{_fmt_sar(sa)}** ({len(settled):,} transactions) and **{_fmt_sar(oa)}** ({len(openx):,}) is awaiting bank verification."
    if avg is not None:text+=f" Average settlement delay is **{avg:.2f} day(s)**."
    if oldest:text+=f" Oldest currently open transaction date is **{oldest}**."
    return {"text":text,"table":tab}

def _fc_commission(result,ctx,db_module=None):
    m=_filter_recon(result.get("matched",pd.DataFrame()),ctx)
    if m.empty:return {"text":f"I don't have matched commission data for **{_scope_text(ctx)}**.","table":pd.DataFrame()}
    comm=_fc_num(m,["Commission"],True); vat=_fc_num(m,["VAT"],True)
    cols=[c for c in ["Store Code","Payment Type","Commission","VAT","D365 Amount","Net Amount"] if c in m.columns]
    tab=m[cols].copy() if cols else pd.DataFrame()
    if "Store Code" in tab.columns:tab=_add_store_name_column(tab,db_module,"Store Code")
    return {"text":f"For **{_scope_text(ctx)}**, recorded commission is **{_fmt_sar(comm)}** and VAT on commission is **{_fmt_sar(vat)}**. Expected-vs-actual rate validation is shown only where the active reconciliation contains sufficient rate/configuration data.","table":tab.head(500)}

def _fc_refunds(result,ctx,db_module=None):
    tender=_filter_tender(result.get("tender",pd.DataFrame()),ctx)
    if tender.empty:return {"text":f"I don't have D365 tender data for **{_scope_text(ctx)}**.","table":pd.DataFrame()}
    x=tender.copy(); x["D365 Amount"]=pd.to_numeric(x.get("D365 Amount",0),errors="coerce").fillna(0)
    r=x[x["D365 Amount"]<0].copy()
    amt=float(r["D365 Amount"].sum()); gross=float(x.loc[x["D365 Amount"]>0,"D365 Amount"].sum())
    ratio=(abs(amt)/gross*100) if gross else 0
    if "Store Code" in r.columns:r=_add_store_name_column(r,db_module,"Store Code")
    cols=[c for c in ["Store Code","Store Name","Date","Receipt ID","Auth Code","D365 Payment","D365 Amount"] if c in r.columns]
    return {"text":f"For **{_scope_text(ctx)}**, refunds/negative tenders total **{_fmt_sar(amt)}** across **{len(r):,}** transaction line(s). Refund-to-positive-sales ratio is **{ratio:.2f}%**.","table":r[cols].sort_values("D365 Amount").head(500) if cols else r.head(500)}

def _fc_jv(result,ctx,db_module=None):
    if db_module is None or not hasattr(db_module,"load_jv_batches"):
        return {"text":"I don't have access to JV batch status in this session.","table":pd.DataFrame()}
    try:jv=db_module.load_jv_batches()
    except Exception:return {"text":"I couldn't read the JV batch status from the application database.","table":pd.DataFrame()}
    if jv is None or jv.empty:return {"text":"No JV batches are currently available.","table":pd.DataFrame()}
    x=jv.copy()
    if ctx.store_codes and "Store Code" in x.columns:x=x[x["Store Code"].map(_norm_store).isin(ctx.store_codes)]
    status_col="D365 Status" if "D365 Status" in x.columns else ("Status" if "Status" in x.columns else None)
    if status_col:
        tab=x.groupby(x[status_col].fillna("UNKNOWN").astype(str),dropna=False).size().reset_index(name="Batches").rename(columns={status_col:"JV Status"})
    else:tab=pd.DataFrame([{"JV Status":"Available","Batches":len(x)}])
    return {"text":f"I found **{len(x):,} JV batch(es)** for **{_scope_text(ctx)}**. The table shows the current workflow/posting status from the application database.","table":tab}

def _fc_close_readiness(result,ctx,db_module=None):
    risk=_risk_answer(result,ctx,"what needs attention",db_module)
    blockers=risk.get("table",pd.DataFrame())
    reasons=[]
    if blockers is not None and not blockers.empty: reasons.append(f"{len(blockers):,} open reconciliation/settlement risk item(s)")
    if db_module is not None and hasattr(db_module,"load_corrections"):
        try:
            c=db_module.load_corrections()
            if c is not None and not c.empty and "Status" in c.columns:
                n=int(c["Status"].astype(str).str.upper().eq("PENDING").sum())
                if n:reasons.append(f"{n:,} pending correction(s)")
        except Exception:pass
    ready=not reasons
    status="READY TO CLOSE" if ready else "NOT READY"
    text=f"**{status}** for **{_scope_text(ctx)}**."
    if reasons:text+=" Blockers: "+"; ".join(reasons)+"."
    else:text+=" I found no blocker in the reconciliation, settlement-risk and pending-correction checks available to the Copilot."
    return {"text":text,"table":blockers.head(100) if blockers is not None else pd.DataFrame()}

def _fc_management_brief(result,ctx,db_module=None):
    sales=_sales_answer(result,ctx,False,db_module)
    recon=_reconciliation_status_answer(result,ctx,"matched and unmatched",db_module)
    risk=_risk_answer(result,ctx,"top 10 risks",db_module)
    settle=_fc_settlement(result,ctx,db_module)
    text="**Finance Control Briefing**\n\n"+sales["text"]+"\n\n"+recon["text"]+"\n\n"+settle["text"]+"\n\n"+risk["text"]
    return {"text":text,"table":risk.get("table",pd.DataFrame())}

def _fc_help():
    groups=[
      ("Sales & Cash","sales by store/date/payment, rankings, refunds, cash sales/refunds, payment mix"),
      ("Reconciliation","matched/unmatched, missing POS, missing D365, match rate, exception drill-down"),
      ("Settlement","bank settled, awaiting bank, settlement delay, oldest outstanding"),
      ("Providers","provider/payment performance, Tabby/Tamara/Tap/card exceptions"),
      ("Controls","commission/VAT, refunds, data quality, duplicates, mappings, risk priorities"),
      ("Close & JV","close readiness, pending corrections, JV workflow/posting status"),
      ("Management","finance briefing, what needs attention, store performance, provider performance"),
      ("Evidence","source files and active data sources used for the answer"),
    ]
    return {"text":"I can answer application-grounded Finance Control questions across sales, reconciliation, settlement, providers, controls, close/JV and management reporting. I will say when the active application does not contain enough data.","table":pd.DataFrame(groups,columns=["Area","Examples"])}


def _gl_control_answer(result,ctx,question=""):
    trace=result.get("gl_source_trace",pd.DataFrame()) if result else pd.DataFrame()
    jv=result.get("gl_jv_verification",pd.DataFrame()) if result else pd.DataFrame()
    exc=result.get("gl_exceptions",pd.DataFrame()) if result else pd.DataFrame()
    clearing=result.get("gl_clearing_control",pd.DataFrame()) if result else pd.DataFrame()
    ql=str(question or "").lower()

    if trace.empty and jv.empty and exc.empty and clearing.empty:
        return {
            "text":"I don't have an active D365 GL Control result yet. Open **D365 GL Reconciliation**, upload the General Journal Account Entry files and run the GL control first.",
            "table":pd.DataFrame()
        }

    def scoped(df,store_col="Store Code"):
        if df is None or df.empty:return pd.DataFrame()
        x=df.copy()
        if ctx.store_codes and store_col in x.columns:
            x=x[x[store_col].map(_norm_store).isin(ctx.store_codes)]
        return x

    trace=scoped(trace)
    jv=scoped(jv)
    exc=scoped(exc)
    clearing=scoped(clearing)

    if "exception" in ql or "mismatch" in ql or "not found" in ql or "unexplained" in ql:
        amount=float(pd.to_numeric(exc.get("Amount",0),errors="coerce").fillna(0).sum()) if not exc.empty else 0
        return {
            "text":f"For **{_scope_text(ctx)}**, I found **{len(exc):,} D365 GL control exception(s)** with gross reviewed exposure of **{_fmt_sar(amount)}**.",
            "table":exc.head(500)
        }

    if "balance" in ql or "movement" in ql or "clearing" in ql:
        net=float(pd.to_numeric(clearing.get("Net GL Movement",0),errors="coerce").fillna(0).sum()) if not clearing.empty else 0
        return {
            "text":f"For **{_scope_text(ctx)}**, the uploaded D365 clearing extracts show net signed GL movement of **{_fmt_sar(net)}**. This is a movement control, not a certified closing balance unless the uploaded population is complete.",
            "table":clearing.head(500)
        }

    sm=int((trace.get("GL Trace Status",pd.Series(dtype=str))=="GL MATCHED").sum()) if not trace.empty else 0
    sx=len(trace)
    jm=int((jv.get("GL Verification Status",pd.Series(dtype=str))=="GL MATCHED").sum()) if not jv.empty else 0
    jx=len(jv)
    text=(
        f"D365 GL control for **{_scope_text(ctx)}**: Source → GL **{sm:,}/{sx:,} matched**; "
        f"JV → GL **{jm:,}/{jx:,} matched**; **{len(exc):,} GL exception(s)** remain."
    )
    if len(exc)==0 and (sx==0 or sm==sx) and (jx==0 or jm==jx):
        text+=" Current uploaded scope is **D365 GL VERIFIED**."
    else:
        text+=" Status is **GL REVIEW REQUIRED**."
    return {"text":text,"table":exc.head(100) if not exc.empty else trace.head(100)}



def _settlement_batch_answer(result,ctx,question=""):
    batches=result.get("settlement_batches",pd.DataFrame()) if result else pd.DataFrame()
    matched=result.get("matched",pd.DataFrame()) if result else pd.DataFrame()

    if batches.empty:
        return {
            "text":"I don't have an active Settlement Batch Engine result yet. Open **Settlement Batch Engine**, upload payout/bank evidence and run settlement control first.",
            "table":pd.DataFrame()
        }

    x=batches.copy()
    if ctx.store_codes and "Store Code" in x.columns:
        x=x[x["Store Code"].map(_norm_store).isin(ctx.store_codes)]
    ql=str(question or "").lower()

    if "pending" in ql or "not received" in ql:
        y=x[x["Settlement Status"]!="BANK RECEIVED"].copy()
        amt=float(pd.to_numeric(y.get("Expected Bank Amount",0),errors="coerce").fillna(0).sum()) if not y.empty else 0
        return {
            "text":f"For **{_scope_text(ctx)}**, **{len(y):,} settlement batch(es)** are not yet verified as BANK RECEIVED, representing expected receipts of **{_fmt_sar(amt)}**.",
            "table":y.head(500)
        }

    received=x[x["Settlement Status"]=="BANK RECEIVED"].copy()
    expected=float(pd.to_numeric(x.get("Expected Bank Amount",0),errors="coerce").fillna(0).sum())
    actual=float(pd.to_numeric(received.get("Actual Bank Amount",0),errors="coerce").fillna(0).sum()) if not received.empty else 0
    return {
        "text":(
            f"Settlement Batch Engine for **{_scope_text(ctx)}**: **{len(received):,}/{len(x):,} batch(es)** are BANK RECEIVED. "
            f"Expected settlement population is **{_fmt_sar(expected)}** and verified bank receipts total **{_fmt_sar(actual)}**."
        ),
        "table":x.head(500)
    }


def answer_question(question, result, db_module=None, prior_context=None, user_context=None):
    if not result:
        return {
            "text":"I don't have an active reconciliation yet. Please run POS Reconciliation first; then I can answer questions about sales, cash, MADA/Visa/Mastercard, providers, exceptions, bank settlement, commission, corrections and JV status.",
            "table":pd.DataFrame(),
            "context":prior_context or CopilotContext(),
            "intent":"no_data",
        }

    result=_apply_user_scope(result,user_context)
    allowed_stores=_allowed_store_codes(user_context)
    intent,ctx=interpret_query(question,result,prior_context,db_module)
    ql=question.lower()

    if intent=="greeting":
        payload={"text":"Good morning. I can help with the active RetailRecon data — ask me about a store, date, payment type, settlement, exceptions, commission, refunds, corrections or JV/D365 status.","table":pd.DataFrame()}
    elif intent=="cash_report":
        # Cash questions use a dedicated D365 Store Tender finance report.
        ctx.payment="CASH"
        payload=_cash_report(result,ctx,question,db_module)
    elif intent=="close_readiness":
        payload=_fc_close_readiness(result,ctx,db_module)
    elif intent=="management_brief":
        payload=_fc_management_brief(result,ctx,db_module)
    elif intent=="settlement_intelligence":
        payload=_fc_settlement(result,ctx,db_module)
    elif intent=="commission_intelligence":
        payload=_fc_commission(result,ctx,db_module)
    elif intent=="refund_intelligence":
        payload=_fc_refunds(result,ctx,db_module)
    elif intent=="data_quality":
        payload=_fc_data_quality(result,ctx,db_module)
    elif intent=="source_evidence":
        payload=_fc_source_answer(result,ctx,db_module)
    elif intent=="copilot_help":
        payload=_fc_help()
    elif intent=="reconciliation_status":
        payload=_reconciliation_status_answer(result,ctx,question,db_module)
    elif intent=="sales":
        # A CASH-scoped "sales" question is a cash query and must always go
        # through the Advanced Cash Report, never the generic tender-total
        # line ("CASH total is SAR X across Y transaction line(s)").
        if ctx.payment=="CASH":
            payload=_cash_report(result,ctx,question,db_module)
        else:
            payload=_sales_answer(result,ctx,detail=False,db_module=db_module)
    elif intent=="date_range":
        payload=_date_range_answer(result,ctx)
    elif intent=="transactions":
        if ctx.payment=="CASH":
            payload=_cash_report(result,ctx,question,db_module)
        else:
            payload=_sales_answer(result,ctx,detail=True,db_module=db_module)
    elif intent=="settlement_batch":
        payload=_settlement_batch_answer(result,ctx,question)
    elif intent=="gl_control":
        payload=_gl_control_answer(result,ctx,question)
    elif intent=="risk":
        payload=_risk_answer(result,ctx,question,db_module)
    elif intent=="store_performance":
        payload=_store_performance_answer(result,ctx,db_module)
    elif intent=="provider_performance":
        payload=_provider_performance_answer(result,ctx)
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
        payload=_compare_answer(result,ctx,question,db_module)
    elif intent=="corrections":
        # correction_log has no per-store column, so it cannot be safely
        # scoped to a Store User's assigned store(s) - block rather than leak.
        if allowed_stores:
            payload={"text":"Correction requests span all stores and aren't available in a store-scoped view.","table":pd.DataFrame()}
        elif db_module is None:
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
            if allowed_stores:
                # JV rows carry Store Code, so this can be scoped safely.
                df=_restrict_df_to_stores(df,allowed_stores)
            if df.empty:
                payload={"text":"No JV batches are currently stored.","table":df}
            else:
                approved=int(df.get("Approval Status",pd.Series(dtype=str)).astype(str).str.upper().eq("APPROVED").sum()) if "Approval Status" in df.columns else 0
                posted=int(df.get("Posted",pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if "Posted" in df.columns else 0
                payload={"text":f"I found **{len(df):,} JV row(s)** in the control table; **{approved:,}** are approved and **{posted:,}** are marked posted.","table":df.head(500)}
    elif intent=="close":
        # Close calendar is a firm-wide finance control, not store-specific.
        if allowed_stores:
            payload={"text":"The close calendar is a firm-wide finance control and isn't available in a store-scoped view.","table":pd.DataFrame()}
        elif db_module is None:
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
        # Same rule for the generic/summary fallback: a CASH-scoped summary
        # request must render the Advanced Cash Report, not the old
        # generic-sales-derived summary text.
        if ctx.payment=="CASH":
            payload=_cash_report(result,ctx,question,db_module)
        else:
            payload=_summary_answer(result,ctx,db_module)

    payload["context"]=ctx
    payload["intent"]=intent
    return payload

from __future__ import annotations
import csv
import io, re, json, hashlib
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

TOLERANCE = 1.00
PAYMENTS = ["MADA","VISA","MASTERCARD","AMEX","TABBY","TAMARA","TAP","FLOOSS","PAYLATER","DEEMA"]

STORE_MAP = {
    # Aigner provider / payment-link mappings
    "AIGNER - KINGDOM TOWER BRANCH 3, PAYMENT LINKS":"643",
    "AIGNER - FAISALIAH MALL, PAYMENT LINKS":"602",
    "AIGNER NAKHEEL MALL":"644",
    "AIGNER - HAYAT MALL, PAYMENT LINKS":"624",
    "AIGNER - TAHLIA CENTER, PAYMENT LINKS":"601",
    "AIGNER - RED SEA MALL, PAYMENT LINKS":"603",
    "AIGNER - MALL OF ARABIA BRANCH 1, PAYMENT LINKS":"619",
    "AIGNER - RIYADH PARK, PAYMENT LINKS":"606",
    "AIGNER - RASHID MALL, PAYMENT LINKS":"609",
    "AIGNER SOLITAIRE MALL":"634",
    "AIGNER KSA - ONLINE":"613",

    # Existing normalized aliases
    "AIGNER KSA":"613",
    "AIGNER TAHLIA":"601",
    "AIGNER RIYADH PARK":"606",
    "AIGNER RASHID MALL":"609",
    "AIGNER SOLITAIRE":"634",

    # Other existing store mappings
    "TAG HEUER RED SEA":"614",
    "TAG HEUER RIYADH PARK":"615",
    "TAG HEUER SOLITAIRE":"629",
    "FRED SOLITAIRE":"630",
    "PIAGET SOLITAIRE":"649",
    "PANERAI SOLITAIRE":"650",
    "IWC SOLITAIRE":"651",
    "JLC SOLITAIRE":"652",

    # Aliases seen in the Tamara/Tabby "branch_name" export format
    # (United_Luxury_Corpoation_*.xlsx) - same physical stores, different wording
    # than the ", PAYMENT LINKS" labels above.
    "AIGNER - RED SEA MALL":"603",
    "AIGNER - MALL OF ARABIA":"619",
    "AIGNER - RIYADH PARK":"606",
    "AIGNER - NAKHEEL MALL":"644",
    "AIGNER - RASHID MALL":"609",
    "AIGNER - FAISALIAH":"602",
    "AIGNER - KINGDOM TOWER":"643",
    "AIGNER - HAYAT MALL":"624",
    "AIGNER - SOLITAIRE MALL":"634",
    "AIGNER - TAHLIA MALL":"601",
    "TAG HEUER - RED SEA MALL":"614",
    "TAG HEUER - RIYADH PARK":"615",
    "FRED - SOLITAIRE MALL":"630",

    # Additional store aliases confirmed by Finance
    "OPTIONS AL ANDALUS MALL":"658",
    "TAG HEUER - RED SEA MALL BRANCH 1, PAYMENT LINKS":"614",
    "TAG HEUER RASHID MALL, PAYMENT LINKS":"629",
}

GL_DEFAULTS = {
    "BANK":"1010","COMMISSION":"7231","VAT":"11020907","AMEX":"11020901",
    "SALES_CLEARING_CARD":"11020920","SALES_CLEARING_AMEX":"11020921",
    "SALES_CLEARING_TABBY":"11020922","SALES_CLEARING_TAMARA":"11020923","SALES_CLEARING_TAP":"11020924"
}

def ccol(v):
    return re.sub(r"[^A-Z0-9]+","_",str(v).strip().upper()).strip("_")

def norm_cols(df):
    d=df.copy()
    d.columns=[ccol(c) for c in d.columns]
    return d

def amount(v):
    if pd.isna(v): return np.nan
    if isinstance(v,(int,float,np.number)): return round(float(v),2)
    s=str(v).replace(",","").replace("SAR","").replace("ر.س","").strip()
    s=re.sub(r"[^\d\.\-\(\)]","",s)
    if s.startswith("(") and s.endswith(")"): s="-"+s[1:-1]
    try:return round(float(s),2)
    except:return np.nan

def auth(v):
    if pd.isna(v): return ""
    s=re.sub(r"[^A-Z0-9]","",str(v).strip().upper())
    if s.isdigit() and len(s)<6:s=s.zfill(6)
    return s

def provider_ref_key(v):
    """
    Matching-only canonical reference for TABBY/TAMARA.
    Numeric leading zeros are ignored for comparison only.
    Original D365/provider reference remains unchanged for audit/display.
    """
    s=auth(v)
    if not s:
        return ""
    if s.isdigit():
        x=s.lstrip("0")
        return x if x else "0"
    return s

def dt(v):
    """
    Parse RetailRecon source dates safely.

    Actual D365/POS/provider exports use examples such as:
      8/1/2026  -> 01-Aug-2026
      8/9/2026  -> 09-Aug-2026
      7/4/2026  -> 04-Jul-2026

    Therefore ambiguous slash dates are treated as M/D/YYYY unless the first
    component is >12 (which makes D/M/YYYY unambiguous). ISO and Excel dates
    are also supported.
    """
    if v is None or (isinstance(v,float) and pd.isna(v)):
        return pd.NaT

    # Already a real date/datetime/Timestamp.
    if isinstance(v,(pd.Timestamp,datetime)):
        return pd.to_datetime(v,errors="coerce")

    # Excel serial date.
    if isinstance(v,(int,float,np.integer,np.floating)) and not isinstance(v,bool):
        fv=float(v)
        if 20000 <= fv <= 80000:
            try:
                return pd.Timestamp("1899-12-30") + pd.to_timedelta(fv,unit="D")
            except Exception:
                pass

    s=str(v).strip()
    if not s or s.lower() in {"nan","nat","none","null"}:
        return pd.NaT

    # ISO YYYY-MM-DD / YYYY/MM/DD
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}",s):
        return pd.to_datetime(s,errors="coerce",yearfirst=True)

    # Numeric slash dates. User's real D365/POS/provider exports are M/D/YYYY.
    m=re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+.*)?$",s)
    if m:
        a,b,_=map(int,m.groups())
        if a>12 and b<=12:
            return pd.to_datetime(s,errors="coerce",dayfirst=True)
        return pd.to_datetime(s,errors="coerce",dayfirst=False)

    # Text month dates / other unambiguous forms.
    return pd.to_datetime(s,errors="coerce")


def parse_provider_date(v, source_file="", provider_hint=""):
    """
    Provider-aware date parser.

    TAP charge exports are resolved against the date range embedded in the
    source filename, e.g. 260801_to_260809 = 01-Aug-2026 to 09-Aug-2026.
    """
    src=str(source_file or "")
    hint=str(provider_hint or "").upper()
    is_tap=("CHARGE_" in src.upper()) or ("TAP" in hint)

    if not is_tap:
        return dt(v)

    if isinstance(v,(pd.Timestamp,datetime)):
        return pd.to_datetime(v,errors="coerce")

    if isinstance(v,(int,float,np.integer,np.floating)) and not isinstance(v,bool):
        fv=float(v)
        if 20000 <= fv <= 80000:
            try:
                return pd.Timestamp("1899-12-30") + pd.to_timedelta(fv,unit="D")
            except Exception:
                pass

    s="" if v is None else str(v).strip()
    if not s or s.lower() in {"nan","nat","none","null"}:
        return pd.NaT

    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}",s):
        return pd.to_datetime(s,errors="coerce",yearfirst=True)

    pm=re.search(r"(\d{6})_to_(\d{6})",src,re.I)
    start=end=None
    if pm:
        try:
            start=pd.to_datetime(pm.group(1),format="%y%m%d")
            end=pd.to_datetime(pm.group(2),format="%y%m%d")
        except Exception:
            start=end=None

    if re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{4}",s):
        cands=[]
        for dayfirst in (True,False):
            try:
                d=pd.to_datetime(s,errors="coerce",dayfirst=dayfirst)
                if pd.notna(d):
                    cands.append(d.normalize())
            except Exception:
                pass
        if start is not None and end is not None:
            inside=[d for d in cands if start.normalize() <= d <= end.normalize()]
            if inside:
                return inside[0]
        return pd.to_datetime(s,errors="coerce",dayfirst=True)

    return pd.to_datetime(s,errors="coerce",dayfirst=True)


def find(df,names):
    for n in names:
        n=ccol(n)
        if n in df.columns:return n
    return None

def _header_score(values):
    tokens=[ccol(v) for v in values if pd.notna(v) and str(v).strip()]
    joined="|".join(tokens)
    keys=[
        "STORE","TRANSDATE","TRANSACTION_DATE","RECEIPTID","RECEIPT_ID","AUTH_CODE",
        "MERCHANT_ID","RETAILER_POS_ACCOUNT","TERMINAL_ID","TRANSACTION_AMOUNT",
        "TRANS_APPROVAL_CD","PAYMENT_ID","CAPTURED_AMOUNT","AUTHORIZATION_ID",
        "ORDER_REFERENCE_ID","LOCALDATE","TR_ARF"
    ]
    return sum(1 for k in keys if k in tokens or k in joined)

def _best_header_row(raw, max_rows=20):
    best_row=0
    best_score=-1
    limit=min(max_rows,len(raw))
    for i in range(limit):
        score=_header_score(raw.iloc[i].tolist())
        nonempty=sum(pd.notna(v) and str(v).strip()!="" for v in raw.iloc[i].tolist())
        # Prefer rows containing recognizable business fields; nonempty count breaks ties.
        rank=score*100+min(nonempty,50)
        if rank>best_score:
            best_score=rank
            best_row=i
    return best_row

def read_upload(file):
    """Robust reader for XLSX/XLS/CSV/TXT with auto header and delimiter detection."""
    name=getattr(file,"name","upload")
    ext=Path(name).suffix.lower()
    data=file.getvalue() if hasattr(file,"getvalue") else file.read()

    def score(row):
        vals=[str(x).strip() for x in row if str(x).strip() not in ("","nan","None")]
        if not vals:return -1
        text=" ".join(vals).lower()
        keys=("terminal","merchant","store","date","amount","auth","receipt","payment",
              "posting","net","commission","vat","payout","transaction","reference",
              "account","credit","debit","value","sales")
        return len(vals)+sum(k in text for k in keys)*4

    def find_header(rows):
        scores=[score(r) for r in rows[:25]]
        return max(range(len(scores)),key=lambda i:scores[i]) if scores else 0

    def safe_headers(headers):
        seen={};out=[]
        for i,h in enumerate(headers):
            base=str(h).strip()
            if not base or base.lower() in ("nan","none"): base=f"Unnamed_{i+1}"
            n=seen.get(base,0);seen[base]=n+1
            out.append(base if n==0 else f"{base}_{n+1}")
        return out

    if ext in (".xlsx",".xls"):
        engine="openpyxl" if ext==".xlsx" else None
        xl=pd.ExcelFile(io.BytesIO(data),engine=engine)
        result={}
        for sheet in xl.sheet_names:
            raw=pd.read_excel(io.BytesIO(data),sheet_name=sheet,header=None,engine=engine)
            if raw.empty:
                result[sheet]=raw;continue
            rows=raw.astype(object).where(pd.notna(raw),"").values.tolist()
            hdr=find_header(rows);width=max(len(r) for r in rows)
            rows=[list(r)+[""]*(width-len(r)) for r in rows]
            df=pd.DataFrame(rows[hdr+1:],columns=safe_headers(rows[hdr]))
            df=df.replace("",np.nan).dropna(how="all").dropna(axis=1,how="all").reset_index(drop=True)
            result[sheet]=df
        return result

    text=None
    for enc in ("utf-8-sig","utf-8","cp1252","latin1"):
        try:text=data.decode(enc);break
        except Exception:pass
    if text is None:text=data.decode("utf-8",errors="replace")
    lines=[ln for ln in text.splitlines() if ln.strip()]
    if not lines:return {"Sheet1":pd.DataFrame()}

    sample="\n".join(lines[:30]);seps=[",",";","\t","|"]
    try:
        sep=csv.Sniffer().sniff(sample,delimiters=seps).delimiter
    except Exception:
        scores={}
        for s in seps:
            widths=[]
            for ln in lines[:30]:
                try:widths.append(len(next(csv.reader([ln],delimiter=s))))
                except Exception:widths.append(1)
            multi=[w for w in widths if w>1]
            scores[s]=(len(multi),-(max(multi)-min(multi)) if multi else -999,sum(multi))
        sep=max(scores,key=scores.get)

    rows=list(csv.reader(io.StringIO(text),delimiter=sep))
    rows=[r for r in rows if any(str(x).strip() for x in r)]
    hdr=find_header(rows);width=max(len(r) for r in rows)
    rows=[list(r)+[""]*(width-len(r)) for r in rows]
    df=pd.DataFrame(rows[hdr+1:],columns=safe_headers(rows[hdr]))
    df=df.replace("",np.nan).dropna(how="all").dropna(axis=1,how="all").reset_index(drop=True)
    return {"Sheet1":df}

def provider_signature(name,df):
    n=name.lower()
    if "tabby" in n:return "TABBY"
    if "tamara" in n:return "TAMARA"
    if re.search(r"(^|[^a-z])tap([^a-z]|$)",n):return "TAP"
    if "amex" in n:return "AMEX"
    cols={ccol(c) for c in df.columns}
    if len(cols & {ccol(x) for x in ["Payment ID","Captured amount","Refunded amount","MID","RRN"]})>=3:return "TABBY"
    if len(cols & {ccol(x) for x in ["order_reference_id","instalments","settlement_status","canceled_amount","branch_name"]})>=3:return "TAMARA"
    return None

def classify(name,df):
    p=provider_signature(name,df)
    if p:return p

    d=norm_cols(df)

    # D365 Sales Details: used as a controlled bridge for Store 613.
    # Must be detected before Store Tender because some Sales Details exports
    # can also carry Receipt ID / Auth-like reference columns.
    sd_store=find(d,["store id","store","store code"])
    sd_sales_order=find(d,["sales order","salesorder","sales order no","sales order number"])
    sd_receipt=find(d,["receipt id","receiptid","receipt"])
    sd_invoice=find(d,["invoice","invoice id","invoice number","invoice no"])
    if sd_store and sd_sales_order and sd_receipt and sd_invoice:
        return "D365 SALES DETAILS"

    # D365 Store Tender is identified by its business keys first.
    # Do NOT require payment columns to be detected before classifying it.
    has_store=find(d,["store","store code","store name"])
    has_date=find(d,["transdate","transaction date","sales date","date"])
    has_receipt=find(d,["receiptid","receipt id","receipt","receipt number","receipt no"])
    has_auth=find(d,[
        "auth code","authcode","authorization code","authorizationcode","auth","authorization","approval code",
        "trans approval cd","tr arf","tr_arf","authorization_id"
    ])
    has_terminal=find(d,["terminal id","tid","terminal"])

    if has_store and has_date and has_receipt and has_auth:
        return "D365 STORE TENDER"

    # Master/reference files
    if has_terminal and has_store and not has_auth:
        return "TERMINAL_MASTER"

    if has_store and any(
        "AMEX" in c or "TABBY" in c or "TAMARA" in c or "TAP" in c
        for c in d.columns
    ) and not has_auth:
        return "STORE_MASTER"

    # Provider/POS files normally have authorization/reference but not D365 receipt structure.
    if has_auth:
        return "POS"

    return "UNKNOWN"

def is_d365_summary_or_nontransaction(row, store_col=None, date_col=None, receipt_col=None, auth_col=None):
    """
    Detect D365 Store Tender total/summary rows that must not become fake transactions.
    A genuine transaction must at least carry usable transaction identity.
    Rows where Store + Date + Receipt are all blank/NaN are source control totals.
    """
    def _txt(c):
        if not c: return ""
        v=row.get(c)
        return "" if pd.isna(v) else str(v).strip()

    store=_txt(store_col)
    receipt=_txt(receipt_col)
    authv=auth(row.get(auth_col)) if auth_col else ""
    datev=dt(row.get(date_col)) if date_col else pd.NaT

    labels={"SUM","SUM:","TOTAL","TOTAL:","GRAND TOTAL","GRAND TOTAL:","SUBTOTAL","SUMMARY","CONTROL TOTAL"}

    if store.upper() in labels or receipt.upper() in labels:
        return True

    # Blank identifiers strongly indicate a grand-total/payment summary row.
    if (not store or store.lower()=="nan") and pd.isna(datev) and (not receipt or receipt.lower()=="nan"):
        return True

    # If everything identifying the transaction is absent, do not expand tender totals.
    if (not store or store.lower()=="nan") and pd.isna(datev) and not authv:
        return True

    return False

def normalize_tender(df):
    d=norm_cols(df)
    store=find(d,["store","store code"])
    date=find(d,["transdate","transaction date","date","sales date"])
    receipt=find(d,["receiptid","receipt id","receipt"])
    ac=find(d,["auth code","authcode","authorization code","authorizationcode","auth"])
    sales_order=find(d,["sales order","salesorder","sales order no","sales order number","order number","order no"])
    tender_reference=find(d,["payment reference","payment id","reference","transaction id","voucher","invoice"])
    if not all([store,date,receipt,ac]):raise ValueError("D365 Store Tender requires Store, Transdate, Receiptid and Auth Code.")
    rows=[]
    for i,r in d.iterrows():
        # D365 transaction-validity gate: source summary/control rows never become exceptions.
        if is_d365_summary_or_nontransaction(
            r, store_col=store, date_col=date, receipt_col=receipt, auth_col=ac
        ):
            continue

        s=str(r.get(store,"")).strip()
        sc=STORE_MAP.get(s.upper(),s)
        parsed_date=dt(r.get(date))
        raw_auth="" if pd.isna(r.get(ac)) else str(r.get(ac)).strip()
        base={
            "D365 Row":i+1,
            "Store Code":sc,
            "Date":parsed_date,
            "Receipt ID":str(r.get(receipt,"")).strip(),
            "Auth Code":auth(r.get(ac)),
            "D365 Raw Auth Code":raw_auth,
            "Sales Order":str(r.get(sales_order,"")).strip() if sales_order else "",
            "StoreTender Reference":str(r.get(tender_reference,"")).strip() if tender_reference else "",
            "SalesDetails Bridge Status":"",
            "SalesDetails Source":"",
        }
        found=False
        for c in d.columns:
            cu=c.upper(); p=None
            if "MADA" in cu or "KNET" in cu:p="MADA"
            elif "VISA" in cu:p="VISA"
            elif "MASTER" in cu:p="MASTERCARD"
            elif "AMEX" in cu:p="AMEX"
            elif "TABBY" in cu:p="TABBY"
            elif "TAMARA" in cu:p="TAMARA"
            elif cu=="TAP" or "TAP_" in cu or "_TAP" in cu:p="TAP"
            elif "FLOOSS" in cu:p="FLOOSS"
            elif "PAYLATER" in cu or "PAY_LATER" in cu:p="PAYLATER"
            elif "DEEMA" in cu:p="DEEMA"
            elif cu=="CASH" or cu.startswith("CASH ") or cu.endswith(" CASH"):
                p="CASH"
            if p:
                a=amount(r.get(c))
                if pd.notna(a) and abs(a)>0:
                    rr=base.copy()
                    rr["D365 Payment"]=p
                    rr["D365 Amount"]=a
                    if p=="CASH":
                        rr["Cash Classification"]="Cash Sales" if a>0 else "Cash Refund"
                        rr["Cash Amount"]=a
                    rows.append(rr)
                    found=True
        if not found:
            total=find(d,["total","sales amount"])
            if total:
                a=amount(r.get(total))
                if pd.notna(a) and abs(a)>0:
                    rr=base.copy();rr["D365 Payment"]="UNKNOWN";rr["D365 Amount"]=a;rows.append(rr)
    out=pd.DataFrame(rows)
    if out.empty:return out
    if "Narration" in out.columns:
        narr=out["Narration"].apply(parse_bank_narration).apply(pd.Series)
        out=pd.concat([out,narr],axis=1)
    if "Cash Classification" not in out.columns:
        out["Cash Classification"]=""
    else:
        out["Cash Classification"]=out["Cash Classification"].fillna("")
    if "Cash Amount" not in out.columns:
        out["Cash Amount"]=0.0
    else:
        out["Cash Amount"]=pd.to_numeric(out["Cash Amount"],errors="coerce").fillna(0.0)
    out["D365 Payment"]=out["D365 Payment"].apply(_norm_payment)
    out["D365 Match Key"]=out.apply(
        lambda r: f"{str(r['Store Code']).strip()}|"
                  f"{pd.to_datetime(r['Date'],errors='coerce').strftime('%Y-%m-%d') if pd.notna(pd.to_datetime(r['Date'],errors='coerce')) else ''}|"
                  f"{auth(r['Auth Code'])}|{_norm_payment(r['D365 Payment'])}|"
                  f"{float(r['D365 Amount']):.2f}",
        axis=1
    )
    # True D365 duplicate control:
    # Auth codes can legitimately repeat across different dates/receipts.
    # A row is only a duplicate when the business transaction identity repeats.
    _dup_cols=["Store Code","Date","Receipt ID","Auth Code","D365 Payment","D365 Amount"]
    out["D365 Duplicate"]=out.duplicated(_dup_cols,keep=False)
    out["Unique Transaction ID"]=out.apply(lambda r: hashlib.sha1(
        f"{r['Store Code']}|{r['Date']}|{r['Receipt ID']}|{r['Auth Code']}|{r['D365 Payment']}|{r['D365 Amount']}".encode()
    ).hexdigest()[:20],axis=1)
    return out


def normalize_sales_details(df, source="D365 Sales Details"):
    """
    Normalize D365 Sales Details for reconciliation support.

    Primary bridge key for Store 613:
        Store Code + Sales Order

    Receipt ID and Auth Code are evidence fields. They are never guessed:
    only a unique non-blank value is eligible to enrich StoreTender.
    """
    d=norm_cols(df)
    store=find(d,["store id","store","store code"])
    store_name=find(d,["store name","store"])
    sales_order=find(d,["sales order","salesorder","sales order no","sales order number"])
    receipt=find(d,["receipt id","receiptid","receipt"])
    invoice=find(d,["invoice","invoice id","invoice number","invoice no"])
    invoice_date=find(d,["invoice date","invoicedate","date"])
    ac=find(d,["auth code","authcode","authorization code","authorizationcode","authorization","approval code"])
    if not store or not sales_order or not receipt:
        raise ValueError("D365 Sales Details requires Store ID/Store, Sales Order and Receipt ID.")

    rows=[]
    for i,r in d.iterrows():
        raw_store="" if pd.isna(r.get(store)) else str(r.get(store)).strip()
        sc=STORE_MAP.get(raw_store.upper(),raw_store)
        so="" if pd.isna(r.get(sales_order)) else str(r.get(sales_order)).strip()
        rid="" if pd.isna(r.get(receipt)) else str(r.get(receipt)).strip()
        if not sc or not so:
            continue
        rows.append({
            "SalesDetails Row":i+1,
            "Store Code":sc,
            "Store Name":("" if not store_name or pd.isna(r.get(store_name)) else str(r.get(store_name)).strip()),
            "Sales Order":so,
            "Receipt ID":rid,
            "Auth Code":auth(r.get(ac)) if ac else "",
            "Invoice":("" if not invoice or pd.isna(r.get(invoice)) else str(r.get(invoice)).strip()),
            "Invoice Date":dt(r.get(invoice_date)) if invoice_date else pd.NaT,
            "SalesDetails Source":source,
        })
    return pd.DataFrame(rows)

def enrich_store613_from_sales_details(tender, sales_details):
    """
    Enrich Store 613 StoreTender rows with D365 SalesDetails.

    Rules:
      - Applies only to Store Code 613.
      - Match key is Store Code + Sales Order.
      - Fill Receipt ID only when SalesDetails has exactly one unique non-blank Receipt ID.
      - Fill Auth Code only when SalesDetails has exactly one unique non-blank Auth Code.
      - Never overwrite an existing StoreTender Receipt ID/Auth Code.
      - Ambiguous/missing SalesDetails mappings are explicitly flagged.
      - Recompute D365 duplicate / unique transaction controls after enrichment.
    """
    if tender is None or tender.empty:
        return tender, pd.DataFrame()
    out=tender.copy()
    for c,default in [
        ("Sales Order",""),("SalesDetails Bridge Status",""),
        ("SalesDetails Source",""),("Receipt ID",""),("Auth Code","")
    ]:
        if c not in out.columns:
            out[c]=default

    audit=[]
    if sales_details is None or sales_details.empty:
        mask=out["Store Code"].astype(str).str.strip().eq("613")
        out.loc[mask,"SalesDetails Bridge Status"]="SalesDetails Missing"
        return out, pd.DataFrame()

    sd=sales_details.copy()
    sd["Store Code"]=sd["Store Code"].astype(str).str.strip()
    sd["Sales Order"]=sd["Sales Order"].astype(str).str.strip()
    sd=sd[(sd["Store Code"]=="613") & sd["Sales Order"].ne("")].copy()

    grouped={}
    for so,g in sd.groupby("Sales Order",dropna=False):
        receipts=sorted({str(x).strip() for x in g.get("Receipt ID",pd.Series(dtype=str)).dropna() if str(x).strip()})
        auths=sorted({auth(x) for x in g.get("Auth Code",pd.Series(dtype=str)).dropna() if auth(x)})
        sources=sorted({str(x).strip() for x in g.get("SalesDetails Source",pd.Series(dtype=str)).dropna() if str(x).strip()})
        invoices=sorted({str(x).strip() for x in g.get("Invoice",pd.Series(dtype=str)).dropna() if str(x).strip()})
        grouped[str(so).strip()]={
            "receipts":receipts,"auths":auths,"sources":sources,"invoices":invoices,
            "rows":len(g)
        }

    for idx,r in out.iterrows():
        if str(r.get("Store Code","")).strip()!="613":
            continue
        so=str(r.get("Sales Order","")).strip()
        old_receipt=str(r.get("Receipt ID","")).strip()
        old_auth=auth(r.get("Auth Code",""))
        if not so:
            status="Sales Order Missing"
            out.at[idx,"SalesDetails Bridge Status"]=status
            audit.append({"D365 Row":r.get("D365 Row"),"Store Code":"613","Sales Order":"","Receipt ID":old_receipt,"Auth Code":old_auth,"Bridge Status":status})
            continue
        info=grouped.get(so)
        if not info:
            status="Sales Order Not Found in SalesDetails"
            out.at[idx,"SalesDetails Bridge Status"]=status
            audit.append({"D365 Row":r.get("D365 Row"),"Store Code":"613","Sales Order":so,"Receipt ID":old_receipt,"Auth Code":old_auth,"Bridge Status":status})
            continue

        receipts=info["receipts"]; auths=info["auths"]
        status_bits=[]
        if old_receipt:
            status_bits.append("Receipt Preserved")
        elif len(receipts)==1:
            out.at[idx,"Receipt ID"]=receipts[0]
            status_bits.append("Receipt Bridged")
        elif len(receipts)>1:
            status_bits.append("Ambiguous Receipt")
        else:
            status_bits.append("Receipt Missing")

        if old_auth:
            status_bits.append("Auth Preserved")
        elif len(auths)==1:
            out.at[idx,"Auth Code"]=auths[0]
            out.at[idx,"D365 Raw Auth Code"]=auths[0]
            status_bits.append("Auth Bridged")
        elif len(auths)>1:
            status_bits.append("Ambiguous Auth")
        else:
            status_bits.append("Auth Not Available")

        out.at[idx,"SalesDetails Source"]=" | ".join(info["sources"])
        status="; ".join(status_bits)
        out.at[idx,"SalesDetails Bridge Status"]=status
        audit.append({
            "D365 Row":r.get("D365 Row"),"Store Code":"613","Sales Order":so,
            "Receipt ID":out.at[idx,"Receipt ID"],"Auth Code":out.at[idx,"Auth Code"],
            "Bridge Status":status,"SalesDetails Rows":info["rows"],
            "Invoices":" | ".join(info["invoices"]),
            "SalesDetails Source":out.at[idx,"SalesDetails Source"],
        })

    # Recompute controls because identity fields may have changed.
    out["D365 Match Key"]=out.apply(
        lambda r: f"{str(r['Store Code']).strip()}|"
                  f"{pd.to_datetime(r['Date'],errors='coerce').strftime('%Y-%m-%d') if pd.notna(pd.to_datetime(r['Date'],errors='coerce')) else ''}|"
                  f"{auth(r['Auth Code'])}|{_norm_payment(r['D365 Payment'])}|"
                  f"{float(r['D365 Amount']):.2f}",
        axis=1
    )
    _dup_cols=["Store Code","Date","Receipt ID","Auth Code","D365 Payment","D365 Amount"]
    out["D365 Duplicate"]=out.duplicated(_dup_cols,keep=False)
    out["Unique Transaction ID"]=out.apply(lambda r: hashlib.sha1(
        f"{r['Store Code']}|{r['Date']}|{r['Receipt ID']}|{r['Auth Code']}|{r.get('Sales Order','')}|{r['D365 Payment']}|{r['D365 Amount']}".encode()
    ).hexdigest()[:20],axis=1)

    return out, pd.DataFrame(audit)


def is_pos_summary_or_nontransaction(row, terminal_col=None, auth_col=None, date_col=None, payment_col=None):
    """
    Detect statement summary/control/footer rows that must never enter
    transaction reconciliation.

    Typical ANB examples:
      Terminal ID = 'Sum:'
      Payment type/scheme = NaN
      no Auth/Reference
      no transaction date
      large statement control amount

    These rows are file-level controls, not POS transactions.
    """
    terminal = ""
    if terminal_col:
        v = row.get(terminal_col)
        terminal = "" if pd.isna(v) else str(v).strip().upper()

    payment = ""
    if payment_col:
        v = row.get(payment_col)
        payment = "" if pd.isna(v) else str(v).strip().upper()

    auth_value = ""
    if auth_col:
        v = row.get(auth_col)
        auth_value = auth(v)

    row_date = pd.NaT
    if date_col:
        row_date = dt(row.get(date_col))

    # Explicit footer/control labels.
    summary_labels = {
        "SUM", "SUM:", "TOTAL", "TOTAL:", "GRAND TOTAL", "GRAND TOTAL:",
        "SUBTOTAL", "SUB TOTAL", "SUMMARY", "CONTROL TOTAL"
    }
    if terminal in summary_labels:
        return True

    # Some files put summary wording in the payment/scheme column.
    if payment in summary_labels:
        return True

    # NaN/blank payment + no auth + no date is not a transaction.
    invalid_payment = payment in {"", "NAN", "NONE", "NULL"}
    if invalid_payment and not auth_value and pd.isna(row_date):
        return True

    # No auth/reference AND no date AND non-numeric terminal identifier
    # strongly indicates a footer/header/control row.
    if not auth_value and pd.isna(row_date):
        if terminal and not re.fullmatch(r"[A-Z0-9\-]+", terminal):
            return True

    return False

def normalize_pos(df,source="POS",forced_payment=None):
    d=norm_cols(df)
    ac=find(d,[
        # TAP: reference_order is the primary provider reference used against D365 Auth Code.
        "reference_order","reference order","referenceorder",
        # TABBY: Order number is the primary provider reference used against D365 Auth Code.
        "order number","order no","order_no","order id","order_id",
        "order_reference_id",
        "auth code","authcode","authorization code","authorizationcode","auth","rrn","reference",
        "payment id","trans approval cd","authorization_id","tr arf","tr_arf"
    ])
    amt=find(d,[
        "pos amount","amount","transaction amount","gross amount","captured amount",
        "settlement amount","value of sales","total amount","transaction_amount"
    ])
    if not ac or not amt:raise ValueError(f"{source}: Auth/Reference and Amount are required.")
    store_col=find(d,["store","store code","store name"])
    branch_col=find(d,["branch name","branch_name","outlet"])
    merchant_col=find(d,["merchant name","merchant_name","retailer name"])
    def _store_value(row):
        # Prefer the most specific, populated identifier for THIS row:
        # explicit store code > branch/outlet name > generic merchant/company name.
        # A file can have a "merchant_name" column that is constant company-wide
        # (e.g. "United Luxury Corpoation") alongside a "branch_name" column that
        # actually varies per store - branch_name must win when it has a value.
        for c in (store_col, branch_col, merchant_col):
            if c:
                v=row.get(c)
                if pd.notna(v) and str(v).strip():
                    return str(v).strip()
        return ""
    date=find(d,[
        # Provider exports: Tabby commonly uses Creation date; Tamara exports
        # can use order/creation/capture/settlement date labels.
        "pos date","transaction date","creation date","creation_date",
        "order date","order_date","order created at","order_created_at",
        "order creation date","order_creation_date",
        "created at","created_at","created date","created_date",
        "captured date","capture date","captured at","captured_at",
        "settlement date","settlement_date","settled at","settled_at",
        "localdate","local date","transaction_date","date"
    ])
    posting=find(d,[
        "posting date","settlement date","payout date","posting_date","settlement_date"
    ])
    # Prefer the actual card scheme over contact method.
    # In the new POS format, payment_type can be "Contactless",
    # while scheme contains the accounting tender (Mada/VISA/MasterCard).
    ptype=find(d,[
        # TAP: payment_scheme is the finance tender (MADA/VISA/MASTERCARD/etc.).
        "payment_scheme","payment scheme",
        "scheme","card type","card","payment type","payment_type","channel"
    ])
    terminal=find(d,["terminal id","tid","terminal","terminal_id"])
    net=find(d,[
        "net amount","net","payout amount","total amount","total_amount"
    ])
    comm=find(d,["commission","fee","mdr","service fee"])
    vat=find(d,["vat","tax","vat amount"])
    status=find(d,["status","transaction status","settlement_status"])
    rows=[]
    for i,r in d.iterrows():
        # Transaction validity gate: exclude statement summaries/footer/control rows
        # before any amount, duplicate, or D365 matching logic.
        if is_pos_summary_or_nontransaction(
            r,
            terminal_col=terminal,
            auth_col=ac,
            date_col=date,
            payment_col=ptype
        ):
            continue

        st=str(r.get(status,"")).strip().upper() if status else ""
        if st in {"CANCEL","CANCELLED","FAILED","FAIL","VOID","VOIDED","EXPIRED"}:
            continue

        a=amount(r.get(amt))
        if pd.isna(a) or abs(a)==0:
            continue
        sr=_store_value(r)
        sc=STORE_MAP.get(sr.upper(),sr)
        is_tap_charge="CHARGE_" in str(source).upper()
        if is_tap_charge:
            # Provider is TAP, but tender comes from payment_scheme.
            pt=str(r.get(ptype,"")).strip().upper() if ptype else ""
        else:
            pt=forced_payment or str(r.get(ptype,source)).strip().upper()
        # Finance-confirmed POS codes.
        pt={"P":"MADA","P1":"MADA","AX":"AMEX","MC":"MASTERCARD","VC":"VISA"}.get(pt,pt)
        if "MASTER" in pt or pt=="MASTERCARD":pt="MASTERCARD"
        elif "VISA" in pt:pt="VISA"
        elif "MADA" in pt or "KNET" in pt:pt="MADA"
        elif "AMEX" in pt or "AMERICAN EXPRESS" in pt:pt="AMEX"
        elif "TABBY" in pt:pt="TABBY"
        elif "TAMARA" in pt:pt="TAMARA"
        elif pt=="TAP" or "TAP" in pt:pt="TAP"
        elif "FLOOSS" in pt:pt="FLOOSS"
        elif "PAYLATER" in pt or "PAY LATER" in pt:pt="PAYLATER"
        elif "DEEMA" in pt:pt="DEEMA"
        n=amount(r.get(net)) if net else a
        c=amount(r.get(comm)) if comm else 0.0
        v=amount(r.get(vat)) if vat else 0.0
        provider_hint="TAP" if "CHARGE_" in str(source).upper() else ""
        pos_date=parse_provider_date(r.get(date),source,provider_hint) if date else pd.NaT
        posting_date=parse_provider_date(r.get(posting),source,provider_hint) if posting else pd.NaT
        provider_name="TAP" if is_tap_charge else (str(forced_payment).upper() if forced_payment else "")
        rows.append({"POS Row":i+1,"Source File":source,"Provider":provider_name,"POS Store":sc,"POS Date":pos_date,
                     "Posting Date":posting_date,"Auth Code":auth(r.get(ac)),
                     "Provider Reference":str(r.get(ac,"")).strip() if ac else "",
                     "POS Payment":pt,"POS Amount":a,"Net Amount":n if pd.notna(n) else a,
                     "Commission":c if pd.notna(c) else 0.0,"VAT":v if pd.notna(v) else 0.0,
                     "Terminal ID":str(r.get(terminal,"")).strip() if terminal else "",
                     "Merchant ID":str(r.get(find(d,["merchant id","merchant_id","retailer id"]),"")).strip() if find(d,["merchant id","merchant_id","retailer id"]) else "",
                     "Account":str(r.get(find(d,["account","account number","retailer pos account"]),"")).strip() if find(d,["account","account number","retailer pos account"]) else "",
                     "ARN":str(r.get(find(d,["arn"]),"")).strip() if find(d,["arn"]) else "",
                     "Slip No":str(r.get(find(d,["tr slip","tr_slip","slip no"]),"")).strip() if find(d,["tr slip","tr_slip","slip no"]) else ""})
    out=pd.DataFrame(rows)
    if out.empty:
        return out

    # Final defensive filter against file-level summary/control rows.
    terminal_text=out["Terminal ID"].astype(str).str.strip().str.upper()
    payment_text=out["POS Payment"].astype(str).str.strip().str.upper()
    bad_terminal=terminal_text.isin({"SUM","SUM:","TOTAL","TOTAL:","GRAND TOTAL","GRAND TOTAL:","SUBTOTAL","SUMMARY"})
    bad_payment=payment_text.isin({"NAN","NONE","NULL","SUM","SUM:","TOTAL","TOTAL:"})
    out=out[~bad_terminal & ~bad_payment].copy()

    if out.empty:
        return out

    out["POS Duplicate"]=out.duplicated(["POS Store","Auth Code","POS Payment","POS Amount"],keep=False)
    out["Settlement Delay Days"]=(out["Posting Date"]-out["POS Date"]).dt.days
    return out




def apply_store_mapping_master(pos, store_master):
    """
    Apply editable Provider Store Name -> D365 Store Code mapping.
    This runs before Terminal Master, because some BNPL/provider files carry
    store/branch names but no terminal IDs.
    """
    if pos is None or pos.empty or store_master is None or store_master.empty:
        return pos

    out=pos.copy()
    cols={str(c).strip().lower():c for c in store_master.columns}
    name_col=cols.get("provider store name") or cols.get("store name") or cols.get("provider_store_name")
    code_col=cols.get("store code") or cols.get("store_code")
    active_col=cols.get("active")

    if name_col is None or code_col is None:
        return out

    mapping={}
    for _,r in store_master.iterrows():
        if active_col is not None:
            av=str(r.get(active_col,"Yes")).strip().upper()
            if av in {"NO","N","FALSE","0","INACTIVE"}:
                continue
        name="" if pd.isna(r.get(name_col)) else str(r.get(name_col)).strip()
        code="" if pd.isna(r.get(code_col)) else str(r.get(code_col)).strip()
        if code.endswith(".0") and code[:-2].isdigit():
            code=code[:-2]
        if name and code:
            mapping[name.upper()]=code

    if not mapping:
        return out

    mapped_flags=[]
    new_store=[]
    for _,r in out.iterrows():
        raw=str(r.get("POS Store","")).strip()
        sc=mapping.get(raw.upper())
        if sc:
            new_store.append(sc)
            mapped_flags.append(True)
        else:
            new_store.append(raw)
            mapped_flags.append(False)

    out["POS Store"]=new_store
    out["Store Name Mapped"]=mapped_flags
    return out

def terminal_key(v):
    if pd.isna(v): return ""
    if isinstance(v,float) and v.is_integer(): v=int(v)
    s=str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit(): s=s[:-2]
    return re.sub(r"[^A-Z0-9]","",s.upper())

def apply_terminal_master(pos, terminal_master):
    """
    Resolve Terminal ID -> D365 Store Code.

    If a POS row has only a generic merchant/company name (for example
    UNITED LUXURY CORP) and the Terminal ID is not mapped, do not treat
    that merchant name as a Store Code. Mark the row as requiring a
    Terminal Master mapping.
    """
    if pos is None or pos.empty:
        return pos

    out=pos.copy()
    exact={}
    prefix8={}

    if terminal_master is not None and not terminal_master.empty:
        for _,r in terminal_master.iterrows():
            tid=terminal_key(r.get("Terminal ID"))
            sc=str(r.get("Store Code","")).strip()
            if sc.endswith(".0") and sc[:-2].isdigit():
                sc=sc[:-2]
            if tid and sc:
                exact[tid]=sc
                prefix8[tid[:8]]=sc

    mapped=[]
    flags=[]
    needs_mapping=[]

    for _,r in out.iterrows():
        tid=terminal_key(r.get("Terminal ID"))
        sc=(exact.get(tid) or prefix8.get(tid[:8])) if tid else None
        raw_store=str(r.get("POS Store","")).strip()

        if sc:
            mapped.append(sc)
            flags.append(True)
            needs_mapping.append(False)
        elif raw_store.isdigit():
            mapped.append(raw_store)
            flags.append(False)
            needs_mapping.append(False)
        else:
            # Generic merchant/company text is not a D365 Store Code.
            mapped.append("")
            flags.append(False)
            needs_mapping.append(bool(tid))

    out["POS Store"]=mapped
    out["Terminal Store Mapped"]=flags
    out["Terminal Mapping Required"]=needs_mapping

    terminal_success=pd.Series(flags,index=out.index).fillna(False)
    if "Merchant Mapping Required" in out.columns:
        out.loc[terminal_success,"Merchant Mapping Required"]=False
    if "Store Mapping Required" in out.columns:
        out.loc[terminal_success,"Store Mapping Required"]=False

    return out

def apply_merchant_master(pos, merchant_master):
    """
    Resolve Merchant ID -> D365 Store Code.

    Second-priority tier in the store-resolution chain:
      Terminal ID -> Merchant ID -> Provider Store Name -> Store Mapping Required
    This must run BEFORE apply_terminal_master() in the pipeline so a
    Terminal ID match (when present) always wins over a Merchant ID match.
    It must run AFTER apply_store_mapping_master() so a Merchant ID match
    (when present) wins over a bare provider/branch name match.

    Some provider settlement files (TAP charge exports, for example) carry
    a numeric merchant_id but no terminal reference and no usable store
    name at all - this is the only identifier available for them.
    """
    if pos is None or pos.empty:
        return pos

    out=pos.copy()
    exact={}
    if merchant_master is not None and not merchant_master.empty:
        for _,r in merchant_master.iterrows():
            mid=terminal_key(r.get("Merchant ID"))
            sc=str(r.get("Store Code","")).strip()
            if sc.endswith(".0") and sc[:-2].isdigit():
                sc=sc[:-2]
            if mid and sc:
                exact[mid]=sc

    mapped=[]
    flags=[]
    needs_mapping=[]
    for _,r in out.iterrows():
        mid=terminal_key(r.get("Merchant ID"))
        sc=exact.get(mid) if mid else None
        raw_store=str(r.get("POS Store","")).strip()

        if sc:
            mapped.append(sc)
            flags.append(True)
            needs_mapping.append(False)
        elif raw_store.isdigit():
            mapped.append(raw_store)
            flags.append(False)
            needs_mapping.append(False)
        else:
            mapped.append("")
            flags.append(False)
            needs_mapping.append(bool(mid))

    out["POS Store"]=mapped
    out["Merchant Store Mapped"]=flags
    out["Merchant Mapping Required"]=needs_mapping

    merchant_success=pd.Series(flags,index=out.index).fillna(False)
    if "Store Mapping Required" in out.columns:
        out.loc[merchant_success,"Store Mapping Required"]=False

    return out

def _norm_payment(v):
    p=str(v or "").strip().upper()
    code_map={"P":"MADA","P1":"MADA","AX":"AMEX","MC":"MASTERCARD","VC":"VISA","MASTER":"MASTERCARD"}
    p=code_map.get(p,p)
    if "MASTER" in p:return "MASTERCARD"
    if "VISA" in p:return "VISA"
    if "MADA" in p or "KNET" in p:return "MADA"
    if "AMEX" in p or "AMERICAN EXPRESS" in p:return "AMEX"
    return p

def _collapse_exact_pos_duplicates(pos):
    """
    Collapse exact repeated POS records caused by overlapping/daily statement uploads.
    The transaction remains matchable, while we retain duplicate-source information.
    """
    if pos is None or pos.empty:
        return pos

    d=pos.copy()
    d["POS Payment"]=d["POS Payment"].apply(_norm_payment)
    d["_DATE_KEY"]=pd.to_datetime(d["POS Date"],errors="coerce").dt.normalize()
    d["_STORE_KEY"]=d["POS Store"].astype(str).str.strip()
    d["_AUTH_KEY"]=d["Auth Code"].astype(str).str.strip()
    d["_AMT_KEY"]=pd.to_numeric(d["POS Amount"],errors="coerce").round(2)

    key=["_STORE_KEY","_DATE_KEY","_AUTH_KEY","POS Payment","_AMT_KEY"]
    grp=d.groupby(key,dropna=False,sort=False)

    rows=[]
    for _,g in grp:
        r=g.iloc[0].copy()
        r["Exact POS Repeat Count"]=len(g)
        r["Exact POS Repeat Collapsed"]=len(g)>1
        if "Source File" in g.columns:
            r["Source File"]=" | ".join(sorted(set(g["Source File"].astype(str))))
        # This is no longer treated as an ambiguous duplicate when every key field is identical.
        r["POS Duplicate"]=False
        rows.append(r)

    out=pd.DataFrame(rows).drop(columns=["_DATE_KEY","_STORE_KEY","_AUTH_KEY","_AMT_KEY"],errors="ignore")
    return out.reset_index(drop=True)

def _date_plausible_for_source(pos_date, source_file):
    """
    Lightweight source-period sanity check.
    If filename contains YYMMDD / YYYYMMDD-like range markers, flag clearly
    impossible dates rather than declaring Missing D365.
    """
    d=pd.to_datetime(pos_date,errors="coerce")
    if pd.isna(d):
        return False

    s=str(source_file or "")
    years=[int(x) for x in re.findall(r"(20\d{2})",s)]
    if years and d.year not in set(years):
        return False
    return True

def classify_unmatched_pos_row(r):
    """
    Convert 'unmatched' into a finance-meaningful exception class.
    Priority mirrors store resolution: Terminal ID > Merchant ID > Provider
    Store Name > unresolved.
    """
    if bool(r.get("Terminal Mapping Required",False)):
        return "Terminal Mapping Required"

    if bool(r.get("Merchant Mapping Required",False)):
        return "Merchant Mapping Required"

    store=str(r.get("POS Store","")).strip()
    if not store or store.lower()=="nan":
        return "Store Mapping Required"

    if not _date_plausible_for_source(r.get("POS Date"),r.get("Source File")):
        return "Date Validation Required"

    if bool(r.get("POS Duplicate",False)):
        return "Duplicate Provider/POS"

    return "Missing D365"


def _auto_resolution_signature_candidates(s, pos_pool, tolerance=1.0):
    """
    Final deterministic candidate finder used before manual correction.

    This NEVER changes D365 data. It only proves a one-to-one match using
    strong transaction evidence that is already present:
      A) Store + Payment + normalized Auth + exact amount
      B) Store + Date + Payment + exact amount
      C) Store + Date + Payment + amount within approved tolerance

    It returns a candidate only when exactly one provider/POS row satisfies
    the rule. Ambiguous cases remain exceptions for maker-checker review.
    """
    if pos_pool is None or pos_pool.empty:
        return None,""

    payment=_norm_payment(s.get("D365 Payment",""))
    store=str(s.get("Store Code","")).strip()
    ad=auth(s.get("Auth Code",""))
    amt=float(s.get("D365 Amount",0) or 0)
    ddate=pd.to_datetime(s.get("Date"),errors="coerce")

    x=pos_pool.copy()
    if "POS Payment" not in x.columns or "POS Amount" not in x.columns:
        return None,""
    x["POS Payment"]=x["POS Payment"].apply(_norm_payment)
    x=x[x["POS Payment"]==payment].copy()
    if x.empty:return None,""

    # Store must be reliable and equal for auto-resolution.
    if "POS Store" not in x.columns:
        return None,""
    reliable=x["POS Store"].astype(str).str.fullmatch(r"\d+")
    if "Terminal Store Mapped" in x.columns:
        reliable = reliable | x["Terminal Store Mapped"].fillna(False)
    if "Merchant Store Mapped" in x.columns:
        reliable = reliable | x["Merchant Store Mapped"].fillna(False)
    x=x[reliable & (x["POS Store"].astype(str).str.strip()==store)].copy()
    if x.empty:return None,""

    # Never consume master-data/date-validation exceptions automatically.
    for c in ["Terminal Mapping Required","Merchant Mapping Required"]:
        if c in x.columns:
            x=x[~x[c].fillna(False)].copy()
    if x.empty:return None,""

    x["_ABS"]=(pd.to_numeric(x["POS Amount"],errors="coerce")-amt).abs()

    # A. Normalized Auth + exact amount.
    if ad and "Auth Code" in x.columns:
        xa=x[x["Auth Code"].apply(auth)==ad]
        xa=xa[xa["_ABS"]<=0.005]
        if len(xa)==1:
            return xa.iloc[0],"AUTO: Store + Normalized Auth + Tender + Exact Amount"

    # B/C. Same transaction date + amount.
    if pd.notna(ddate) and "POS Date" in x.columns:
        xd=x[pd.to_datetime(x["POS Date"],errors="coerce").dt.normalize()==ddate.normalize()].copy()
        exact=xd[xd["_ABS"]<=0.005]
        if len(exact)==1:
            return exact.iloc[0],"AUTO: Store + Date + Tender + Exact Amount"
        within=xd[xd["_ABS"]<=float(tolerance)]
        if len(within)==1:
            return within.iloc[0],"AUTO: Store + Date + Tender + Approved Tolerance"

    return None,""


def reconcile(tender,pos,tolerance=1.0):
    """
    Evidence-based reconciliation.

    Exact repeated POS rows from overlapping statements are collapsed first.
    Matching hierarchy:
      1. Reliable Store + Payment + Auth + Exact Amount
      2. Payment + Auth + Exact Amount where POS store is unavailable/unreliable
      3. Same Date + Payment + Amount (Store when reliable)
      4. Approved SAR tolerance
    Multiple genuinely different candidates are never guessed.
    """
    if tender.empty:
        return pd.DataFrame(),pd.DataFrame(),pos.copy()

    if pos.empty:
        u=tender.copy()
        u["Reason"]="Missing POS/provider transaction"
        return pd.DataFrame(),u,pd.DataFrame()

    pos=_collapse_exact_pos_duplicates(pos)
    used=set()
    rows=[]
    uns=[]

    for _,s in tender.reset_index(drop=True).iterrows():
        # Keep only transaction-identical D365 duplicates as exceptions.
        # Same Auth Code on another date/receipt is NOT a duplicate.
        if bool(s.get("D365 Duplicate",False)):
            rr=s.to_dict()
            rr["Reason"]="True duplicate D365 transaction - requires manual review"
            rr["Auto Resolution Status"]="Manual Review - True Duplicate"
            uns.append(rr)
            continue

        payment=_norm_payment(s["D365 Payment"])
        amount_d365=float(s["D365 Amount"])
        auth_d365=str(s["Auth Code"]).strip()
        provider_key_d365=provider_ref_key(auth_d365) if payment in {"TABBY","TAMARA"} else auth_d365
        store_d365=str(s["Store Code"]).strip()
        date_d365=pd.to_datetime(s["Date"],errors="coerce")

        cand=pos[~pos.index.isin(used)].copy()

        # Rows with a Terminal ID or Merchant ID but no Store mapping are not
        # allowed to be misclassified as Missing D365. They remain a
        # master-data exception until the relevant master is updated.
        if "Terminal Mapping Required" in cand.columns:
            cand=cand[~cand["Terminal Mapping Required"].fillna(False)].copy()
        if "Merchant Mapping Required" in cand.columns:
            cand=cand[~cand["Merchant Mapping Required"].fillna(False)].copy()

        cand["POS Payment"]=cand["POS Payment"].apply(_norm_payment)

        # Payment type is always required when known.
        pc=cand[cand["POS Payment"]==payment]
        if not pc.empty:
            cand=pc

        # Reliable store check:
        # numeric Store Code or explicitly mapped by Terminal Master.
        reliable_store = cand["POS Store"].astype(str).str.fullmatch(r"\d+")
        if "Terminal Store Mapped" in cand.columns:
            reliable_store = reliable_store | cand["Terminal Store Mapped"].fillna(False)
        if "Merchant Store Mapped" in cand.columns:
            reliable_store = reliable_store | cand["Merchant Store Mapped"].fillna(False)

        same_store = cand[
            reliable_store &
            (cand["POS Store"].astype(str).str.strip()==store_d365)
        ]
        if not same_store.empty:
            store_pool=same_store
        else:
            # POS may only contain generic company/merchant text.
            store_pool=cand

        sel=None
        rule=""
        status=""
        reason=""

        # ------------------------------------------------------
        # Rule 1: Auth + Exact Amount (with store if reliable)
        # ------------------------------------------------------
        if auth_d365:
            if payment in {"TABBY","TAMARA"}:
                _provider_keys=store_pool["Auth Code"].apply(provider_ref_key)
                x=store_pool[_provider_keys==provider_key_d365].copy()
            else:
                x=store_pool[store_pool["Auth Code"].astype(str).str.strip()==auth_d365].copy()
            if not x.empty:
                x["ABS"]=(pd.to_numeric(x["POS Amount"],errors="coerce")-amount_d365).abs()

                exact=x[x["ABS"]<=0.005]
                if len(exact)==1:
                    sel=exact.iloc[0]
                    if payment=="TABBY":
                        rule="TABBY Order Number + Store + Exact Amount" if not same_store.empty else "TABBY Order Number + Exact Amount"
                    elif payment=="TAMARA":
                        rule="TAMARA Reference + Store + Exact Amount" if not same_store.empty else "TAMARA Reference + Exact Amount"
                    else:
                        rule="Store + Date/Auth + Tender + Exact Amount" if not same_store.empty else "Auth + Tender + Exact Amount"
                    status="Matched"
                elif len(exact)>1:
                    # Prefer same date to disambiguate exact auth repeats.
                    if pd.notna(date_d365):
                        xd=exact[pd.to_datetime(exact["POS Date"],errors="coerce").dt.normalize()==date_d365.normalize()]
                        if len(xd)==1:
                            sel=xd.iloc[0]
                            rule="Store + Date + Auth + Tender + Exact Amount"
                            status="Matched"
                        else:
                            reason="Multiple Auth + Exact Amount candidates"
                    else:
                        reason="Multiple Auth + Exact Amount candidates"
                else:
                    within=x[x["ABS"]<=tolerance]
                    if len(within)==1:
                        sel=within.iloc[0]
                        rule="Auth + Tender + Approved Tolerance"
                        status="Matched"
                    elif len(within)>1:
                        reason="Multiple Auth candidates within tolerance"
                    elif len(x)==1:
                        sel=x.iloc[0]
                        rule="Auth + Tender + Closest Amount"
                        status="Review"

        # ------------------------------------------------------
        # Rule 2: Same Date + Payment + Amount fallback
        # ------------------------------------------------------
        if sel is None and pd.notna(date_d365):
            x=store_pool.copy()
            x=x[pd.to_datetime(x["POS Date"],errors="coerce").dt.normalize()==date_d365.normalize()]

            if not x.empty:
                x["ABS"]=(pd.to_numeric(x["POS Amount"],errors="coerce")-amount_d365).abs()
                exact=x[x["ABS"]<=0.005]

                if len(exact)==1:
                    sel=exact.iloc[0]
                    rule="Store + Date + Tender + Exact Amount" if not same_store.empty else "Date + Tender + Exact Amount"
                    status="Matched"
                elif len(exact)>1:
                    reason=f"Multiple {payment} candidates: same Date + Amount"
                else:
                    within=x[x["ABS"]<=tolerance]
                    if len(within)==1:
                        sel=within.iloc[0]
                        rule="Date + Tender + Approved Tolerance"
                        status="Matched"
                    elif len(within)>1:
                        reason=f"Multiple {payment} candidates within SAR {tolerance:.2f} tolerance"

        if sel is None:
            # Final deterministic auto-resolution pass. This is intentionally
            # conservative: exactly one strong candidate is required.
            remaining=pos[~pos.index.isin(used)].copy()
            auto_sel,auto_rule=_auto_resolution_signature_candidates(
                s,remaining,tolerance
            )
            if auto_sel is not None:
                sel=auto_sel
                rule=auto_rule
                status="Matched"
                reason=""

        if sel is None:
            rr=s.to_dict()
            rr["Reason"]=reason or "Missing settlement"
            rr["Auto Resolution Status"]="Manual Review Required"
            uns.append(rr)
            continue

        used.add(sel.name)
        diff=round(amount_d365-float(sel["POS Amount"]),2)

        rows.append({
            "Unique Transaction ID":s["Unique Transaction ID"],
            "Store Code":s["Store Code"],
            "Date":s["Date"],
            "Receipt ID":s["Receipt ID"],
            "Auth Code":s["Auth Code"],
            "Sales Order":s.get("Sales Order",""),
            "SalesDetails Bridge Status":s.get("SalesDetails Bridge Status",""),
            "SalesDetails Source":s.get("SalesDetails Source",""),
            "StoreTender Reference":s.get("StoreTender Reference",""),
            "Provider Reference":sel["Auth Code"] if payment in {"TABBY","TAMARA"} else "",
            "Provider Reference Key":provider_ref_key(sel["Auth Code"]) if payment in {"TABBY","TAMARA"} else "",
            "Payment Type":payment,
            "D365 Amount":s["D365 Amount"],
            "POS Amount":sel["POS Amount"],
            "Net Amount":sel["Net Amount"],
            "Commission":sel["Commission"],
            "VAT":sel["VAT"],
            "Difference":diff,
            "Status":status,
            "Match Rule":rule,
            "Auto Resolution Status":"Automatically Resolved" if str(rule).startswith("AUTO:") else "Primary Match Rule",
            "POS Date":sel["POS Date"],
            "Posting Date":sel["Posting Date"],
            "Settlement Delay Days":sel["Settlement Delay Days"],
            "Terminal ID":sel["Terminal ID"],
            "Source File":sel["Source File"],
            "D365 Duplicate":s["D365 Duplicate"],
            "POS Duplicate":False,
            "Exact POS Repeat Count":sel.get("Exact POS Repeat Count",1),
            "Exact POS Repeat Collapsed":sel.get("Exact POS Repeat Collapsed",False),
            "Bank Settled":False,
            "Bank Name":"",
            "Bank Date":pd.NaT,
            "Bank Amount":np.nan
        })

    matched=pd.DataFrame(rows)
    unmatched_sales=pd.DataFrame(uns)

    unmatched_pos=pos[~pos.index.isin(used)].copy()
    if not unmatched_pos.empty:
        unmatched_pos["Exception Status"]=unmatched_pos.apply(classify_unmatched_pos_row,axis=1)

        def _reason(r):
            st=r["Exception Status"]
            if st=="Terminal Mapping Required":
                return "Terminal ID is not mapped to a D365 Store Code. Update POS Terminal Master and rerun."
            if st=="Merchant Mapping Required":
                return "Merchant ID is not mapped to a D365 Store Code. Update Merchant ID Master and rerun."
            if st=="Store Mapping Required":
                return "Provider transaction has no reliable D365 Store Code. Update Store Mapping Master and rerun."
            if st=="Date Validation Required":
                return "Provider transaction date is missing or inconsistent with the source file period. Validate provider date mapping."
            if st=="Duplicate Provider/POS":
                return "Duplicate provider/POS transaction requires review."
            return "Valid mapped provider transaction found but no matching D365 Store Tender transaction."

        unmatched_pos["Reason"]=unmatched_pos.apply(_reason,axis=1)

    return matched,unmatched_sales,unmatched_pos


def parse_bank_narration(text):
    """
    Extract settlement evidence from bank narration without changing the raw text.
    Evidence may include provider, terminal, merchant, scheme, payout/batch ID and
    transaction count. Missing fields remain blank; nothing is invented.
    """
    raw="" if text is None or (isinstance(text,float) and pd.isna(text)) else str(text)
    s=raw.upper()

    provider=""
    for p in ["TABBY","TAMARA","AMEX","TAP"]:
        if p in s:
            provider=p
            break
    if not provider and any(k in s for k in ["MADA","VISA","MASTER","MC ","VC "]):
        provider="ANB POS"

    scheme=""
    if "MADA" in s: scheme="MADA"
    elif re.search(r"\b(VISA|VC)\b",s): scheme="VISA"
    elif re.search(r"\b(MASTER|MASTERCARD|MC)\b",s): scheme="MASTERCARD"
    elif "AMEX" in s: scheme="AMEX"

    terminal=""
    for pat in [
        r"\b(?:TID|TERMINAL(?:\s*ID)?)\s*[:#\-]?\s*([A-Z0-9]{5,20})\b",
        r"\bPOS\s*[:#\-]?\s*([0-9]{5,20})\b",
    ]:
        m=re.search(pat,s)
        if m:
            terminal=m.group(1); break

    merchant=""
    for pat in [
        r"\b(?:MID|MERCHANT(?:\s*ID)?)\s*[:#\-]?\s*([A-Z0-9]{5,30})\b",
        r"\bRETAILER\s*ID\s*[:#\-]?\s*([A-Z0-9]{5,30})\b",
    ]:
        m=re.search(pat,s)
        if m:
            merchant=m.group(1); break

    payout_id=""
    for pat in [
        r"\bPAYOUT[_\s:#\-]*([A-Z0-9\-]{6,})\b",
        r"\bSETTLEMENT[_\s:#\-]*([A-Z0-9\-]{6,})\b",
    ]:
        m=re.search(pat,s)
        if m:
            payout_id=m.group(1); break

    tx_count=np.nan
    m=re.search(r"\b(?:TX|TRX|TRANSACTIONS?)\s*[_:#\-]?\s*(\d{1,6})\b",s)
    if m:
        try: tx_count=int(m.group(1))
        except Exception: pass

    return {
        "Narration Provider":provider,
        "Narration Scheme":scheme,
        "Narration Terminal ID":terminal,
        "Narration Merchant ID":merchant,
        "Narration Payout ID":payout_id,
        "Narration Transaction Count":tx_count,
    }

def detect_bank_name(source,df=None):
    """
    Detect bank from statement evidence. Filename is only a fallback.
    """
    s=str(source or "").upper()
    if "RAJHI" in s or "ALRAJHI" in s:
        return "AL RAJHI"
    if "ANB" in s or "ARAB NATIONAL" in s:
        return "ANB"

    # Known statement/account text can be used when available.
    if df is not None and not df.empty:
        txt=" ".join(
            " ".join(map(str,row))
            for row in df.astype(str).head(25).values.tolist()
        ).upper()
        if "AL RAJHI" in txt or "ALRAJHI" in txt:
            return "AL RAJHI"
        if "ARAB NATIONAL BANK" in txt or "ANB" in txt:
            return "ANB"
    return "UNKNOWN"


def normalize_bank(df,bank):
    d=norm_cols(df)

    dc=find(d,[
        "date","transaction date","posting date","value date",
        "transaction_date","posting_date","value_date","booking date"
    ])

    # Prefer a direct amount/credit field.
    ac=find(d,[
        "amount","credit","credit amount","deposit amount","net amount",
        "transaction amount","amount sar","credit_amount","deposit_amount",
        "transaction_amount","local amount"
    ])

    # Some bank statements split debit and credit.
    credit_col=find(d,["credit","credit amount","credit_amount"])
    debit_col=find(d,["debit","debit amount","debit_amount"])

    desc=find(d,[
        "description","narration","details","reference","remarks",
        "transaction details","transaction description"
    ])

    if ac:
        bank_amount=d[ac].apply(amount)
    elif credit_col or debit_col:
        credit=d[credit_col].apply(amount) if credit_col else pd.Series(0.0,index=d.index)
        debit=d[debit_col].apply(amount) if debit_col else pd.Series(0.0,index=d.index)
        credit=credit.fillna(0.0)
        debit=debit.fillna(0.0)
        # Bank credits are positive; debits negative.
        bank_amount=(credit-debit).round(2)
    else:
        raise ValueError(f"{bank}: amount column not found.")

    out=pd.DataFrame({
        "Bank":bank,
        "Bank Date":d[dc].apply(dt) if dc else pd.NaT,
        "Bank Amount":bank_amount,
        "Description":d[desc].astype(str) if desc else ""
    })

    # Remove blank/zero/non-transaction rows.
    out=out[out["Bank Amount"].notna()].copy()
    out=out[out["Bank Amount"]!=0].copy()
    return out

def apply_bank_settlement(recon,bank,tolerance=1.0):
    if recon.empty:return recon
    out=recon.copy()
    if bank is None or bank.empty:return out
    used=set()
    for i,r in out.iterrows():
        cand=bank[~bank.index.isin(used)].copy()
        if cand.empty:continue
        target=abs(float(r["Net Amount"]))
        cand["ABS"]=(cand["Bank Amount"].abs()-target).abs()
        if pd.notna(r["Posting Date"]):
            local=cand[cand["Bank Date"].between(r["Posting Date"]-pd.Timedelta(days=7),r["Posting Date"]+pd.Timedelta(days=7))]
            if not local.empty:cand=local
        best=cand.sort_values("ABS").iloc[0]
        if best["ABS"]<=tolerance:
            used.add(best.name)
            out.at[i,"Bank Settled"]=True;out.at[i,"Bank Name"]=best["Bank"];out.at[i,"Bank Date"]=best["Bank Date"];out.at[i,"Bank Amount"]=best["Bank Amount"]
    return out

def make_carry_forward(unmatched_sales,unmatched_pos,previous=None):
    fs=[]
    if previous is not None and not previous.empty:
        x=previous.copy();x["Carry Forward Source"]="Prior Period";fs.append(x)
    if unmatched_sales is not None and not unmatched_sales.empty:
        x=unmatched_sales.copy();x["Carry Forward Type"]="OPEN_D365";x["Carry Forward Source"]="Current";fs.append(x)
    if unmatched_pos is not None and not unmatched_pos.empty:
        x=unmatched_pos.copy();x["Carry Forward Type"]="OPEN_POS";x["Carry Forward Source"]="Current";fs.append(x)
    return pd.concat(fs,ignore_index=True,sort=False) if fs else pd.DataFrame()

def jv_group(payment):
    return "CC" if payment in {"MADA","VISA","MASTERCARD"} else payment

def _commission_master_maps(commission_master):
    rate_map={}
    vat_map={}
    method_map={}

    if commission_master is None or commission_master.empty:
        defaults=[
            ("MADA",0.55,15.0,"CONTRACT_RATE"),
            ("VISA",1.55,15.0,"CONTRACT_RATE"),
            ("MASTERCARD",1.55,15.0,"CONTRACT_RATE"),
            ("GCC NET",1.50,15.0,"CONTRACT_RATE"),
            ("AMEX",3.00,15.0,"CONTRACT_RATE"),
            ("TABBY",np.nan,15.0,"PROVIDER_ACTUAL"),
            ("TAMARA",np.nan,15.0,"PROVIDER_ACTUAL"),
            ("TAP",np.nan,15.0,"PROVIDER_ACTUAL"),
        ]
        for p,r,v,m in defaults:
            rate_map[p]=r; vat_map[p]=v; method_map[p]=m
        return rate_map,vat_map,method_map

    cm=commission_master.copy()
    cm.columns=[str(c).strip() for c in cm.columns]

    for _,r in cm.iterrows():
        p=_norm_payment(r.get("Payment Type",""))
        if p=="GCCNET":
            p="GCC NET"
        if not p:
            continue

        active=str(r.get("Active","Yes")).strip().upper()
        if active in {"NO","N","FALSE","0","INACTIVE"}:
            continue

        rate=pd.to_numeric(pd.Series([r.get("Commission Rate %",np.nan)]),errors="coerce").iloc[0]
        vat=pd.to_numeric(pd.Series([r.get("VAT Rate %",15.0)]),errors="coerce").iloc[0]
        method=str(r.get("Validation Method","")).strip().upper()
        if not method:
            method="CONTRACT_RATE" if pd.notna(rate) else "PROVIDER_ACTUAL"

        rate_map[p]=rate
        vat_map[p]=15.0 if pd.isna(vat) else float(vat)
        method_map[p]=method

    return rate_map,vat_map,method_map



# ---------------------------------------------------------------------------
# D365 JV mapping confirmed by Finance
# ---------------------------------------------------------------------------
D365_JV_DEFAULTS = {
    "COMPANY": "ULC",
    "CURRENCY": "SAR",
    "BANK_ACCOUNT": "1015",
    "COMMISSION_GL": "7231",
    "VAT_VENDOR": "P0672",

    # Confirmed payment clearing / sales GL mapping
    "CC_GL": "11020907",       # MADA + VISA + MASTERCARD
    "AMEX_GL": "11020901",
    "TABBY_GL": "11020913",
    "TAMARA_GL": "11020922",
    "TAP_GL": "11020904",
}

# Store display names used in D365 descriptions.
# Additional stores can be maintained here / migrated to Store Master.
D365_STORE_DISPLAY = {
    "601": {"store_name": "Aigner Tahlia Mall", "location": "601"},
    "602": {"store_name": "Aigner Faisaliah Mall", "location": "602"},
    "603": {"store_name": "Aigner Red Sea Mall", "location": "603"},
    "606": {"store_name": "Aigner Riyadh Park", "location": "606"},
    "609": {"store_name": "Aigner Rashid Mall", "location": "609"},
    "613": {"store_name": "Aigner KSA Online", "location": "613"},
    "614": {"store_name": "Tag Heuer Red Sea Mall", "location": "614"},
    "615": {"store_name": "Tag Heuer Riyadh Park", "location": "615"},
    "619": {"store_name": "Aigner Mall of Arabia", "location": "619"},
    "624": {"store_name": "Aigner Hayat Mall", "location": "624"},
    "629": {"store_name": "Tag Heuer Rashid Mall", "location": "629"},
    "630": {"store_name": "Fred Solitaire Mall", "location": "630"},
    "634": {"store_name": "Aigner Solitaire Mall", "location": "634"},
    "643": {"store_name": "Aigner Kingdom Tower", "location": "643"},
    "644": {"store_name": "Aigner Nakheel Mall", "location": "644"},
    "649": {"store_name": "Piaget Solitaire Mall", "location": "649"},
    "650": {"store_name": "Panerai Solitaire Mall", "location": "650"},
    "651": {"store_name": "IWC Solitaire Mall", "location": "651"},
    "652": {"store_name": "JLC Solitaire Mall", "location": "652"},
    "658": {"store_name": "Options Al Andalus Mall", "location": "658"},
}

def _d365_store_info(store_code):
    s = str(store_code).strip()
    if s.endswith(".0"):
        s = s[:-2]
    info = D365_STORE_DISPLAY.get(s, {})
    return {
        "store_code": s,
        "store_name": info.get("store_name", s),
        "location": info.get("location", s),
    }

def _d365_month_year(date_value):
    d = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(d):
        return "", ""
    return d.strftime("%b"), d.strftime("%Y")

def _d365_description(kind, store_name, month, year):
    templates = {
        "BANK": f"CC-Deposited- {store_name}- {month} -{year}",
        "COMMISSION": f"Credit Card Commission - {store_name}- {month} -{year}",
        "VAT": f"VAT on Credit Card Commision - {store_name}- {month} -{year}",
        "SALE": f"CC-Sale- {store_name}- {month} -{year}",
    }
    return templates[kind]

def _d365_dimension(account, store_code, department=""):
    # Confirmed examples:
    # 7231-601--Sale
    # 11020907-601---
    if department:
        return f"{account}-{store_code}--{department}"
    return f"{account}-{store_code}---"


# =====================================================================
# D365 GENERAL LEDGER / CLEARING CONTROL
# =====================================================================

D365_CLEARING_ACCOUNT_MAP = {
    "11020907": {"group":"CARD", "account_name":"POS Clearing - DC/CC", "payments":["MADA","VISA","MASTERCARD"]},
    "11020901": {"group":"AMEX", "account_name":"POS Clearing - AMEX", "payments":["AMEX"]},
    "11020902": {"group":"CASH", "account_name":"POS Clearing - Cash/Cheques", "payments":["CASH"]},
    "11020913": {"group":"TABBY", "account_name":"POS/Online Clearing - Tabby", "payments":["TABBY"]},
    "11020922": {"group":"TAMARA", "account_name":"POS/Online Clearing - Tamara", "payments":["TAMARA"]},
    "11020904": {"group":"TAP", "account_name":"POS Clearing - Tap", "payments":["TAP"]},
    "11020908": {"group":"TAP_GATEWAY", "account_name":"Online Clearing - Tap Gateway", "payments":["TAP"]},
}

def _gl_text(v):
    if v is None or (isinstance(v,float) and pd.isna(v)):
        return ""
    return str(v).strip()

def _gl_main_store_dimension(ledger_account):
    """
    Parse D365 dimension strings such as:
        11020907-601--Sale-10415---
        11020913-613------
    Returns main account, store and the untouched ledger dimension.
    """
    raw=_gl_text(ledger_account)
    parts=raw.split("-")
    main=parts[0].strip() if parts else ""
    store=""
    if len(parts)>1:
        p=parts[1].strip()
        if re.fullmatch(r"\d{3}",p):
            store=p
    return main,store,raw

def _gl_sales_order(description):
    s=_gl_text(description).upper()
    m=re.search(r"\b(SO[A-Z0-9]*-\d+)\b",s)
    return m.group(1) if m else ""

def _gl_event_type(description,amount_value):
    s=_gl_text(description).upper()
    if any(k in s for k in ["WRONG PUNCHED","REVERS","CORRECTION","CORRECTED","RECLASS"]):
        return "REVERSAL / CORRECTION"
    if "STATEMENT DIFFERENCE" in s:
        return "STATEMENT DIFFERENCE"
    try:
        a=float(amount_value)
    except Exception:
        a=0.0
    return "POSITIVE CLEARING MOVEMENT" if a>0 else ("NEGATIVE CLEARING MOVEMENT" if a<0 else "ZERO MOVEMENT")


# =====================================================================
# SETTLEMENT BATCH ENGINE
# =====================================================================

def classify_settlement_source(name,df):
    d=norm_cols(df)
    cols=set(d.columns)
    n=str(name or "").upper()

    # Tamara merchant statement / invoice payout file.
    if (
        ("payable to merchant" in cols or "statement id" in cols or "statement period" in cols)
        and any("tamara" in c for c in cols | {n.lower()})
    ) or ("TAMARA_" in n and any(c in cols for c in ["captured amount","refund amount","payable to merchant","statement id"])):
        return "TAMARA_PAYOUT"

    # Tabby bulk settlement / merchant payout file.
    if (
        "transferred amount" in cols or "total deduction" in cols or "transfer date" in cols
    ) and any(c in cols for c in ["order number","merchant","merchant name","store"]):
        return "TABBY_PAYOUT"

    # TAP payout/charge file: payout_id and settlement_id are critical.
    if "payout_id" in cols and "settlement_id" in cols:
        return "TAP_PAYOUT"

    # Generic AMEX settlement file can be extended here if payout-level columns exist.
    if "AMEX" in n and any(c in cols for c in ["settlement amount","net amount","merchant id"]):
        return "AMEX_PAYOUT"

    return ""

def normalize_tamara_payout(df,source="Tamara Payout"):
    d=norm_cols(df)
    statement=find(d,["statement id","statement_id","invoice id","invoice"])
    period=find(d,["statement period","period"])
    merchant=find(d,["merchant","merchant name","store","store name"])
    captured=find(d,["captured amount","gross captured","captured"])
    refunded=find(d,["refund amount","refunded amount","refunds"])
    fees=find(d,["fees","commission","fee amount","merchant fees"])
    vat=find(d,["vat","tax","vat amount"])
    payable=find(d,["payable to merchant","payable amount","net payable","settlement amount","amount payable"])
    date=find(d,["payment date","payout date","transfer date","date"])
    rows=[]
    for i,r in d.iterrows():
        pay=amount(r.get(payable)) if payable else np.nan
        if pd.isna(pay): continue
        rows.append({
            "Settlement Source":"TAMARA",
            "Settlement Batch ID":_gl_text(r.get(statement)) if statement else f"TAMARA-{source}-{i+1}",
            "Provider":"TAMARA",
            "Merchant":_gl_text(r.get(merchant)) if merchant else "",
            "Settlement Period":_gl_text(r.get(period)) if period else "",
            "Settlement Date":dt(r.get(date)) if date else pd.NaT,
            "Gross Amount":amount(r.get(captured)) if captured else np.nan,
            "Refund Amount":amount(r.get(refunded)) if refunded else 0.0,
            "Fee Amount":amount(r.get(fees)) if fees else np.nan,
            "VAT Amount":amount(r.get(vat)) if vat else np.nan,
            "Expected Bank Amount":float(pay),
            "Source File":source,
            "Source Row":i+1,
        })
    return pd.DataFrame(rows)

def normalize_tabby_payout(df,source="Tabby Payout"):
    d=norm_cols(df)
    batch=find(d,["payout id","settlement id","bulk settlement id","batch id"])
    merchant=find(d,["merchant","merchant name","store","store name"])
    order=find(d,["order number","order no","order id"])
    transfer=find(d,["transferred amount","transfer amount","net amount","settlement amount"])
    deduction=find(d,["total deduction","deduction","fees","fee amount"])
    date=find(d,["transfer date","payout date","settlement date","date"])
    rows=[]
    # Row-level payout details are rolled into one batch per merchant/date when no explicit batch id exists.
    temp=[]
    for i,r in d.iterrows():
        a=amount(r.get(transfer)) if transfer else np.nan
        if pd.isna(a): continue
        temp.append({
            "_batch":_gl_text(r.get(batch)) if batch else "",
            "Merchant":_gl_text(r.get(merchant)) if merchant else "",
            "Order Number":_gl_text(r.get(order)) if order else "",
            "Settlement Date":dt(r.get(date)) if date else pd.NaT,
            "Transferred Amount":float(a),
            "Deduction":amount(r.get(deduction)) if deduction else 0.0,
            "Source File":source,
            "Source Row":i+1,
        })
    if not temp:return pd.DataFrame()
    t=pd.DataFrame(temp)
    t["_DateKey"]=pd.to_datetime(t["Settlement Date"],errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    t["_GroupKey"]=t.apply(lambda r:r["_batch"] or f"{r['Merchant']}|{r['_DateKey']}",axis=1)
    rows=[]
    for key,g in t.groupby("_GroupKey",dropna=False):
        rows.append({
            "Settlement Source":"TABBY",
            "Settlement Batch ID":str(key),
            "Provider":"TABBY",
            "Merchant":" / ".join(sorted(set(x for x in g["Merchant"].astype(str) if x))),
            "Settlement Period":"",
            "Settlement Date":pd.to_datetime(g["Settlement Date"],errors="coerce").max(),
            "Gross Amount":np.nan,
            "Refund Amount":0.0,
            "Fee Amount":float(pd.to_numeric(g["Deduction"],errors="coerce").fillna(0).sum()),
            "VAT Amount":np.nan,
            "Expected Bank Amount":float(pd.to_numeric(g["Transferred Amount"],errors="coerce").fillna(0).sum()),
            "Order Count":int(g["Order Number"].astype(str).ne("").sum()),
            "Source File":source,
            "Source Row":int(g["Source Row"].min()),
        })
    return pd.DataFrame(rows)

def normalize_tap_payout(df,source="TAP Payout"):
    d=norm_cols(df)
    payout=find(d,["payout_id","payout id"])
    settlement=find(d,["settlement_id","settlement id"])
    amount_col=find(d,["amount","transaction amount","settlement amount"])
    status=find(d,["status"])
    payout_date=find(d,["payout_date","payout date"])
    settlement_date=find(d,["settlement_date","settlement date"])
    auth_col=find(d,["authorization_id","authorization id","auth code"])
    if not payout or not settlement or not amount_col:
        return pd.DataFrame()
    temp=[]
    for i,r in d.iterrows():
        a=amount(r.get(amount_col))
        if pd.isna(a): continue
        pdte=dt(r.get(payout_date)) if payout_date else pd.NaT
        sdte=dt(r.get(settlement_date)) if settlement_date else pd.NaT
        # Defensive preference: if settlement_id carries YYYYMMDD and source date is implausible,
        # derive date from the identifier as audit-supported evidence.
        sid=_gl_text(r.get(settlement))
        m=re.search(r"(20\d{6})",sid)
        id_date=pd.NaT
        if m:
            try:id_date=pd.to_datetime(m.group(1),format="%Y%m%d",errors="coerce")
            except Exception:pass
        if pd.notna(id_date) and (pd.isna(sdte) or abs((sdte-id_date).days)>31):
            sdte=id_date
        temp.append({
            "Payout ID":_gl_text(r.get(payout)),
            "Settlement ID":sid,
            "Settlement Date":sdte,
            "Payout Date":pdte,
            "Amount":float(a),
            "Status":_gl_text(r.get(status)) if status else "",
            "Auth Code":auth(r.get(auth_col)) if auth_col else "",
            "Source File":source,
            "Source Row":i+1,
        })
    if not temp:return pd.DataFrame()
    t=pd.DataFrame(temp)
    rows=[]
    for pid,g in t.groupby("Payout ID",dropna=False):
        rows.append({
            "Settlement Source":"TAP",
            "Settlement Batch ID":str(pid),
            "Provider":"TAP",
            "Merchant":"",
            "Settlement Period":"",
            "Settlement Date":pd.to_datetime(g["Settlement Date"],errors="coerce").max(),
            "Gross Amount":float(pd.to_numeric(g["Amount"],errors="coerce").fillna(0).sum()),
            "Refund Amount":0.0,
            "Fee Amount":np.nan,
            "VAT Amount":np.nan,
            "Expected Bank Amount":float(pd.to_numeric(g["Amount"],errors="coerce").fillna(0).sum()),
            "Charge Count":len(g),
            "Source File":source,
            "Source Row":int(g["Source Row"].min()),
        })
    return pd.DataFrame(rows)

def build_card_settlement_batches(matched):
    """
    Build ANB card settlement batches from already POS-matched transactions.
    Batch evidence is Store + Terminal + POS Date + Scheme.
    """
    if matched is None or matched.empty:return pd.DataFrame()
    x=matched.copy()
    x=x[x["Payment Type"].apply(_norm_payment).isin(["MADA","VISA","MASTERCARD","AMEX"])].copy()
    if x.empty:return pd.DataFrame()
    x["Payment Type"]=x["Payment Type"].apply(_norm_payment)
    x["Settlement Date"]=pd.to_datetime(x.get("POS Date",x.get("Date")),errors="coerce").dt.normalize()
    x["Terminal ID"]=x.get("Terminal ID","").fillna("").astype(str).str.strip()
    x["Merchant ID"]=x.get("Merchant ID","").fillna("").astype(str).str.strip() if "Merchant ID" in x.columns else ""
    x["Expected Net"]=pd.to_numeric(x.get("Net Amount",x.get("POS Amount",0)),errors="coerce").fillna(0.0)
    rows=[]
    for (store,terminal,dtv,pay),g in x.groupby(["Store Code","Terminal ID","Settlement Date","Payment Type"],dropna=False):
        if pd.isna(dtv): continue
        key=f"ANB|{store}|{terminal}|{dtv:%Y-%m-%d}|{pay}"
        rows.append({
            "Settlement Source":"ANB POS" if pay!="AMEX" else "AMEX",
            "Settlement Batch ID":hashlib.sha1(key.encode()).hexdigest()[:20],
            "Provider":"ANB POS" if pay!="AMEX" else "AMEX",
            "Store Code":str(store),
            "Merchant":"",
            "Terminal ID":str(terminal),
            "Payment Type":pay,
            "Settlement Date":dtv,
            "Gross Amount":float(pd.to_numeric(g.get("POS Amount",0),errors="coerce").fillna(0).sum()),
            "Refund Amount":0.0,
            "Fee Amount":float(pd.to_numeric(g.get("Commission",0),errors="coerce").fillna(0).sum()),
            "VAT Amount":float(pd.to_numeric(g.get("VAT",0),errors="coerce").fillna(0).sum()),
            "Expected Bank Amount":float(pd.to_numeric(g["Expected Net"],errors="coerce").fillna(0).sum()),
            "Transaction Count":len(g),
            "Underlying IDs":"|".join(g.get("Unique Transaction ID",pd.Series(dtype=str)).astype(str)),
            "Source File":"Matched Reconciliation",
        })
    return pd.DataFrame(rows)

def reconcile_settlement_batches_to_bank(batches,bank,tolerance=1.0,tabby_fixed_fee=5.0):
    """
    Match settlement batches to bank credits. Deterministic evidence only.

    Rules:
      - Exact/approved tolerance amount and plausible bank date.
      - ANB POS prefers narration terminal/scheme evidence when available.
      - Tabby allows a configurable settlement-level fixed fee difference.
      - One bank credit may satisfy one settlement batch; ambiguous candidates stay REVIEW.
    """
    if batches is None or batches.empty:
        return pd.DataFrame(),bank.copy() if bank is not None else pd.DataFrame()
    if bank is None or bank.empty:
        x=batches.copy()
        x["Settlement Status"]="BANK RECEIPT PENDING"
        return x,pd.DataFrame()

    b=bank.copy()
    # Support common normalized names.
    if "Credit" in b.columns:
        b["_Credit"]=pd.to_numeric(b["Credit"],errors="coerce").fillna(0.0)
    elif "Bank Amount" in b.columns:
        b["_Credit"]=pd.to_numeric(b["Bank Amount"],errors="coerce").fillna(0.0)
    else:
        num=find(norm_cols(b),["credit","credit amount","amount cr","amount cr.","bank amount","amount"])
        b["_Credit"]=pd.to_numeric(b[num],errors="coerce").fillna(0.0) if num else 0.0

    if "Bank Date" in b.columns:
        b["_Date"]=pd.to_datetime(b["Bank Date"],errors="coerce")
    elif "Date" in b.columns:
        b["_Date"]=pd.to_datetime(b["Date"],errors="coerce")
    else:
        b["_Date"]=pd.NaT

    used=set();rows=[]
    for _,r in batches.reset_index(drop=True).iterrows():
        exp=float(r.get("Expected Bank Amount",0) or 0)
        provider=str(r.get("Provider","")).upper()
        sdate=pd.to_datetime(r.get("Settlement Date"),errors="coerce")
        terminal=str(r.get("Terminal ID","")).strip()
        pay=_norm_payment(r.get("Payment Type",""))

        pool=b[~b.index.isin(used)].copy()
        if pool.empty:
            cand=pd.DataFrame()
        else:
            # Bank receipt can reasonably arrive from same day to +10 days for batch reconciliation.
            cand=pool.copy()
            if pd.notna(sdate):
                dd=(pd.to_datetime(cand["_Date"],errors="coerce").dt.normalize()-sdate.normalize()).dt.days
                cand=cand[(dd>=0)&(dd<=10)].copy()

            cand["_DIFF"]=(pd.to_numeric(cand["_Credit"],errors="coerce")-exp).abs()

            # Provider-level expected fee pattern. Tabby observed sample has SAR 5 deduction.
            if provider=="TABBY":
                cand["_DIFF_FEE"]=(pd.to_numeric(cand["_Credit"],errors="coerce")-(exp-tabby_fixed_fee)).abs()
                cand["_BEST_DIFF"]=cand[["_DIFF","_DIFF_FEE"]].min(axis=1)
            else:
                cand["_BEST_DIFF"]=cand["_DIFF"]

            # Narration evidence improves confidence but is not required if the amount/date is unique.
            if terminal and "Narration Terminal ID" in cand.columns:
                term_match=cand["Narration Terminal ID"].astype(str).eq(terminal)
            else:
                term_match=pd.Series(False,index=cand.index)
            if pay and "Narration Scheme" in cand.columns:
                scheme_match=cand["Narration Scheme"].apply(_norm_payment).eq(pay)
            else:
                scheme_match=pd.Series(False,index=cand.index)
            cand["_EvidenceScore"]=term_match.astype(int)*2 + scheme_match.astype(int)

        sel=None;status="BANK RECEIPT PENDING";rule="";diff=np.nan
        if not cand.empty:
            within=cand[cand["_BEST_DIFF"]<=float(tolerance)].copy()
            if len(within)>1:
                mx=within["_EvidenceScore"].max()
                best=within[within["_EvidenceScore"]==mx]
                if len(best)==1 and mx>0:
                    sel=best.iloc[0]
            elif len(within)==1:
                sel=within.iloc[0]

            if sel is not None:
                used.add(sel.name)
                actual=float(sel["_Credit"])
                raw_diff=round(actual-exp,2)
                if provider=="TABBY" and abs(actual-(exp-tabby_fixed_fee))<=float(tolerance):
                    status="BANK RECEIVED"
                    rule=f"TABBY Payout - Fixed Fee SAR {tabby_fixed_fee:.2f} - Bank Credit"
                    diff=round(actual-(exp-tabby_fixed_fee),2)
                else:
                    status="BANK RECEIVED"
                    rule="Settlement Batch + Bank Credit"
                    diff=raw_diff
            elif len(within)>1:
                status="BANK REVIEW REQUIRED";rule="Multiple bank credits satisfy settlement batch"

        rec=r.to_dict()
        rec.update({
            "Settlement Status":status,
            "Bank Match Rule":rule,
            "Actual Bank Amount":float(sel["_Credit"]) if sel is not None else np.nan,
            "Bank Date":sel["_Date"] if sel is not None else pd.NaT,
            "Bank Difference":diff,
            "Bank Reference":(
                str(sel.get("Narration",sel.get("Reference",""))) if sel is not None else ""
            ),
        })
        rows.append(rec)
    result=pd.DataFrame(rows)
    bank_unmatched=b[~b.index.isin(used)].copy()
    return result,bank_unmatched

def propagate_batch_settlement_to_matched(matched,batch_results):
    """
    Propagate verified batch settlement back to all constituent matched transactions.
    Existing transaction identity and reconciliation evidence are preserved.
    """
    if matched is None or matched.empty:return matched
    out=matched.copy()
    for c,default in [
        ("Settlement Batch ID",""),("Settlement Stage","TRANSACTION MATCHED"),
        ("Provider Settled",False),("Bank Settled",False),("Settlement Match Rule",""),
        ("Settlement Bank Amount",np.nan),("Settlement Bank Date",pd.NaT),
        ("Settlement Bank Reference","")
    ]:
        if c not in out.columns: out[c]=default

    if batch_results is None or batch_results.empty:
        return out

    # ANB/AMEX propagation via Store+Terminal+Date+Payment.
    for _,b in batch_results.iterrows():
        if str(b.get("Settlement Status",""))!="BANK RECEIVED":
            continue
        provider=str(b.get("Provider","")).upper()
        batch_id=str(b.get("Settlement Batch ID",""))
        bank_amt=b.get("Actual Bank Amount",np.nan)
        bank_date=b.get("Bank Date",pd.NaT)
        bank_ref=str(b.get("Bank Reference",""))
        rule=str(b.get("Bank Match Rule",""))

        mask=pd.Series(False,index=out.index)
        if provider in {"ANB POS","AMEX"}:
            d=pd.to_datetime(out.get("POS Date",out.get("Date")),errors="coerce").dt.normalize()
            mask=(
                out["Store Code"].astype(str).eq(str(b.get("Store Code","")))
                & out["Payment Type"].apply(_norm_payment).eq(_norm_payment(b.get("Payment Type","")))
                & d.eq(pd.to_datetime(b.get("Settlement Date"),errors="coerce").normalize())
            )
            if "Terminal ID" in out.columns and str(b.get("Terminal ID","")).strip():
                mask=mask & out["Terminal ID"].astype(str).eq(str(b.get("Terminal ID","")).strip())
        else:
            # Provider payout batches can propagate by provider if the batch contains explicit
            # Underlying IDs; otherwise keep transaction-level settlement unchanged until a
            # stronger linkage is supplied.
            ids=str(b.get("Underlying IDs","")).split("|") if b.get("Underlying IDs") else []
            if ids and "Unique Transaction ID" in out.columns:
                mask=out["Unique Transaction ID"].astype(str).isin(ids)

        if mask.any():
            out.loc[mask,"Settlement Batch ID"]=batch_id
            out.loc[mask,"Settlement Stage"]="BANK RECEIVED"
            out.loc[mask,"Provider Settled"]=True
            out.loc[mask,"Bank Settled"]=True
            out.loc[mask,"Settlement Match Rule"]=rule
            out.loc[mask,"Settlement Bank Amount"]=bank_amt
            out.loc[mask,"Settlement Bank Date"]=bank_date
            out.loc[mask,"Settlement Bank Reference"]=bank_ref
    return out

def settlement_stage_summary(matched):
    if matched is None or matched.empty:return pd.DataFrame()
    x=matched.copy()
    if "Settlement Stage" not in x.columns:
        x["Settlement Stage"]=np.where(x.get("Bank Settled",False),"BANK RECEIVED","TRANSACTION MATCHED")
    rows=[]
    for (store,pay,stage),g in x.groupby(["Store Code","Payment Type","Settlement Stage"],dropna=False):
        rows.append({
            "Store Code":store,"Payment Type":pay,"Settlement Stage":stage,
            "Transactions":len(g),
            "D365 Amount":float(pd.to_numeric(g.get("D365 Amount",0),errors="coerce").fillna(0).sum()),
            "Net Amount":float(pd.to_numeric(g.get("Net Amount",0),errors="coerce").fillna(0).sum()),
        })
    return pd.DataFrame(rows)


def normalize_d365_gl(df, source="D365 GL"):
    """
    Normalize Microsoft D365 General journal account entry exports.

    Exact source columns observed in Finance samples:
      Journal number, Voucher, Date, Year closed, Type, Ledger account,
      Account name, Description, Currency, Amount in transaction currency,
      Amount, Amount in reporting currency.

    No accounting meaning is guessed from sign alone. Signed Amount is retained
    exactly as exported and reversal/correction indicators come from evidence
    such as Description and opposite-sign journal movements.
    """
    d=norm_cols(df)
    journal=find(d,["journal number","journal no","journal"])
    voucher=find(d,["voucher","voucher number"])
    date=find(d,["date","accounting date"])
    ledger=find(d,["ledger account","ledger dimension","account"])
    account_name=find(d,["account name","main account name"])
    desc=find(d,["description","text"])
    currency=find(d,["currency","currency code"])
    amt=find(d,["amount","accounting currency amount","amount in accounting currency"])
    tx_amt=find(d,["amount in transaction currency","transaction currency amount"])
    rpt_amt=find(d,["amount in reporting currency","reporting currency amount"])
    year_closed=find(d,["year closed"])
    typ=find(d,["type","posting type"])

    required=[journal,voucher,date,ledger,amt]
    if not all(required):
        raise ValueError(
            f"{source}: D365 GL export requires Journal number, Voucher, Date, Ledger account and Amount."
        )

    rows=[]
    for i,r in d.iterrows():
        main,store,dimension=_gl_main_store_dimension(r.get(ledger))
        signed=amount(r.get(amt))
        if pd.isna(signed):
            continue
        description=_gl_text(r.get(desc)) if desc else ""
        info=D365_CLEARING_ACCOUNT_MAP.get(main,{})
        rows.append({
            "GL Row":i+1,
            "Source File":source,
            "Journal Number":_gl_text(r.get(journal)),
            "Voucher":_gl_text(r.get(voucher)),
            "GL Date":dt(r.get(date)),
            "Year Closed":_gl_text(r.get(year_closed)) if year_closed else "",
            "Posting Type":_gl_text(r.get(typ)) if typ else "",
            "Ledger Account":dimension,
            "Main Account":main,
            "Store Code":store,
            "Account Name":_gl_text(r.get(account_name)) if account_name else info.get("account_name",""),
            "Description":description,
            "Currency":_gl_text(r.get(currency)) if currency else "",
            "Transaction Currency Amount":amount(r.get(tx_amt)) if tx_amt else np.nan,
            "Signed Amount":float(signed),
            "Absolute Amount":abs(float(signed)),
            "Reporting Currency Amount":amount(r.get(rpt_amt)) if rpt_amt else np.nan,
            "GL Group":info.get("group","UNMAPPED"),
            "Expected Payments":" / ".join(info.get("payments",[])),
            "Sales Order":_gl_sales_order(description),
            "GL Event Type":_gl_event_type(description,signed),
            "Controlled Clearing Account":main in D365_CLEARING_ACCOUNT_MAP,
        })

    out=pd.DataFrame(rows)
    if out.empty:
        return out

    out["GL Period"]=pd.to_datetime(out["GL Date"],errors="coerce").dt.to_period("M").astype(str)
    out["GL Date Key"]=pd.to_datetime(out["GL Date"],errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    out["GL Fingerprint"]=out.apply(
        lambda r: hashlib.sha1(
            f"{r['Journal Number']}|{r['Voucher']}|{r['GL Date Key']}|{r['Ledger Account']}|"
            f"{r['Signed Amount']:.3f}|{r['Description']}".encode()
        ).hexdigest()[:20],axis=1
    )
    out["Duplicate GL Fingerprint"]=out.duplicated("GL Fingerprint",keep=False)

    # Identify exact opposite-sign movements inside the same journal/account/store/amount.
    keycols=["Journal Number","Main Account","Store Code","Absolute Amount"]
    counts=out.groupby(keycols,dropna=False)["Signed Amount"].agg(
        Pos=lambda s:int((s>0).sum()),
        Neg=lambda s:int((s<0).sum())
    ).reset_index()
    counts["Opposite Sign Pair"]=(counts["Pos"]>0)&(counts["Neg"]>0)
    out=out.merge(counts[keycols+["Opposite Sign Pair"]],on=keycols,how="left")
    out["Opposite Sign Pair"]=out["Opposite Sign Pair"].fillna(False)
    out.loc[
        out["Opposite Sign Pair"] &
        ~out["GL Event Type"].isin(["REVERSAL / CORRECTION","STATEMENT DIFFERENCE"]),
        "GL Event Type"
    ]="OFFSET / REVERSAL PAIR"
    return out

def _gl_expected_account_for_tender(payment_type,store_code=""):
    p=_norm_payment(payment_type)
    store=str(store_code).strip()
    if p in {"MADA","VISA","MASTERCARD"}:
        return {"11020907"}
    if p=="AMEX":
        return {"11020901"}
    if p=="CASH":
        return {"11020902"}
    if p=="TABBY":
        return {"11020913"}
    if p=="TAMARA":
        return {"11020922"}
    if p=="TAP":
        # Store 613 online orders are evidenced in the supplied D365 GL
        # through Online Clearing - Tap Gateway (11020908); normal POS TAP
        # continues to use the Finance-confirmed 11020904 clearing account.
        return {"11020904","11020908"} if store=="613" else {"11020904"}
    return set()

def trace_d365_source_to_gl(tender,actual_gl,tolerance=1.0):
    """
    Independent source-to-GL evidence trace.

    Store 613:
      Sales Order is the strongest available key, because the supplied D365 GL
      descriptions explicitly contain "Payment for order SO6-...".

    Other stores:
      Store + expected clearing account + source date + exact amount.
      A unique same-period amount may be shown as REVIEW but never upgraded to
      a deterministic GL match.

    This function does not alter Store Tender or GL records.
    """
    if tender is None or tender.empty:
        return pd.DataFrame(),actual_gl.copy() if actual_gl is not None else pd.DataFrame()
    if actual_gl is None or actual_gl.empty:
        out=tender.copy()
        out["GL Trace Status"]="GL NOT FOUND"
        out["GL Trace Rule"]="No D365 GL data uploaded"
        return out,pd.DataFrame()

    g=actual_gl[actual_gl["Controlled Clearing Account"].fillna(False)].copy()
    used=set()
    rows=[]

    for _,s in tender.reset_index(drop=True).iterrows():
        store=str(s.get("Store Code","")).strip()
        pay=_norm_payment(s.get("D365 Payment",""))
        so=str(s.get("Sales Order","")).strip().upper()
        src_date=pd.to_datetime(s.get("Date"),errors="coerce")
        src_amt=abs(float(pd.to_numeric(pd.Series([s.get("D365 Amount",0)]),errors="coerce").fillna(0).iloc[0]))
        expected_accounts=_gl_expected_account_for_tender(pay,store)

        pool=g[~g.index.isin(used)].copy()
        if expected_accounts:
            account_pool=pool[pool["Main Account"].isin(expected_accounts)].copy()
        else:
            account_pool=pool.copy()
        if store:
            store_pool=account_pool[account_pool["Store Code"].astype(str).eq(store)].copy()
        else:
            store_pool=account_pool.copy()

        sel=None
        status="GL NOT FOUND"
        rule=""
        reason=""

        # Store 613: explicit Sales Order in D365 GL description is primary evidence.
        if store=="613" and so:
            x=pool[pool["Sales Order"].astype(str).str.upper().eq(so)].copy()
            if len(x)==1:
                candidate=x.iloc[0]
                amount_diff=round(src_amt-float(candidate["Absolute Amount"]),2)
                if expected_accounts and candidate["Main Account"] not in expected_accounts:
                    sel=candidate
                    status="GL ACCOUNT MISMATCH"
                    rule="Store 613 Sales Order"
                    reason=f"Sales Order found in GL {candidate['Main Account']}, expected {', '.join(sorted(expected_accounts))}"
                elif abs(amount_diff)<=float(tolerance):
                    sel=candidate
                    status="GL MATCHED"
                    rule="Store 613 Sales Order + Amount"
                else:
                    sel=candidate
                    status="GL AMOUNT MISMATCH"
                    rule="Store 613 Sales Order"
                    reason=f"Source {src_amt:.2f} vs GL {float(candidate['Absolute Amount']):.2f}"
            elif len(x)>1:
                # If Sales Order repeats, amount can safely disambiguate only when unique.
                x["_DIFF"]=(x["Absolute Amount"]-src_amt).abs()
                exact=x[x["_DIFF"]<=float(tolerance)]
                if len(exact)==1:
                    sel=exact.iloc[0]
                    status="GL MATCHED"
                    rule="Store 613 Sales Order + Unique Amount"
                else:
                    status="GL REVIEW REQUIRED"
                    rule="Store 613 Sales Order"
                    reason="Multiple GL candidates for the same Sales Order"

        # Other stores / fallback: store + account + date + amount.
        if sel is None and status=="GL NOT FOUND" and not store_pool.empty:
            x=store_pool.copy()
            x["_DIFF"]=(x["Absolute Amount"]-src_amt).abs()
            if pd.notna(src_date):
                xd=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.normalize()==src_date.normalize()].copy()
            else:
                xd=pd.DataFrame()

            exact=xd[xd["_DIFF"]<=float(tolerance)] if not xd.empty else pd.DataFrame()
            if len(exact)==1:
                sel=exact.iloc[0]
                status="GL MATCHED"
                rule="Store + Clearing Account + Date + Amount"
            elif len(exact)>1:
                status="GL REVIEW REQUIRED"
                rule="Store + Clearing Account + Date + Amount"
                reason="Multiple exact GL candidates"
            else:
                # Period fallback is review only; never deterministic.
                if pd.notna(src_date):
                    xp=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.to_period("M")==src_date.to_period("M")]
                    xp=xp[xp["_DIFF"]<=float(tolerance)]
                    if len(xp)==1:
                        sel=xp.iloc[0]
                        status="GL REVIEW REQUIRED"
                        rule="Store + Clearing Account + Period + Amount"
                        reason="Date differs; unique same-period amount candidate"

        rec={
            "Store Code":store,
            "Source Date":src_date,
            "Receipt ID":str(s.get("Receipt ID","")),
            "Sales Order":str(s.get("Sales Order","")),
            "Auth Code":str(s.get("Auth Code","")),
            "Payment Type":pay,
            "Source Amount":float(s.get("D365 Amount",0) or 0),
            "Expected GL Accounts":" / ".join(sorted(expected_accounts)),
            "GL Trace Status":status,
            "GL Trace Rule":rule,
            "GL Trace Reason":reason,
            "GL Journal Number":"",
            "GL Voucher":"",
            "GL Date":pd.NaT,
            "Actual Main Account":"",
            "Actual Ledger Account":"",
            "Actual GL Amount":np.nan,
            "GL Description":"",
            "GL Source File":"",
            "GL Fingerprint":"",
        }
        if sel is not None:
            used.add(sel.name)
            rec.update({
                "GL Journal Number":sel.get("Journal Number",""),
                "GL Voucher":sel.get("Voucher",""),
                "GL Date":sel.get("GL Date",pd.NaT),
                "Actual Main Account":sel.get("Main Account",""),
                "Actual Ledger Account":sel.get("Ledger Account",""),
                "Actual GL Amount":sel.get("Signed Amount",np.nan),
                "GL Description":sel.get("Description",""),
                "GL Source File":sel.get("Source File",""),
                "GL Fingerprint":sel.get("GL Fingerprint",""),
            })
        rows.append(rec)

    trace=pd.DataFrame(rows)
    gl_only=g[~g.index.isin(used)].copy()
    if not gl_only.empty:
        gl_only["GL Trace Status"]="D365 GL ONLY / SOURCE NOT TRACED"
    return trace,gl_only

def expected_clearing_from_jv(jv):
    """Return only RetailRecon JV clearing lines that should be independently found in D365 GL."""
    if jv is None or jv.empty:
        return pd.DataFrame()
    x=jv.copy()
    main_col="Main Account" if "Main Account" in x.columns else ("Account" if "Account" in x.columns else None)
    if not main_col:
        return pd.DataFrame()
    x["Main Account"]=x[main_col].astype(str).str.strip()
    x=x[x["Main Account"].isin(D365_CLEARING_ACCOUNT_MAP)].copy()
    if x.empty:
        return x
    debit=pd.to_numeric(x.get("Debit",0),errors="coerce").fillna(0.0)
    credit=pd.to_numeric(x.get("Credit",0),errors="coerce").fillna(0.0)
    x["Expected Signed Amount"]=debit-credit
    x["Expected Absolute Amount"]=(debit-credit).abs()
    x["Expected GL Date"]=pd.to_datetime(
        x.get("JV Accounting Date",x.get("Date",pd.NaT)),errors="coerce"
    )
    x["Expected GL Period"]=x["Expected GL Date"].dt.to_period("M").astype(str)
    return x

def reconcile_jv_to_d365_gl(jv,actual_gl,tolerance=1.0):
    """
    Verify RetailRecon's approved/posted clearing lines against actual D365 GL.

    Matching priority:
      1. Captured Voucher + Main Account + Store + Amount
      2. Main Account + Store + Accounting Date + Amount
      3. Same period + amount -> REVIEW only
    """
    exp=expected_clearing_from_jv(jv)
    if exp.empty:
        return pd.DataFrame(),actual_gl.copy() if actual_gl is not None else pd.DataFrame()

    g=actual_gl[actual_gl["Controlled Clearing Account"].fillna(False)].copy() if actual_gl is not None and not actual_gl.empty else pd.DataFrame()
    used=set()
    rows=[]
    for _,e in exp.reset_index(drop=True).iterrows():
        main=str(e.get("Main Account","")).strip()
        store=str(e.get("Store Code",e.get("Default Dimension",""))).strip()
        voucher=str(e.get("Voucher","")).strip()
        d=pd.to_datetime(e.get("Expected GL Date"),errors="coerce")
        a=float(e.get("Expected Absolute Amount",0) or 0)
        pool=g[~g.index.isin(used)].copy() if not g.empty else pd.DataFrame()
        x=pool[(pool["Main Account"]==main)&(pool["Store Code"].astype(str)==store)].copy() if not pool.empty else pd.DataFrame()
        sel=None;status="GL NOT FOUND";rule="";reason=""

        if voucher and not x.empty:
            xv=x[x["Voucher"].astype(str).eq(voucher)].copy()
            if not xv.empty:
                xv["_DIFF"]=(xv["Absolute Amount"]-a).abs()
                exact=xv[xv["_DIFF"]<=float(tolerance)]
                if len(exact)==1:
                    sel=exact.iloc[0];status="GL MATCHED";rule="Voucher + Account + Store + Amount"
                elif len(exact)>1:
                    status="DUPLICATE GL POSTING";rule="Voucher + Account + Store + Amount";reason="Multiple D365 GL lines satisfy the same RetailRecon voucher"

        if sel is None and status=="GL NOT FOUND" and not x.empty and pd.notna(d):
            xd=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.normalize()==d.normalize()].copy()
            xd["_DIFF"]=(xd["Absolute Amount"]-a).abs()
            exact=xd[xd["_DIFF"]<=float(tolerance)]
            if len(exact)==1:
                sel=exact.iloc[0];status="GL MATCHED";rule="Account + Store + Accounting Date + Amount"
            elif len(exact)>1:
                status="GL REVIEW REQUIRED";rule="Account + Store + Accounting Date + Amount";reason="Multiple actual GL candidates"

        if sel is None and status=="GL NOT FOUND" and not x.empty and pd.notna(d):
            xp=x[pd.to_datetime(x["GL Date"],errors="coerce").dt.to_period("M")==d.to_period("M")].copy()
            xp["_DIFF"]=(xp["Absolute Amount"]-a).abs()
            exact=xp[xp["_DIFF"]<=float(tolerance)]
            if len(exact)==1:
                sel=exact.iloc[0];status="GL REVIEW REQUIRED";rule="Account + Store + Period + Amount";reason="Unique amount found but accounting date differs"

        rec={
            "Journal Batch":e.get("Journal Batch",e.get("Journal batch number","")),
            "RetailRecon Voucher":voucher,
            "Store Code":store,
            "Group":e.get("Group",""),
            "Expected Main Account":main,
            "Expected GL Date":d,
            "Expected Debit":float(pd.to_numeric(pd.Series([e.get("Debit",0)]),errors="coerce").fillna(0).iloc[0]),
            "Expected Credit":float(pd.to_numeric(pd.Series([e.get("Credit",0)]),errors="coerce").fillna(0).iloc[0]),
            "Expected Absolute Amount":a,
            "GL Verification Status":status,
            "GL Match Rule":rule,
            "GL Verification Reason":reason,
            "D365 Journal Number":"",
            "D365 Voucher":"",
            "Actual GL Date":pd.NaT,
            "Actual Main Account":"",
            "Actual Ledger Account":"",
            "Actual Signed Amount":np.nan,
            "Actual Absolute Amount":np.nan,
            "Difference":np.nan,
            "D365 Description":"",
            "GL Source File":"",
        }
        if sel is not None:
            used.add(sel.name)
            rec.update({
                "D365 Journal Number":sel.get("Journal Number",""),
                "D365 Voucher":sel.get("Voucher",""),
                "Actual GL Date":sel.get("GL Date",pd.NaT),
                "Actual Main Account":sel.get("Main Account",""),
                "Actual Ledger Account":sel.get("Ledger Account",""),
                "Actual Signed Amount":sel.get("Signed Amount",np.nan),
                "Actual Absolute Amount":sel.get("Absolute Amount",np.nan),
                "Difference":round(a-float(sel.get("Absolute Amount",0)),2),
                "D365 Description":sel.get("Description",""),
                "GL Source File":sel.get("Source File",""),
            })
        rows.append(rec)

    ver=pd.DataFrame(rows)
    residual=g[~g.index.isin(used)].copy() if not g.empty else pd.DataFrame()
    return ver,residual

def d365_gl_clearing_control(actual_gl):
    """
    Clearing-account movement control for the uploaded GL period.

    This is intentionally called 'Net GL Movement' rather than 'Closing Balance'
    because a General Journal Account Entry extract may not contain an opening
    balance or the full historical account population.
    """
    if actual_gl is None or actual_gl.empty:
        return pd.DataFrame()
    g=actual_gl[actual_gl["Controlled Clearing Account"].fillna(False)].copy()
    if g.empty:
        return pd.DataFrame()
    g["GL Date"]=pd.to_datetime(g["GL Date"],errors="coerce")
    g["Positive Movement"]=pd.to_numeric(g["Signed Amount"],errors="coerce").fillna(0).clip(lower=0)
    g["Negative Movement"]=(-pd.to_numeric(g["Signed Amount"],errors="coerce").fillna(0).clip(upper=0))
    today=pd.Timestamp.today().normalize()
    rows=[]
    for (main,store,name,group),x in g.groupby(["Main Account","Store Code","Account Name","GL Group"],dropna=False):
        oldest=x["GL Date"].min()
        newest=x["GL Date"].max()
        rows.append({
            "Main Account":main,
            "Store Code":store,
            "Account Name":name,
            "GL Group":group,
            "Rows":len(x),
            "Positive Movement":round(float(x["Positive Movement"].sum()),2),
            "Negative Movement":round(float(x["Negative Movement"].sum()),2),
            "Net GL Movement":round(float(pd.to_numeric(x["Signed Amount"],errors="coerce").fillna(0).sum()),2),
            "Absolute Activity":round(float(pd.to_numeric(x["Signed Amount"],errors="coerce").fillna(0).abs().sum()),2),
            "Oldest GL Date":oldest,
            "Newest GL Date":newest,
            "Oldest Age Days":max(0,(today-oldest.normalize()).days) if pd.notna(oldest) else np.nan,
            "Reversal / Offset Rows":int(x["GL Event Type"].isin(["REVERSAL / CORRECTION","OFFSET / REVERSAL PAIR","STATEMENT DIFFERENCE"]).sum()),
            "Duplicate Fingerprint Rows":int(x["Duplicate GL Fingerprint"].fillna(False).sum()),
        })
    return pd.DataFrame(rows).sort_values(["Main Account","Store Code"]).reset_index(drop=True)

def build_d365_gl_exceptions(source_trace,jv_verification,gl_only,actual_gl):
    rows=[]
    if source_trace is not None and not source_trace.empty:
        x=source_trace[source_trace["GL Trace Status"]!="GL MATCHED"]
        for _,r in x.iterrows():
            rows.append({
                "Exception Type":r.get("GL Trace Status",""),
                "Control Layer":"SOURCE → GL",
                "Store Code":r.get("Store Code",""),
                "Reference":r.get("Sales Order") or r.get("Receipt ID") or r.get("Auth Code"),
                "Main Account":r.get("Actual Main Account") or r.get("Expected GL Accounts"),
                "Amount":abs(float(r.get("Source Amount",0) or 0)),
                "Date":r.get("Source Date"),
                "Reason":r.get("GL Trace Reason") or r.get("GL Trace Rule"),
                "Voucher":r.get("GL Voucher",""),
            })
    if jv_verification is not None and not jv_verification.empty:
        x=jv_verification[jv_verification["GL Verification Status"]!="GL MATCHED"]
        for _,r in x.iterrows():
            rows.append({
                "Exception Type":r.get("GL Verification Status",""),
                "Control Layer":"JV → GL",
                "Store Code":r.get("Store Code",""),
                "Reference":r.get("Journal Batch",""),
                "Main Account":r.get("Expected Main Account",""),
                "Amount":abs(float(r.get("Expected Absolute Amount",0) or 0)),
                "Date":r.get("Expected GL Date"),
                "Reason":r.get("GL Verification Reason") or r.get("GL Match Rule"),
                "Voucher":r.get("RetailRecon Voucher",""),
            })
    if gl_only is not None and not gl_only.empty:
        for _,r in gl_only.iterrows():
            rows.append({
                "Exception Type":"UNEXPECTED / UNTRACED D365 GL ENTRY",
                "Control Layer":"GL → SOURCE",
                "Store Code":r.get("Store Code",""),
                "Reference":r.get("Sales Order") or r.get("GL Fingerprint"),
                "Main Account":r.get("Main Account",""),
                "Amount":abs(float(r.get("Signed Amount",0) or 0)),
                "Date":r.get("GL Date"),
                "Reason":"Controlled clearing-account entry was not consumed by the current source trace.",
                "Voucher":r.get("Voucher",""),
            })
    if actual_gl is not None and not actual_gl.empty:
        dup=actual_gl[actual_gl["Duplicate GL Fingerprint"].fillna(False)]
        for _,r in dup.iterrows():
            rows.append({
                "Exception Type":"DUPLICATE GL FINGERPRINT",
                "Control Layer":"D365 GL",
                "Store Code":r.get("Store Code",""),
                "Reference":r.get("GL Fingerprint",""),
                "Main Account":r.get("Main Account",""),
                "Amount":abs(float(r.get("Signed Amount",0) or 0)),
                "Date":r.get("GL Date"),
                "Reason":"Same journal/voucher/date/dimension/amount/description fingerprint appears more than once.",
                "Voucher":r.get("Voucher",""),
            })
    out=pd.DataFrame(rows)
    if not out.empty:
        out["Age Days"]=(pd.Timestamp.today().normalize()-pd.to_datetime(out["Date"],errors="coerce").dt.normalize()).dt.days.clip(lower=0)
        out["Priority"]=np.select(
            [
                out["Exception Type"].astype(str).str.contains("DUPLICATE|ACCOUNT MISMATCH",case=False,na=False),
                (pd.to_numeric(out["Amount"],errors="coerce").fillna(0)>=10000) | (out["Age Days"].fillna(0)>7),
            ],
            ["CRITICAL","HIGH"],
            default="REVIEW"
        )
        out=out.sort_values(["Priority","Amount"],ascending=[True,False]).reset_index(drop=True)
    return out


def create_jv(recon,gl=None,commission_master=None,accounting_date=None,period_control=None,from_date=None,to_date=None):
    """
    Final D365 JV logic confirmed with Finance.

    Eligibility:
      Matched + difference <= SAR 1 + bank settled.

    Commission:
      Uses Commission Rate Master transaction-by-transaction.

    Confirmed D365 mapping for MADA:
      Bank       : account type Bank   / 1015
      Commission : account type Ledger / 7231-{store}--Sale
      VAT        : account type Vendor / P0672
      CC Sale    : Ledger / 11020907-{store}---  (MADA + VISA + MASTERCARD)
      AMEX Sale  : Ledger / 11020901-{store}---
      TABBY Sale : Ledger / 11020913-{store}---
      TAMARA Sale: Ledger / 11020922-{store}---
      TAP Sale   : Ledger / 11020904-{store}---

    Description uses Brand + Store/Mall name, e.g. Aigner Tahlia Mall.
    """
    if recon is None or recon.empty:
        return pd.DataFrame()

    # Finance-confirmed chart of accounts is the default; an explicit gl
    # override (e.g. from GL Configuration) is honored on top of it so the
    # config page has real effect, but every value still traces back to a
    # known baseline instead of two independent, driftable sources of truth.
    gl_effective={**D365_JV_DEFAULTS,**(gl or {})}

    e=recon[
        (recon["Status"]=="Matched")
        & (pd.to_numeric(recon["Difference"],errors="coerce").abs()<=1.0)
        & (recon["Bank Settled"]==True)
    ].copy()
    if e.empty:
        return pd.DataFrame()

    # Finance-selected JV source period. The filter is inclusive and applies
    # to the Matched report before any store/payment grouping is performed.
    e["_SourceDate"]=pd.to_datetime(e["Date"],errors="coerce").dt.normalize()
    fd=pd.to_datetime(from_date,errors="coerce") if from_date is not None else pd.NaT
    td=pd.to_datetime(to_date,errors="coerce") if to_date is not None else pd.NaT
    if pd.notna(fd):
        e=e[e["_SourceDate"]>=fd.normalize()].copy()
    if pd.notna(td):
        e=e[e["_SourceDate"]<=td.normalize()].copy()
    if pd.notna(fd) and pd.notna(td) and fd.normalize()>td.normalize():
        raise ValueError("JV From Date cannot be later than JV To Date.")
    if e.empty:
        return pd.DataFrame()

    rate_map,vat_map,method_map=_commission_master_maps(commission_master)

    e["Payment Type"]=e["Payment Type"].apply(_norm_payment)
    e["Group"]=e["Payment Type"].apply(jv_group)

    # One JV per Store + Finance Group for the selected From/To period.
    # If no range was supplied (backward compatibility), use the actual
    # eligible minimum/maximum source dates.
    actual_from=e["_SourceDate"].min()
    actual_to=e["_SourceDate"].max()
    period_from=fd.normalize() if pd.notna(fd) else actual_from
    period_to=td.normalize() if pd.notna(td) else actual_to
    period_label=f"{period_from:%d-%b-%Y} to {period_to:%d-%b-%Y}"
    e["Week"]=period_label  # legacy DB/display column retained for compatibility
    e["_Gross"]=pd.to_numeric(e["D365 Amount"],errors="coerce").fillna(0.0).round(2)
    e["_POSBase"]=pd.to_numeric(e["POS Amount"],errors="coerce").fillna(e["_Gross"]).abs()

    comms=[]; vats=[]; bases=[]; rates=[]
    for _,r in e.iterrows():
        p=_norm_payment(r["Payment Type"])
        method=method_map.get(p,"PROVIDER_ACTUAL")
        rate=rate_map.get(p,np.nan)
        vat_rate=vat_map.get(p,15.0)

        if method=="CONTRACT_RATE" and pd.notna(rate):
            c=round(abs(float(r["_POSBase"])) * float(rate)/100.0, 2)
            v=round(c * float(vat_rate)/100.0, 2)
            bases.append("CONTRACT_RATE"); rates.append(float(rate))
        else:
            c=pd.to_numeric(pd.Series([r.get("Commission",0.0)]),errors="coerce").fillna(0.0).iloc[0]
            v=pd.to_numeric(pd.Series([r.get("VAT",0.0)]),errors="coerce").fillna(0.0).iloc[0]
            c=round(float(c),2); v=round(float(v),2)
            bases.append("PROVIDER_ACTUAL"); rates.append(np.nan)

        comms.append(max(c,0.0)); vats.append(max(v,0.0))

    e["_Approved Commission"]=comms
    e["_Approved VAT"]=vats
    e["_Fee Basis"]=bases
    e["_Rate %"]=rates

    rows=[]
    batch_no=1

    for (store,gp),g in e.groupby(["Store Code","Group"],dropna=False):
        week=period_label
        gross=round(g["_Gross"].sum(),2)
        comm=round(g["_Approved Commission"].sum(),2)
        vat=round(g["_Approved VAT"].sum(),2)
        net=round(gross-comm-vat,2)
        if min(gross,comm,vat,net) < 0:
            continue

        info=_d365_store_info(store)
        store_code=info["store_code"]
        store_name=info["store_name"]
        location=info["location"]
        first_date=pd.to_datetime(g["Date"],errors="coerce").dropna()
        month,year=_d365_month_year(first_date.iloc[0] if not first_date.empty else None)

        batch=f"RR-{store_code}-{gp}-{period_from:%Y%m%d}-{period_to:%Y%m%d}-{batch_no:03d}"
        rate_values=sorted(set(round(float(x),4) for x in g["_Rate %"].dropna().tolist()))
        rate_text=", ".join(f"{x:.2f}%" for x in rate_values)
        fee_basis=" + ".join(sorted(set(g["_Fee Basis"].astype(str))))

        # Final confirmed payment clearing / sales GL mapping.
        # MADA + VISA + MASTERCARD are one CC weekly JV.
        sale_gl_by_group = {
            "CC": gl_effective["CC_GL"],
            "CARD": gl_effective["CC_GL"],  # legacy batches
            "AMEX": gl_effective["AMEX_GL"],
            "TABBY": gl_effective["TABBY_GL"],
            "TAMARA": gl_effective["TAMARA_GL"],
            "TAP": gl_effective["TAP_GL"],
        }
        sale_main = sale_gl_by_group.get(gp)
        if not sale_main:
            # Unknown payment groups must not silently post to a guessed GL.
            continue

        src_dates = pd.to_datetime(g["Date"], errors="coerce").dropna()
        source_date = src_dates.min() if not src_dates.empty else pd.NaT
        source_period = source_date.strftime("%b-%Y") if pd.notna(source_date) else ""

        requested_acc = pd.to_datetime(accounting_date, errors="coerce") if accounting_date is not None else pd.NaT
        if pd.notna(requested_acc):
            jv_accounting_date = requested_acc.normalize()
        elif period_control:
            closed = pd.to_datetime(period_control.get("Closed Through Date",""), errors="coerce")
            next_open = pd.to_datetime(period_control.get("Next Open Date",""), errors="coerce")
            if pd.notna(source_date) and pd.notna(closed) and source_date.normalize() <= closed.normalize() and pd.notna(next_open):
                jv_accounting_date = next_open.normalize()
            else:
                jv_accounting_date = source_date.normalize() if pd.notna(source_date) else (next_open.normalize() if pd.notna(next_open) else pd.Timestamp.today().normalize())
        else:
            jv_accounting_date = source_date.normalize() if pd.notna(source_date) else pd.Timestamp.today().normalize()

        common={
            "Valid":"",
            "Company accounts":gl_effective["COMPANY"],
            "Journal batch number":batch,
            "Store Code":store_code,
            "Store Name":store_name,
            "Brand":store_name.split()[0] if store_name else "",
            "Week":week,
            "JV From Date":period_from,
            "JV To Date":period_to,
            "JV Source Period":period_label,
            "Group":gp,
            "Fee Basis":fee_basis,
            "Rate %":rate_text,
            "Currency":gl_effective["CURRENCY"],
            "Exchange rate":"",
            "Gross Amount":gross,
            "Source Date":source_date,
            "Source Period":source_period,
            "JV Accounting Date":jv_accounting_date,
            "Accounting Period":jv_accounting_date.strftime("%b-%Y") if pd.notna(jv_accounting_date) else "",
            "Carry Forward From Closed Period":bool(pd.notna(source_date) and pd.notna(jv_accounting_date) and source_date.to_period("M") != jv_accounting_date.to_period("M")),
            "Bank Settlement Verified":True,
        }

        rows += [
            {
                **common,
                "Account type":"Bank",
                "Main Account":gl_effective["BANK_ACCOUNT"],
                "Ledger Dimension":gl_effective["BANK_ACCOUNT"],
                "Default Dimension":store_code,
                "Location":location,
                "Brand Dimension":"",
                "Department":"",
                "Debit":net,"Credit":0.0,
                "Description":f"{gp}-Deposited- {store_name} - {period_label}",
            },
            {
                **common,
                "Account type":"Ledger",
                "Main Account":gl_effective["COMMISSION_GL"],
                "Ledger Dimension":_d365_dimension(gl_effective["COMMISSION_GL"],store_code,"Sale"),
                "Default Dimension":store_code,
                "Location":location,
                "Brand Dimension":"",
                "Department":"Sale",
                "Debit":comm,"Credit":0.0,
                "Description":f"{gp}-Commission- {store_name} - {period_label}",
            },
            {
                **common,
                "Account type":"Vendor",
                "Main Account":gl_effective["VAT_VENDOR"],
                "Ledger Dimension":gl_effective["VAT_VENDOR"],
                "Default Dimension":store_code,
                "Location":"604" if store_code=="601" else location,
                "Brand Dimension":"",
                "Department":"Sale",
                "Debit":vat,"Credit":0.0,
                "Description":f"{gp}-VAT- {store_name} - {period_label}",
            },
            {
                **common,
                "Account type":"Ledger",
                "Main Account":sale_main,
                "Ledger Dimension":_d365_dimension(sale_main,store_code),
                "Default Dimension":store_code,
                "Location":location,
                "Brand Dimension":"",
                "Department":"",
                "Debit":0.0,"Credit":gross,
                "Description":f"{gp}-Sale- {store_name} - {period_label}",
            }
        ]
        batch_no += 1

    j=pd.DataFrame(rows)
    if j.empty:
        return j

    # D365 line numbering.
    j["RecId"]=range(1,len(j)+1)
    j["Line number"]=j.groupby("Journal batch number").cumcount()+1
    j["Date"]=pd.to_datetime(j["JV Accounting Date"],errors="coerce").dt.strftime("%d-%b-%y")

    chk=j.groupby("Journal batch number")[["Debit","Credit"]].sum().reset_index()
    chk["Difference"]=(chk["Debit"]-chk["Credit"]).round(2)
    chk["Balanced"]=chk["Difference"].abs()<=0.01
    j=j.merge(chk[["Journal batch number","Difference","Balanced"]],
              on="Journal batch number",how="left")

    j["Approval Status"]="PENDING"
    j["D365 Status"]="NOT POSTED"
    j["Voucher"]=""

    # Immutable snapshot of the GL mapping actually used to build this batch.
    # validate_jv() reads this back per-batch instead of re-loading GL
    # Configuration live, so a later, legitimate change to GL Configuration
    # can never retroactively invalidate (or wrongly re-validate) a JV that
    # was already created under a prior, equally legitimate mapping.
    gl_snapshot_json=json.dumps(gl_effective,sort_keys=True)
    gl_mapping_version=hashlib.sha1(gl_snapshot_json.encode()).hexdigest()[:12]
    j["GL Mapping Snapshot"]=gl_snapshot_json
    j["Mapping Version"]=gl_mapping_version

    # Backward-compatible internal/database aliases.
    # D365 export keeps its official field names, while the shared database
    # and approval/posting pages continue to receive their historical names.
    j["Journal Batch"] = j["Journal batch number"]
    j["Account"] = j["Main Account"]
    j["Narration"] = j["Description"]
    j["Bank Name"] = ""
    j["Bank Settled"] = j["Bank Settlement Verified"]

    return j

def validate_jv(j, gl=None, validated_by="SYSTEM (core.validate_jv)"):
    """
    Hard control gate: validate generated JV lines against the Finance-
    confirmed D365 chart of accounts and dimension format before they may
    be approved or posted.

    Confirmed baseline (Finance, this engagement):
      Bank 1015 | Commission 7231 | VAT Vendor P0672 |
      CC (MADA+VISA+MASTERCARD) 11020907 | AMEX 11020901 |
      TABBY 11020913 | TAMARA 11020922 | TAP 11020904
      Dimensions: "{account}-{store}--Sale" (Commission), "{account}-{store}---" (Sale)

    This recomputes the *expected* account/dimension for every line from
    scratch (from gl_effective + Store Code + Group) and compares it against
    what is actually in the row, rather than re-checking create_jv()'s own
    constants against themselves - so it also catches a future bug in
    create_jv() itself, not just configuration drift.

    Adds two columns, broadcast to every line of a batch:
      "Validation Passed"  bool
      "Validation Errors"  "; "-joined list of failed checks, blank if none
    """
    if j is None or j.empty:
        return j

    fallback_gl={**D365_JV_DEFAULTS,**(gl or {})}

    out=j.copy()
    batch_col="Journal Batch" if "Journal Batch" in out.columns else "Journal batch number"
    errors_by_batch={}
    version_by_batch={}

    for batch,g in out.groupby(batch_col,dropna=False):
        errs=[]

        # Use the mapping snapshot the batch was actually CREATED with, not a
        # freshly-loaded GL Configuration - this is what makes validation
        # immune to GL Configuration changes made after this batch existed.
        # Falls back to the caller-supplied/confirmed mapping only when a
        # batch has no snapshot at all (e.g. hand-built rows in a test).
        snapshot_col="GL Mapping Snapshot"
        if snapshot_col in g.columns and str(g[snapshot_col].iloc[0]).strip():
            try:
                gl_effective={**D365_JV_DEFAULTS,**json.loads(g[snapshot_col].iloc[0])}
            except (ValueError, TypeError):
                gl_effective=fallback_gl
                errs.append("GL Mapping Snapshot on this batch is unreadable; validated against current/fallback mapping instead")
        else:
            gl_effective=fallback_gl

        version_by_batch[batch]=hashlib.sha1(
            json.dumps(gl_effective,sort_keys=True).encode()
        ).hexdigest()[:12]

        sale_gl_by_group={
            "CC": gl_effective["CC_GL"],
            "CARD": gl_effective["CC_GL"],  # legacy batches
            "AMEX": gl_effective["AMEX_GL"],
            "TABBY": gl_effective["TABBY_GL"],
            "TAMARA": gl_effective["TAMARA_GL"],
            "TAP": gl_effective["TAP_GL"],
        }
        valid_sale_accounts=set(sale_gl_by_group.values())
        store_codes=set(g["Store Code"].astype(str).str.strip()) if "Store Code" in g.columns else set()
        store=next(iter(store_codes)) if len(store_codes)==1 else None
        group=str(g["Group"].iloc[0]) if "Group" in g.columns and not g["Group"].empty else ""

        if len(store_codes)!=1:
            errs.append(f"Batch spans {len(store_codes)} store codes, expected exactly 1")

        # Company / Currency consistency
        if "Company accounts" in g.columns and set(g["Company accounts"].astype(str))!={gl_effective["COMPANY"]}:
            errs.append(f"Company accounts must be {gl_effective['COMPANY']!r} on every line")
        if "Currency" in g.columns and set(g["Currency"].astype(str))!={gl_effective["CURRENCY"]}:
            errs.append(f"Currency must be {gl_effective['CURRENCY']!r} on every line")

        acct_type_col="Account type" if "Account type" in g.columns else None
        main_col="Main Account" if "Main Account" in g.columns else "Account"
        dim_col="Ledger Dimension" if "Ledger Dimension" in g.columns else None

        def _lines(kind_check):
            if acct_type_col is None:
                return g.iloc[0:0]
            return g[kind_check(g[acct_type_col].astype(str), g[main_col].astype(str))]

        bank=_lines(lambda t,m: (t=="Bank") & (m==gl_effective["BANK_ACCOUNT"]))
        if len(bank)!=1:
            errs.append(f"Expected exactly 1 Bank line on Main Account {gl_effective['BANK_ACCOUNT']}, found {len(bank)}")
        elif dim_col and bank.iloc[0][dim_col]!=gl_effective["BANK_ACCOUNT"]:
            errs.append(f"Bank line Ledger Dimension must be {gl_effective['BANK_ACCOUNT']!r}, found {bank.iloc[0][dim_col]!r}")

        comm=_lines(lambda t,m: (t=="Ledger") & (m==gl_effective["COMMISSION_GL"]))
        if len(comm)!=1:
            errs.append(f"Expected exactly 1 Commission line on Main Account {gl_effective['COMMISSION_GL']}, found {len(comm)}")
        elif store and dim_col:
            expected=_d365_dimension(gl_effective["COMMISSION_GL"],store,"Sale")
            actual=comm.iloc[0][dim_col]
            if actual!=expected:
                errs.append(f"Commission line dimension must be {expected!r}, found {actual!r}")

        vat=_lines(lambda t,m: (t=="Vendor") & (m==gl_effective["VAT_VENDOR"]))
        if len(vat)!=1:
            errs.append(f"Expected exactly 1 VAT line on Vendor {gl_effective['VAT_VENDOR']}, found {len(vat)}")
        elif dim_col and vat.iloc[0][dim_col]!=gl_effective["VAT_VENDOR"]:
            errs.append(f"VAT line Ledger Dimension must be {gl_effective['VAT_VENDOR']!r}, found {vat.iloc[0][dim_col]!r}")

        sale=_lines(lambda t,m: (t=="Ledger") & (m.isin(valid_sale_accounts)))
        expected_sale_acct=sale_gl_by_group.get(group)
        if len(sale)!=1:
            errs.append(f"Expected exactly 1 Sale line on a confirmed clearing account, found {len(sale)}")
        elif expected_sale_acct is None:
            errs.append(f"Payment Group {group!r} has no confirmed clearing account")
        elif sale.iloc[0][main_col]!=expected_sale_acct:
            errs.append(f"Sale line Main Account must be {expected_sale_acct!r} for Group {group!r}, found {sale.iloc[0][main_col]!r}")
        elif store and dim_col:
            expected=_d365_dimension(expected_sale_acct,store)
            actual=sale.iloc[0][dim_col]
            if actual!=expected:
                errs.append(f"Sale line dimension must be {expected!r}, found {actual!r}")

        # Balance and sign checks, recomputed independently of the "Balanced" column.
        debit=pd.to_numeric(g["Debit"],errors="coerce").fillna(0.0)
        credit=pd.to_numeric(g["Credit"],errors="coerce").fillna(0.0)
        if round(float(debit.sum())-float(credit.sum()),2)!=0.0:
            errs.append("Batch is not balanced (Debit total != Credit total)")
        if (debit<0).any() or (credit<0).any():
            errs.append("Negative Debit/Credit line detected")

        # Store display name must be a real name, not the bare numeric code -
        # otherwise D365 descriptions post with a code instead of a store name.
        if store:
            info=_d365_store_info(store)
            if info["store_name"]==store:
                errs.append(f"No Store display name configured for store {store} (D365_STORE_DISPLAY)")

        errors_by_batch[batch]="; ".join(errs)

    out["Validation Errors"]=out[batch_col].map(errors_by_batch).fillna("")
    out["Validation Passed"]=out["Validation Errors"]==""
    out["Validation Date"]=datetime.now().isoformat(timespec="seconds")
    out["Validated By/System"]=validated_by
    out["Mapping Version"]=out[batch_col].map(version_by_batch).fillna(out.get("Mapping Version",""))
    return out


def to_excel(sheets):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w:
        for n,d in sheets.items():
            if d is None:d=pd.DataFrame()
            d.to_excel(w,index=False,sheet_name=re.sub(r'[\[\]\*\?/\\:]','_',n)[:31])
    out.seek(0);return out.getvalue()

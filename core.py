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
    out["D365 Duplicate"]=out.duplicated(["Store Code","Auth Code","D365 Payment","D365 Amount"],keep=False)
    out["Unique Transaction ID"]=out.apply(lambda r: hashlib.sha1(
        f"{r['Store Code']}|{r['Date']}|{r['Receipt ID']}|{r['Auth Code']}|{r['D365 Payment']}|{r['D365 Amount']}".encode()
    ).hexdigest()[:20],axis=1)
    return out

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
        # Keep true D365 duplicates as exceptions.
        if s.get("D365 Duplicate",False):
            rr=s.to_dict()
            rr["Reason"]="Duplicate D365 - requires manual review"
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
            rr=s.to_dict()
            rr["Reason"]=reason or "Missing settlement"
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
    return "CARD" if payment in {"MADA","VISA","MASTERCARD"} else payment

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

def create_jv(recon,gl=None,commission_master=None,accounting_date=None,period_control=None):
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

    rate_map,vat_map,method_map=_commission_master_maps(commission_master)

    e["Payment Type"]=e["Payment Type"].apply(_norm_payment)
    e["Week"]=pd.to_datetime(e["Date"],errors="coerce").dt.to_period("W-SUN").astype(str)
    e["Group"]=e["Payment Type"].apply(jv_group)
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

    for (store,week,gp),g in e.groupby(["Store Code","Week","Group"],dropna=False):
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

        batch=f"RR-{store_code}-{week[-5:].replace('-','')}-{batch_no:03d}"
        rate_values=sorted(set(round(float(x),4) for x in g["_Rate %"].dropna().tolist()))
        rate_text=", ".join(f"{x:.2f}%" for x in rate_values)
        fee_basis=" + ".join(sorted(set(g["_Fee Basis"].astype(str))))

        # Final confirmed payment clearing / sales GL mapping.
        # MADA + VISA + MASTERCARD are one CC weekly JV.
        sale_gl_by_group = {
            "CARD": gl_effective["CC_GL"],
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
                "Description":_d365_description("BANK",store_name,month,year),
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
                "Description":_d365_description("COMMISSION",store_name,month,year),
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
                "Description":_d365_description("VAT",store_name,month,year),
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
                "Description":_d365_description("SALE",store_name,month,year),
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
            "CARD": gl_effective["CC_GL"],
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

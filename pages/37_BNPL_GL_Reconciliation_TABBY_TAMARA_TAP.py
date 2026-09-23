from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
import auth, theme

st.set_page_config(page_title="BNPL & GL Reconciliation", page_icon="🧾", layout="wide")
auth.require_login({"Admin", "Finance Manager", "Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "BNPL & GL Reconciliation"), unsafe_allow_html=True)

AMOUNT_TOLERANCE = 0.02
BANK_TOLERANCE = 0.05

STORE_NAME_TO_CODE = {
    "AIGNER - TAHLIA MALL": "601",
    "AIGNER - TAHLIAH MALL": "601",
    "AIGNER - FAISALIAH MALL": "602",
    "AIGNER - RED SEA MALL": "603",
    "AIGNER - RIYADH PARK": "606",
    "AIGNER - RASHID MALL": "609",
    "AIGNER KSA - ONLINE": "613",
    "AIGNER - ONLINE": "613",
    "AIGNER - MALL OF ARABIA": "619",
    "AIGNER - HAYAT MALL": "624",
    "AIGNER - SOLITAIRE MALL": "634",
    "AIGNER - KINGDOM TOWER BRANCH 3": "643",
    "AIGNER - NAKHEEL MALL": "644",
}

def clean_text(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()

def clean_code(v) -> str:
    s = clean_text(v)
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]
    return s

def norm_ref(v) -> str:
    s = clean_text(v).upper()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]
    s = re.sub(r"[^A-Z0-9]", "", s)
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s

def num(v) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        s = str(v).replace(",", "").replace("SAR", "").strip()
        s = re.sub(r"[^\d\.\-\(\)]", "", s)
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return float(s)
    except Exception:
        return 0.0

def parse_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return pd.NaT
    if isinstance(v, (int, float)) and 30000 <= float(v) <= 70000:
        return pd.to_datetime(float(v), unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(v, errors="coerce", dayfirst=True)

def norm_store_name(v) -> str:
    return re.sub(r"\s+", " ", clean_text(v).upper()).strip()

def store_code_from_name(v) -> str:
    return STORE_NAME_TO_CODE.get(norm_store_name(v), "")

def find_col(df: pd.DataFrame, aliases: list[str]) -> Optional[str]:
    lookup = {re.sub(r"[^A-Z0-9]", "", str(c).upper()): c for c in df.columns}
    for a in aliases:
        k = re.sub(r"[^A-Z0-9]", "", a.upper())
        if k in lookup:
            return lookup[k]
    return None

def read_excel_sheets(uploaded) -> list[tuple[str, pd.DataFrame]]:
    uploaded.seek(0)
    xls = pd.ExcelFile(uploaded)
    out = []
    for sn in xls.sheet_names:
        try:
            uploaded.seek(0)
            raw = pd.read_excel(uploaded, sheet_name=sn, header=None)
            out.append((sn, raw))
        except Exception:
            pass
    return out

def detect_header(raw: pd.DataFrame, keyword_sets: list[set[str]], max_rows=50) -> Optional[int]:
    best_i, best_score = None, 0
    for i in range(min(max_rows, len(raw))):
        vals = {
            re.sub(r"[^A-Z0-9]", "", str(v).upper())
            for v in raw.iloc[i].tolist()
            if pd.notna(v) and str(v).strip()
        }
        score = max((len(vals.intersection(k)) for k in keyword_sets), default=0)
        if score > best_score:
            best_i, best_score = i, score
    return best_i if best_score >= 2 else None

def read_with_detected_header(uploaded, keyword_sets, max_rows=50) -> list[tuple[str, pd.DataFrame]]:
    frames = []
    for sn, raw in read_excel_sheets(uploaded):
        hi = detect_header(raw, keyword_sets, max_rows=max_rows)
        if hi is None:
            continue
        uploaded.seek(0)
        try:
            df = pd.read_excel(uploaded, sheet_name=sn, header=hi)
            df = df.dropna(how="all")
            if not df.empty:
                frames.append((sn, df))
        except Exception:
            pass
    return frames

# ---------------- Provider parsers ----------------

def parse_tabby(uploaded) -> pd.DataFrame:
    keyword_sets = [{
        "ORDERNUMBER", "SALEREFUNDDATE", "MERCHANTNAME", "ORDERTYPE",
        "ORDERAMOUNT", "TOTALFEE", "VATAMOUNT", "TRANSFERREDAMOUNT", "TRANSFERDATE"
    }]
    frames = read_with_detected_header(uploaded, keyword_sets)
    rows = []
    for sn, df in frames:
        order = find_col(df, ["Order Number"])
        dt = find_col(df, ["Sale/Refund Date"])
        merchant = find_col(df, ["Merchant Name"])
        merchant_code = find_col(df, ["Merchant Code"])
        typ = find_col(df, ["Order Type", "Type"])
        amt = find_col(df, ["Order Amount"])
        fee = find_col(df, ["Total Fee"])
        vat = find_col(df, ["VAT Amount"])
        deduction = find_col(df, ["Total Deduction"])
        net = find_col(df, ["Transferred amount", "Transferred Amount"])
        transfer_date = find_col(df, ["Transfer Date"])
        if not order or not amt:
            continue
        for _, r in df.iterrows():
            ref = clean_text(r.get(order))
            if not ref:
                continue
            event = clean_text(r.get(typ)).upper()
            gross = num(r.get(amt))
            sign = -1.0 if "REFUND" in event else 1.0
            rows.append({
                "Provider": "TABBY",
                "Provider Reference": ref,
                "Reference Key": norm_ref(ref),
                "Transaction Date": parse_date(r.get(dt)) if dt else pd.NaT,
                "Store Code": "",
                "Store Name": clean_text(r.get(merchant)) if merchant else "",
                "Merchant Code": clean_text(r.get(merchant_code)) if merchant_code else "",
                "Event": event or "SALE",
                "Gross Amount": sign * abs(gross),
                "Provider Fee": sign * abs(num(r.get(fee))) if fee else 0.0,
                "Provider VAT": sign * abs(num(r.get(vat))) if vat else 0.0,
                "Total Deduction": sign * abs(num(r.get(deduction))) if deduction else 0.0,
                "Net Settlement": sign * abs(num(r.get(net))) if net else 0.0,
                "Settlement Date": parse_date(r.get(transfer_date)) if transfer_date else pd.NaT,
                "Source": uploaded.name,
            })
    return pd.DataFrame(rows)

def parse_tamara(uploaded) -> pd.DataFrame:
    keyword_sets = [{
        "TRANSACTIONDATEDDMMYYYY", "TAMARAORDERID", "MERCHANTORDERID",
        "MERCHANTORDERNUMBER", "STORECODE", "ORDERAMOUNT", "EVENT",
        "TOTALFEES", "VATCOLLECTEDBYTAMARA", "TOTALPAYABLETOMERCHANT"
    }]
    frames = read_with_detected_header(uploaded, keyword_sets)
    rows = []
    for sn, df in frames:
        tx_date = find_col(df, ["Transaction Date DD/MM/YYYY", "Transaction Date"])
        order_id = find_col(df, ["Tamara Order ID"])
        merchant_order = find_col(df, ["Merchant Order ID", "Merchant Order Number"])
        store = find_col(df, ["Store Code"])
        order_amt = find_col(df, ["Order Amount"])
        event = find_col(df, ["Event"])
        event_amt = find_col(df, ["Event Amount"])
        event_date = find_col(df, ["Event Date DD/MM/YYYY", "Event Date"])
        fixed = find_col(df, ["Tamara Fixed Fees"])
        variable = find_col(df, ["Tamara Variable Fees"])
        total_fee = find_col(df, ["Total Fees"])
        vat = find_col(df, ["VAT Collected by Tamara"])
        payable = find_col(df, ["Total Payable to Merchant"])
        if not merchant_order or not order_amt:
            continue

        for _, r in df.iterrows():
            ref = clean_text(r.get(merchant_order))
            if not ref:
                continue
            ev = clean_text(r.get(event)).upper()
            gross_base = num(r.get(event_amt)) if event_amt else num(r.get(order_amt))
            is_refund = "REFUND" in ev
            sign = -1.0 if is_refund else 1.0
            store_raw = clean_text(r.get(store)) if store else ""
            code = clean_code(store_raw) if store_raw.isdigit() else store_code_from_name(store_raw)
            rows.append({
                "Provider": "TAMARA",
                "Provider Reference": ref,
                "Reference Key": norm_ref(ref),
                "Transaction Date": parse_date(r.get(tx_date)) if tx_date else pd.NaT,
                "Store Code": code,
                "Store Name": store_raw,
                "Merchant Code": "",
                "Event": ev or "CAPTURED",
                "Gross Amount": sign * abs(gross_base),
                "Provider Fee": sign * abs(num(r.get(total_fee))) if total_fee else sign * abs(
                    num(r.get(fixed)) + num(r.get(variable))
                ),
                "Provider VAT": sign * abs(num(r.get(vat))) if vat else 0.0,
                "Total Deduction": sign * abs(
                    (num(r.get(total_fee)) if total_fee else num(r.get(fixed)) + num(r.get(variable)))
                    + (num(r.get(vat)) if vat else 0.0)
                ),
                "Net Settlement": sign * abs(num(r.get(payable))) if payable else 0.0,
                "Settlement Date": parse_date(r.get(event_date)) if event_date else pd.NaT,
                "Source": uploaded.name,
            })
    return pd.DataFrame(rows)


def parse_tap(uploaded) -> pd.DataFrame:
    """
    Parse TAP charge/settlement export.

    Confirmed fields in the uploaded TAP reports:
    settlement_id, charge_id, amount, status, authorization_id,
    charge_date, settlement_date, payout_date, reference_transaction,
    reference_order, receipt, payment_method, payment_scheme, merchant_id,
    post_amount, fee, fee_vat and net_amount.

    TAP is a payment gateway rather than BNPL, but it is included on this
    control page so the same POS/D365 -> Provider -> Bank -> GL framework
    can be used without changing the existing RetailRecon core engine.
    """
    keyword_sets = [{
        "SETTLEMENTID", "CHARGEID", "AMOUNT", "STATUS", "AUTHORIZATIONID",
        "CHARGEDATE", "SETTLEMENTDATE", "REFERENCETRANSACTION",
        "REFERENCEORDER", "MERCHANTID", "FEE", "FEEVAT", "NETAMOUNT"
    }]
    frames = read_with_detected_header(uploaded, keyword_sets)
    rows = []

    for sn, df in frames:
        settlement_id = find_col(df, ["settlement_id", "Settlement ID"])
        charge_id = find_col(df, ["charge_id", "Charge ID"])
        amount = find_col(df, ["amount", "Amount"])
        status = find_col(df, ["status", "Status"])
        auth = find_col(df, ["authorization_id", "Authorization ID", "Auth Code"])
        charge_date = find_col(df, ["charge_date", "Charge Date"])
        settlement_date = find_col(df, ["settlement_date", "Settlement Date"])
        payout_date = find_col(df, ["payout_date", "Payout Date"])
        ref_txn = find_col(df, ["reference_transaction", "Reference Transaction"])
        ref_order = find_col(df, ["reference_order", "Reference Order"])
        receipt = find_col(df, ["receipt", "Receipt"])
        merchant_id = find_col(df, ["merchant_id", "Merchant ID"])
        payment_method = find_col(df, ["payment_method", "Payment Method"])
        payment_scheme = find_col(df, ["payment_scheme", "Payment Scheme"])
        post_amount = find_col(df, ["post_amount", "Post Amount"])
        fee = find_col(df, ["fee", "Fee"])
        fee_vat = find_col(df, ["fee_vat", "Fee VAT"])
        net_amount = find_col(df, ["net_amount", "Net Amount"])

        if not amount:
            continue

        for _, r in df.iterrows():
            stat = clean_text(r.get(status)).upper() if status else ""
            # Only captured/successful charge rows are treated as financial transactions.
            if stat and stat not in {"CAPTURED", "SUCCESS", "SUCCEEDED", "PAID"}:
                continue

            # Priority for transaction identity:
            # reference_order -> reference_transaction -> authorization_id -> charge_id.
            ref = ""
            for c in [ref_order, ref_txn, auth, charge_id]:
                if c:
                    candidate = clean_text(r.get(c))
                    if candidate:
                        ref = candidate
                        break

            gross = num(r.get(post_amount)) if post_amount and abs(num(r.get(post_amount))) > 0 else num(r.get(amount))
            fee_value = num(r.get(fee)) if fee else 0.0
            vat_value = num(r.get(fee_vat)) if fee_vat else 0.0
            net_value = num(r.get(net_amount)) if net_amount else gross - fee_value - vat_value

            rows.append({
                "Provider": "TAP",
                "Provider Reference": ref,
                "Reference Key": norm_ref(ref),
                "Transaction Date": parse_date(r.get(charge_date)) if charge_date else pd.NaT,
                "Store Code": "",
                "Store Name": "",
                "Merchant Code": clean_code(r.get(merchant_id)) if merchant_id else "",
                "Event": "CAPTURED",
                "Gross Amount": gross,
                "Provider Fee": fee_value,
                "Provider VAT": vat_value,
                "Total Deduction": fee_value + vat_value,
                "Net Settlement": net_value,
                "Settlement Date": (
                    parse_date(r.get(payout_date)) if payout_date and pd.notna(parse_date(r.get(payout_date)))
                    else parse_date(r.get(settlement_date)) if settlement_date else pd.NaT
                ),
                "Settlement ID": clean_text(r.get(settlement_id)) if settlement_id else "",
                "Charge ID": clean_text(r.get(charge_id)) if charge_id else "",
                "Authorization ID": clean_text(r.get(auth)) if auth else "",
                "Reference Transaction": clean_text(r.get(ref_txn)) if ref_txn else "",
                "Reference Order": clean_text(r.get(ref_order)) if ref_order else "",
                "Receipt": clean_text(r.get(receipt)) if receipt else "",
                "Payment Method": clean_text(r.get(payment_method)) if payment_method else "",
                "Payment Scheme": clean_text(r.get(payment_scheme)) if payment_scheme else "",
                "Source": uploaded.name,
            })

    return pd.DataFrame(rows)


# ---------------- POS / D365 parser ----------------

def parse_pos_d365(uploaded) -> pd.DataFrame:
    keyword_sets = [
        {"STORE", "TRANSDATE", "AUTHCODE", "RECEIPTID"},
        {"STORECODE", "AUTHCODE", "POSTOTAL", "POSTENDER"},
        {"STORE", "TRANSACTIONDATE", "AUTHORIZATIONCODE", "AMOUNT"},
    ]
    frames = read_with_detected_header(uploaded, keyword_sets)
    rows = []
    for sn, df in frames:
        store = find_col(df, ["Store Code", "Store"])
        store_name = find_col(df, ["Store Name"])
        dt = find_col(df, ["Transdate", "Transaction Date", "POS Date", "Date"])
        auth = find_col(df, ["Auth Code", "Authorization Code", "Auth", "Reference"])
        receipt = find_col(df, ["Receiptid", "Receipt ID", "Receipt", "SO / Receipt", "Order Number"])
        tender = find_col(df, ["POS Tender", "Payment Type", "Tender", "Payment Method"])
        amount = find_col(df, ["POS Total", "Amount", "Transaction Amount", "Value of Sales", "Total"])
        if not amount:
            # Classic D365 may have separate tender columns. Unpivot BNPL only.
            for provider, aliases in {
                "TABBY": ["Tabby payment", "TABBY", "Tabby"],
                "TAMARA": ["Tamara", "TAMARA"],
                "TAP": ["Tap Payment", "TAP", "TAPGateway", "Tap Gateway"],
            }.items():
                c = find_col(df, aliases)
                if not c:
                    continue
                for _, r in df.iterrows():
                    a = num(r.get(c))
                    if abs(a) < 0.005:
                        continue
                    ref = clean_text(r.get(auth)) if auth else clean_text(r.get(receipt)) if receipt else ""
                    rows.append({
                        "POS/D365 Date": parse_date(r.get(dt)) if dt else pd.NaT,
                        "Store Code": clean_code(r.get(store)) if store else "",
                        "Store Name": clean_text(r.get(store_name)) if store_name else "",
                        "Payment Type": provider,
                        "Reference": ref,
                        "Reference Key": norm_ref(ref),
                        "Receipt": clean_text(r.get(receipt)) if receipt else "",
                        "POS/D365 Amount": a,
                        "Source": uploaded.name,
                    })
            continue

        for _, r in df.iterrows():
            p = clean_text(r.get(tender)).upper() if tender else ""
            if "TABBY" not in p and "TAMARA" not in p and "TAP" not in p:
                continue
            provider = "TABBY" if "TABBY" in p else ("TAMARA" if "TAMARA" in p else "TAP")
            ref = clean_text(r.get(auth)) if auth else clean_text(r.get(receipt)) if receipt else ""
            rows.append({
                "POS/D365 Date": parse_date(r.get(dt)) if dt else pd.NaT,
                "Store Code": clean_code(r.get(store)) if store else "",
                "Store Name": clean_text(r.get(store_name)) if store_name else "",
                "Payment Type": provider,
                "Reference": ref,
                "Reference Key": norm_ref(ref),
                "Receipt": clean_text(r.get(receipt)) if receipt else "",
                "POS/D365 Amount": num(r.get(amount)),
                "Source": uploaded.name,
            })
    return pd.DataFrame(rows)

# ---------------- Bank parser ----------------

def parse_bank(uploaded) -> pd.DataFrame:
    keyword_sets = [
        {"DATE", "AMOUNT", "NARRATION"},
        {"BANKDATE", "BANKGROSSSAR", "BANKNARRATION"},
        {"TRANSACTIONDATE", "CREDIT", "DESCRIPTION"},
    ]
    frames = read_with_detected_header(uploaded, keyword_sets)
    rows = []
    for sn, df in frames:
        dt = find_col(df, ["Bank Date", "Date", "Transaction Date", "Value Date"])
        narr = find_col(df, ["Bank Narration", "Narration", "Description", "Details", "Remarks"])
        amt = find_col(df, ["Bank Gross SAR", "Amount", "Credit Amount", "Credit", "Deposit"])
        debit = find_col(df, ["Debit", "Debit Amount"])
        credit = find_col(df, ["Credit", "Credit Amount"])
        if not dt or (not amt and not credit):
            continue
        for _, r in df.iterrows():
            value = num(r.get(amt)) if amt else num(r.get(credit))
            if credit and debit:
                value = num(r.get(credit)) - num(r.get(debit))
            if value <= 0:
                continue
            rows.append({
                "Bank Date": parse_date(r.get(dt)),
                "Bank Amount": value,
                "Bank Narration": clean_text(r.get(narr)) if narr else "",
                "Bank Source": uploaded.name,
            })
    return pd.DataFrame(rows)

# ---------------- GL parser ----------------

def parse_gl(uploaded) -> pd.DataFrame:
    keyword_sets = [
        {"ACCOUNT", "DATE", "DEBIT", "CREDIT"},
        {"MAINACCOUNT", "TRANSACTIONDATE", "AMOUNT"},
        {"GLACCOUNT", "VOUCHER", "AMOUNT"},
    ]
    frames = read_with_detected_header(uploaded, keyword_sets)
    rows = []
    for sn, df in frames:
        dt = find_col(df, ["Transaction Date", "Date", "Accounting Date"])
        account = find_col(df, ["Main Account", "Account", "GL Account", "Ledger Account"])
        name = find_col(df, ["Account Name", "Main Account Name", "Description"])
        voucher = find_col(df, ["Voucher", "Voucher Number", "Journal", "Journal Number"])
        text = find_col(df, ["Text", "Description", "Narration", "Transaction Text"])
        debit = find_col(df, ["Debit", "Debit Amount"])
        credit = find_col(df, ["Credit", "Credit Amount"])
        amount = find_col(df, ["Amount", "Accounting Currency Amount", "Amount SAR"])
        if not account or (not amount and not debit and not credit):
            continue
        for _, r in df.iterrows():
            val = num(r.get(amount)) if amount else num(r.get(debit)) - num(r.get(credit))
            rows.append({
                "GL Date": parse_date(r.get(dt)) if dt else pd.NaT,
                "GL Account": clean_text(r.get(account)),
                "GL Account Name": clean_text(r.get(name)) if name else "",
                "Voucher": clean_text(r.get(voucher)) if voucher else "",
                "GL Text": clean_text(r.get(text)) if text else "",
                "GL Amount": val,
                "GL Source": uploaded.name,
            })
    return pd.DataFrame(rows)

# ---------------- Reconciliation ----------------

def reconcile_provider_to_pos(provider: pd.DataFrame, pos: pd.DataFrame) -> pd.DataFrame:
    if provider.empty:
        return pd.DataFrame()
    p = provider.copy().reset_index(drop=True)
    pos = pos.copy().reset_index(drop=True)
    used = set()
    result = []

    for i, r in p.iterrows():
        cand = pos[
            pos["Payment Type"].astype(str).str.upper().eq(r["Provider"])
            & pos["Reference Key"].eq(r["Reference Key"])
            & (pos["POS/D365 Amount"].astype(float).sub(float(r["Gross Amount"])).abs() <= AMOUNT_TOLERANCE)
        ].copy()

        if r["Store Code"]:
            same_store = cand[cand["Store Code"].astype(str).eq(str(r["Store Code"]))]
            if not same_store.empty:
                cand = same_store

        cand = cand[~cand.index.isin(used)]

        status = "Missing in POS/D365"
        matched_idx = None
        if len(cand) == 1:
            matched_idx = int(cand.index[0])
            used.add(matched_idx)
            status = "MATCHED PROVIDER ↔ POS/D365"
        elif len(cand) > 1:
            status = "Review - Multiple POS/D365 Candidates"
        else:
            # Conservative fallback: exact provider + amount + store/date only if unique.
            fallback = pos[
                pos["Payment Type"].astype(str).str.upper().eq(r["Provider"])
                & (pos["POS/D365 Amount"].astype(float).sub(float(r["Gross Amount"])).abs() <= AMOUNT_TOLERANCE)
                & (~pos.index.isin(used))
            ].copy()
            if r["Store Code"]:
                fallback = fallback[fallback["Store Code"].astype(str).eq(str(r["Store Code"]))]
            if pd.notna(r["Transaction Date"]) and "POS/D365 Date" in fallback:
                same_date = fallback[fallback["POS/D365 Date"].dt.date.eq(r["Transaction Date"].date())]
                if not same_date.empty:
                    fallback = same_date
            if len(fallback) == 1:
                matched_idx = int(fallback.index[0])
                used.add(matched_idx)
                status = "MATCHED FALLBACK - UNIQUE STORE/DATE/AMOUNT"

        pr = r.to_dict()
        if matched_idx is not None:
            mr = pos.loc[matched_idx]
            pr.update({
                "POS/D365 Date": mr["POS/D365 Date"],
                "POS/D365 Store": mr["Store Code"],
                "POS/D365 Reference": mr["Reference"],
                "POS/D365 Receipt": mr["Receipt"],
                "POS/D365 Amount": mr["POS/D365 Amount"],
                "POS/D365 Source": mr["Source"],
            })
        else:
            pr.update({
                "POS/D365 Date": pd.NaT,
                "POS/D365 Store": "",
                "POS/D365 Reference": "",
                "POS/D365 Receipt": "",
                "POS/D365 Amount": 0.0,
                "POS/D365 Source": "",
            })
        pr["Sales Match Status"] = status
        pr["Sales Difference"] = round(float(pr["Gross Amount"]) - float(pr["POS/D365 Amount"]), 2)
        result.append(pr)

    return pd.DataFrame(result)

def settlement_groups(provider: pd.DataFrame) -> pd.DataFrame:
    if provider.empty:
        return pd.DataFrame()
    x = provider.copy()
    x["Settlement Date Key"] = x["Settlement Date"].dt.date
    # Tabby gives a transfer date. Tamara statement rows use event date, so aggregate by source
    # to avoid inventing a bank settlement date.
    if "Settlement ID" not in x.columns:
        x["Settlement ID"] = ""

    def _settlement_group_key(r):
        if r["Provider"] == "TAP":
            sid = clean_text(r.get("Settlement ID"))
            if sid:
                return f"TAP|{sid}"
            return f"TAP|{r['Settlement Date Key']}|{r['Source']}"
        if r["Provider"] == "TABBY":
            return f"TABBY|{r['Settlement Date Key']}|{r['Source']}"
        return f"{r['Provider']}|{r['Source']}"

    x["Settlement Group"] = x.apply(_settlement_group_key, axis=1)
    g = x.groupby(["Settlement Group", "Provider", "Source"], dropna=False).agg(
        Gross_Amount=("Gross Amount", "sum"),
        Provider_Fee=("Provider Fee", "sum"),
        Provider_VAT=("Provider VAT", "sum"),
        Expected_Net_Settlement=("Net Settlement", "sum"),
        Settlement_Date=("Settlement Date", "max"),
        Transaction_Count=("Provider Reference", "count"),
    ).reset_index()
    return g

def reconcile_bank(groups: pd.DataFrame, bank: pd.DataFrame) -> pd.DataFrame:
    if groups.empty:
        return pd.DataFrame()
    out = groups.copy()
    out["Bank Date"] = pd.NaT
    out["Bank Amount"] = 0.0
    out["Bank Narration"] = ""
    out["Bank Source"] = ""
    out["Bank Match Status"] = "Bank File Not Uploaded" if bank.empty else "Settlement Not Received"
    out["Bank Difference"] = out["Expected_Net_Settlement"].round(2)
    used = set()

    if bank.empty:
        return out

    for i, r in out.iterrows():
        expected = float(r["Expected_Net_Settlement"])
        cand = bank[
            (~bank.index.isin(used))
            & (bank["Bank Amount"].astype(float).sub(expected).abs() <= BANK_TOLERANCE)
        ].copy()

        if pd.notna(r["Settlement_Date"]):
            cand["Shift"] = (cand["Bank Date"] - r["Settlement_Date"]).dt.days
            dated = cand[cand["Shift"].between(-1, 10, inclusive="both")]
            if not dated.empty:
                cand = dated

        if len(cand) == 1:
            j = int(cand.index[0])
            used.add(j)
            out.at[i, "Bank Date"] = bank.at[j, "Bank Date"]
            out.at[i, "Bank Amount"] = bank.at[j, "Bank Amount"]
            out.at[i, "Bank Narration"] = bank.at[j, "Bank Narration"]
            out.at[i, "Bank Source"] = bank.at[j, "Bank Source"]
            out.at[i, "Bank Match Status"] = "MATCHED BANK SETTLEMENT"
            out.at[i, "Bank Difference"] = round(expected - float(bank.at[j, "Bank Amount"]), 2)
        elif len(cand) > 1:
            out.at[i, "Bank Match Status"] = "Review - Multiple Bank Candidates"

    return out

def gl_summary(gl: pd.DataFrame, provider: pd.DataFrame, bank_rec: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for provider_name in ["TABBY", "TAMARA", "TAP"]:
        p = provider[provider["Provider"].eq(provider_name)] if not provider.empty else pd.DataFrame()
        expected_gross = float(p["Gross Amount"].sum()) if not p.empty else 0.0
        expected_fee = float(p["Provider Fee"].sum()) if not p.empty else 0.0
        expected_vat = float(p["Provider VAT"].sum()) if not p.empty else 0.0
        expected_net = float(p["Net Settlement"].sum()) if not p.empty else 0.0

        if gl.empty:
            gl_provider = pd.DataFrame()
        else:
            mask = (
                gl["GL Text"].astype(str).str.upper().str.contains(provider_name, na=False)
                | gl["GL Account Name"].astype(str).str.upper().str.contains(provider_name, na=False)
            )
            gl_provider = gl[mask].copy()

        gl_total = float(gl_provider["GL Amount"].sum()) if not gl_provider.empty else 0.0
        rows.append({
            "Provider": provider_name,
            "Provider Gross": expected_gross,
            "Provider Fees": expected_fee,
            "Provider VAT": expected_vat,
            "Expected Net Settlement": expected_net,
            "GL Tagged Amount": gl_total,
            "GL Tagged Rows": len(gl_provider),
            "GL Status": (
                "GL File Not Uploaded" if gl.empty
                else "Review GL Mapping" if gl_provider.empty
                else "GL Rows Identified - Review Account Classification"
            ),
        })
    return pd.DataFrame(rows)

# ---------------- UI ----------------

st.title("🧾 BNPL / TAP & GL Reconciliation")
st.caption(
    "Additive RetailRecon control page for TABBY / TAMARA / TAP. "
    "This page does not change core.py or the existing POS reconciliation engine."
)

st.info(
    "Flow: POS/D365 ↔ TABBY/TAMARA/TAP ↔ Bank Settlement ↔ GL. "
    "Matching is conservative: exact normalized reference + exact amount first; "
    "fallback is used only when Store/Date/Amount produces one unique candidate."
)

st.subheader("1. Upload Files")

c1, c2 = st.columns(2)
with c1:
    pos_files = st.file_uploader(
        "POS / D365 files",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="bnpl_pos_files",
    )
    tabby_files = st.file_uploader(
        "TABBY settlement reports",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="bnpl_tabby_files",
    )
    tamara_files = st.file_uploader(
        "TAMARA merchant statements",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="bnpl_tamara_files",
    )
    tap_files = st.file_uploader(
        "TAP charge / settlement reports",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="bnpl_tap_files",
    )
with c2:
    bank_files = st.file_uploader(
        "Bank statements (optional)",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="bnpl_bank_files",
    )
    gl_files = st.file_uploader(
        "GL / Ledger extract (optional)",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="bnpl_gl_files",
    )

if not tabby_files and not tamara_files and not tap_files:
    st.warning("Upload at least one TABBY, TAMARA or TAP provider statement.")
    st.stop()

provider_frames = []
for f in tabby_files or []:
    try:
        x = parse_tabby(f)
        if not x.empty:
            provider_frames.append(x)
    except Exception as e:
        st.error(f"TABBY parser error - {f.name}: {e}")

for f in tamara_files or []:
    try:
        x = parse_tamara(f)
        if not x.empty:
            provider_frames.append(x)
    except Exception as e:
        st.error(f"TAMARA parser error - {f.name}: {e}")

for f in tap_files or []:
    try:
        x = parse_tap(f)
        if not x.empty:
            provider_frames.append(x)
    except Exception as e:
        st.error(f"TAP parser error - {f.name}: {e}")

provider = pd.concat(provider_frames, ignore_index=True) if provider_frames else pd.DataFrame()

if provider.empty:
    st.error("No TABBY/TAMARA/TAP transaction rows were detected in the uploaded provider files.")
    st.stop()

pos_frames = []
for f in pos_files or []:
    try:
        x = parse_pos_d365(f)
        if not x.empty:
            pos_frames.append(x)
    except Exception as e:
        st.error(f"POS/D365 parser error - {f.name}: {e}")
pos = pd.concat(pos_frames, ignore_index=True) if pos_frames else pd.DataFrame()

bank_frames = []
for f in bank_files or []:
    try:
        x = parse_bank(f)
        if not x.empty:
            bank_frames.append(x)
    except Exception as e:
        st.error(f"Bank parser error - {f.name}: {e}")
bank = pd.concat(bank_frames, ignore_index=True) if bank_frames else pd.DataFrame()

gl_frames = []
for f in gl_files or []:
    try:
        x = parse_gl(f)
        if not x.empty:
            gl_frames.append(x)
    except Exception as e:
        st.error(f"GL parser error - {f.name}: {e}")
gl = pd.concat(gl_frames, ignore_index=True) if gl_frames else pd.DataFrame()

st.subheader("2. Provider Control")

p1, p2, p3, p4 = st.columns(4)
p1.metric("Provider Transactions", len(provider))
p2.metric("Gross", f"SAR {provider['Gross Amount'].sum():,.2f}")
p3.metric("Fees + VAT", f"SAR {(provider['Provider Fee'].sum() + provider['Provider VAT'].sum()):,.2f}")
p4.metric("Expected Net", f"SAR {provider['Net Settlement'].sum():,.2f}")

provider_summary = provider.groupby("Provider").agg(
    Transactions=("Provider Reference", "count"),
    Gross=("Gross Amount", "sum"),
    Fees=("Provider Fee", "sum"),
    VAT=("Provider VAT", "sum"),
    Net_Settlement=("Net Settlement", "sum"),
).reset_index()
st.dataframe(provider_summary, use_container_width=True, hide_index=True)

st.subheader("3. POS / D365 ↔ BNPL Provider")

if pos.empty:
    st.warning("POS/D365 file not uploaded or not recognized. Provider data is loaded, but sales reconciliation is pending.")
    sales_rec = provider.copy()
    sales_rec["Sales Match Status"] = "POS/D365 File Not Uploaded"
    sales_rec["POS/D365 Amount"] = 0.0
    sales_rec["Sales Difference"] = sales_rec["Gross Amount"]
else:
    sales_rec = reconcile_provider_to_pos(provider, pos)

matched_sales = int(sales_rec["Sales Match Status"].astype(str).str.startswith("MATCHED").sum())
s1, s2, s3 = st.columns(3)
s1.metric("Matched", matched_sales)
s2.metric("Exceptions", len(sales_rec) - matched_sales)
s3.metric("Match %", f"{(matched_sales / len(sales_rec) * 100 if len(sales_rec) else 0):.2f}%")

st.dataframe(
    sales_rec,
    use_container_width=True,
    hide_index=True,
)

st.subheader("4. BNPL Provider ↔ Bank Settlement")

groups = settlement_groups(provider)
bank_rec = reconcile_bank(groups, bank)
st.dataframe(bank_rec, use_container_width=True, hide_index=True)

if not bank_rec.empty:
    bank_matched = int(bank_rec["Bank Match Status"].eq("MATCHED BANK SETTLEMENT").sum())
    b1, b2, b3 = st.columns(3)
    b1.metric("Settlement Groups", len(bank_rec))
    b2.metric("Bank Matched", bank_matched)
    b3.metric("Bank Exceptions", len(bank_rec) - bank_matched)

st.subheader("5. GL Reconciliation Control")

gl_control = gl_summary(gl, provider, bank_rec)
st.dataframe(gl_control, use_container_width=True, hide_index=True)

if gl.empty:
    st.warning(
        "GL file is not uploaded yet. Upload the ledger extract to identify TABBY/TAMARA GL rows. "
        "Final GL clearing reconciliation requires the BNPL clearing account(s), fee expense account(s), "
        "VAT account and bank account mapping."
    )
else:
    st.info(
        "GL rows are identified conservatively by TABBY/TAMARA text/account-name references. "
        "Use the GL Account Mapping section below to confirm the exact clearing, fee, VAT and bank accounts "
        "before treating the GL control as final."
    )

st.subheader("6. GL Account Mapping")

mapping = pd.DataFrame([
    {"Provider": "TABBY", "Control Type": "BNPL Clearing", "GL Account": "", "Expected Basis": "Gross sales/refunds less settlements"},
    {"Provider": "TABBY", "Control Type": "Commission / Fee", "GL Account": "", "Expected Basis": "Provider Total Fee"},
    {"Provider": "TABBY", "Control Type": "VAT on Fee", "GL Account": "", "Expected Basis": "Provider VAT Amount"},
    {"Provider": "TAMARA", "Control Type": "BNPL Clearing", "GL Account": "", "Expected Basis": "Gross captured/refunded less settlements"},
    {"Provider": "TAMARA", "Control Type": "Commission / Fee", "GL Account": "", "Expected Basis": "Tamara Total Fees"},
    {"Provider": "TAMARA", "Control Type": "VAT on Fee", "GL Account": "", "Expected Basis": "VAT Collected by Tamara"},
    {"Provider": "TAP", "Control Type": "Provider Clearing", "GL Account": "", "Expected Basis": "Gross captured less settlements"},
    {"Provider": "TAP", "Control Type": "Commission / Fee", "GL Account": "", "Expected Basis": "TAP fee"},
    {"Provider": "TAP", "Control Type": "VAT on Fee", "GL Account": "", "Expected Basis": "TAP fee_vat"},
])
edited_mapping = st.data_editor(
    mapping,
    use_container_width=True,
    hide_index=True,
    key="bnpl_gl_account_mapping_v1",
)

st.subheader("7. Exceptions")

exceptions = sales_rec[~sales_rec["Sales Match Status"].astype(str).str.startswith("MATCHED")].copy()
if not bank_rec.empty:
    bank_ex = bank_rec[~bank_rec["Bank Match Status"].eq("MATCHED BANK SETTLEMENT")].copy()
else:
    bank_ex = pd.DataFrame()

e1, e2 = st.columns(2)
with e1:
    st.markdown("**Sales / Provider Exceptions**")
    st.dataframe(exceptions, use_container_width=True, hide_index=True)
with e2:
    st.markdown("**Settlement / Bank Exceptions**")
    st.dataframe(bank_ex, use_container_width=True, hide_index=True)

st.subheader("8. Download Reconciliation Report")

buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    provider.to_excel(writer, sheet_name="Provider Transactions", index=False)
    provider_summary.to_excel(writer, sheet_name="Provider Summary", index=False)
    sales_rec.to_excel(writer, sheet_name="POS Provider Recon", index=False)
    bank_rec.to_excel(writer, sheet_name="Bank Settlement Recon", index=False)
    gl_control.to_excel(writer, sheet_name="GL Control", index=False)
    edited_mapping.to_excel(writer, sheet_name="GL Account Mapping", index=False)
    exceptions.to_excel(writer, sheet_name="Exceptions", index=False)
    if not bank_ex.empty:
        bank_ex.to_excel(writer, sheet_name="Bank Exceptions", index=False)

st.download_button(
    "⬇️ DOWNLOAD BNPL / TAP & GL RECONCILIATION",
    data=buffer.getvalue(),
    file_name="RetailReconAI_BNPL_TAP_GL_Reconciliation.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

st.caption(
    "Additive module only. Existing RetailRecon POS matching/core.py is unchanged. "
    "No ambiguous transaction is force-matched."
)

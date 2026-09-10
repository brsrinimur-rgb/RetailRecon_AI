from __future__ import annotations

import hashlib
import re
import pandas as pd


# Compact D365 TenderCash_Reco export tender columns, in source order.
_COMPACT_TENDER_ORDER = [
    ("AMEX", "AMEX"),
    ("BANK DROP", "CASH"),
    ("CREDIT CARD", "CREDIT_CARD"),
    ("KNET", "MADA"),
    ("LOYALTY CARD BALANCE", "LOYALTY"),
    ("MADA", "MADA"),
    ("TABBY", "TABBY"),
    ("TAMARA", "TAMARA"),
    ("TAP", "TAP"),
    ("TAPGATEWAY", "TAP"),
]


def _canon(v):
    return re.sub(r"[^a-z0-9]+", "", str(v or "").strip().lower())


def is_tender_cash_reco(filename, df):
    """
    Detect the compact D365 FIN TenderCash_Reco format.

    Required evidence:
      filename hint OR compact business-column signature
      + Store + Transdate + Auth Code + multiple Amt columns
      + Ref and/or SO / Receipt
    """
    if df is None or getattr(df, "empty", True):
        return False

    cols = list(df.columns)
    c = {_canon(x): x for x in cols}

    has_store = any(k in c for k in ("store", "storecode"))
    has_date = any(k in c for k in ("transdate", "transactiondate", "date"))
    has_auth = any(k in c for k in ("authcode", "authorizationcode", "approvalcode"))
    amt_cols = [x for x in cols if _canon(x).startswith("amt")]
    has_ref = any(k in c for k in ("ref", "receiptid", "receipt"))
    has_so = any(k in c for k in ("soreceipt", "salesorder", "salesorderno"))

    name_hint = "tendercash_reco" in str(filename or "").lower()
    signature = has_store and has_date and has_auth and len(amt_cols) >= 6 and (has_ref or has_so)

    return bool(signature and (name_hint or len(amt_cols) >= 8))


def normalize_tender_cash_reco(df, core):
    """
    Normalize the compact D365 TenderCash_Reco export to the SAME tender schema
    used by core.reconcile(), without changing core.py.

    Confirmed column meaning from the uploaded D365 format:
      Store
      Transdate
      Auth Code
      Amt ... Amt_10, in this order:
        AMEX, Bank Drop, Credit Card, KNET, Loyalty, MADA,
        TABBY, Tamara, TAP, TAPGateway
      Type
      SO / Receipt  -> Sales Order
      Ref           -> Receipt ID
      Desp          -> descriptive/customer reference

    Generic "Credit Card" cannot safely be called VISA or MASTERCARD at import
    time. It is retained as CREDIT_CARD and can be resolved later only from a
    unique POS Store + Auth + Exact Amount evidence match.
    """
    if not is_tender_cash_reco("", df):
        raise ValueError("Not a recognized D365 TenderCash_Reco compact format.")

    d = core.norm_cols(df)
    cols = list(d.columns)

    store_col = core.find(d, ["store", "store code"])
    date_col = core.find(d, ["transdate", "transaction date", "date"])
    auth_col = core.find(d, ["auth code", "authcode", "authorization code", "approval code"])
    ref_col = core.find(d, ["ref", "receiptid", "receipt id", "receipt"])
    so_col = core.find(d, ["so / receipt", "so receipt", "sales order", "salesorder", "sales order no"])
    type_col = core.find(d, ["type"])
    desc_col = core.find(d, ["desp", "description"])

    if not store_col or not date_col or not auth_col:
        raise ValueError("TenderCash_Reco requires Store, Transdate and Auth Code.")

    amt_cols = [col for col in cols if _canon(col).startswith("amt")]
    if len(amt_cols) < 6:
        raise ValueError("TenderCash_Reco requires the tender Amt columns.")

    # Respect source column order exactly.
    amt_cols = sorted(amt_cols, key=lambda x: cols.index(x))
    tender_map = {}
    for idx, col in enumerate(amt_cols[:len(_COMPACT_TENDER_ORDER)]):
        tender_map[col] = _COMPACT_TENDER_ORDER[idx]

    rows = []
    for i, r in d.iterrows():
        raw_store = "" if pd.isna(r.get(store_col)) else str(r.get(store_col)).strip()
        if not raw_store:
            continue

        sc = core.STORE_MAP.get(raw_store.upper(), raw_store)
        parsed_date = core.dt(r.get(date_col))
        raw_auth = "" if pd.isna(r.get(auth_col)) else str(r.get(auth_col)).strip()
        auth_code = core.auth(r.get(auth_col))

        receipt = ""
        if ref_col and not pd.isna(r.get(ref_col)):
            receipt = str(r.get(ref_col)).strip()

        sales_order = ""
        if so_col and not pd.isna(r.get(so_col)):
            sales_order = str(r.get(so_col)).strip()

        tx_type = ""
        if type_col and not pd.isna(r.get(type_col)):
            tx_type = str(r.get(type_col)).strip()

        desc = ""
        if desc_col and not pd.isna(r.get(desc_col)):
            desc = str(r.get(desc_col)).strip()

        base = {
            "D365 Row": i + 1,
            "Store Code": sc,
            "Date": parsed_date,
            "Receipt ID": receipt,
            "Auth Code": auth_code,
            "D365 Raw Auth Code": raw_auth,
            "Sales Order": sales_order,
            "StoreTender Reference": receipt,
            "SalesDetails Bridge Status": "",
            "SalesDetails Source": "",
            "Tender Format": "D365_TENDERCASH_RECO",
            "D365 Transaction Type": tx_type,
            "D365 Description": desc,
        }

        for amt_col, (_label, payment) in tender_map.items():
            a = core.amount(r.get(amt_col))
            if pd.isna(a) or abs(float(a)) <= 0:
                continue

            rr = base.copy()
            rr["D365 Payment"] = payment
            rr["D365 Amount"] = float(a)
            rr["Original D365 Payment"] = _label

            if payment == "CASH":
                rr["Cash Classification"] = "Cash Sales" if float(a) > 0 else "Cash Refund"
                rr["Cash Amount"] = float(a)

            rows.append(rr)

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    if "Cash Classification" not in out.columns:
        out["Cash Classification"] = ""
    else:
        out["Cash Classification"] = out["Cash Classification"].fillna("")

    if "Cash Amount" not in out.columns:
        out["Cash Amount"] = 0.0
    else:
        out["Cash Amount"] = pd.to_numeric(out["Cash Amount"], errors="coerce").fillna(0.0)

    out["D365 Payment"] = out["D365 Payment"].apply(
        lambda x: x if str(x).upper() == "CREDIT_CARD" else core._norm_payment(x)
    )

    out["D365 Match Key"] = out.apply(
        lambda r: (
            f"{str(r['Store Code']).strip()}|"
            f"{pd.to_datetime(r['Date'], errors='coerce').strftime('%Y-%m-%d') if pd.notna(pd.to_datetime(r['Date'], errors='coerce')) else ''}|"
            f"{core.auth(r['Auth Code'])}|{str(r['D365 Payment']).strip().upper()}|"
            f"{float(r['D365 Amount']):.2f}"
        ),
        axis=1,
    )

    dup_cols = ["Store Code", "Date", "Receipt ID", "Auth Code", "D365 Payment", "D365 Amount"]
    out["D365 Duplicate"] = out.duplicated(dup_cols, keep=False)

    out["Unique Transaction ID"] = out.apply(
        lambda r: hashlib.sha1(
            (
                f"{r['Store Code']}|{r['Date']}|{r['Receipt ID']}|"
                f"{r['Auth Code']}|{r['D365 Payment']}|{r['D365 Amount']}"
            ).encode()
        ).hexdigest()[:20],
        axis=1,
    )
    return out


def resolve_generic_credit_card(tender, pos, core):
    """
    Resolve compact D365 "Credit Card" to VISA or MASTERCARD ONLY when the POS
    evidence is deterministic.

    Required evidence:
      same Store
      same normalized Auth
      exact Amount (<= 0.005)
      POS payment is VISA or MASTERCARD
      exactly one candidate

    No date/amount-only guessing is performed.

    Returns:
      (updated_tender, audit_df)
    """
    if tender is None or tender.empty or pos is None or pos.empty:
        return tender, pd.DataFrame()

    t = tender.copy()
    p = pos.copy()

    if "D365 Payment" not in t.columns:
        return t, pd.DataFrame()

    generic_idx = t.index[
        t["D365 Payment"].fillna("").astype(str).str.upper().eq("CREDIT_CARD")
    ]
    if len(generic_idx) == 0:
        return t, pd.DataFrame()

    p_store = p.get("POS Store", pd.Series("", index=p.index)).fillna("").astype(str).str.strip()
    p_auth = p.get("Auth Code", pd.Series("", index=p.index)).apply(core.auth)
    p_amt = pd.to_numeric(p.get("POS Amount", pd.Series(index=p.index, dtype=float)), errors="coerce")
    p_pay = p.get("POS Payment", pd.Series("", index=p.index)).apply(core._norm_payment)

    audits = []

    for idx in generic_idx:
        r = t.loc[idx]
        store = str(r.get("Store Code", "")).strip()
        auth_code = core.auth(r.get("Auth Code", ""))
        amount = pd.to_numeric(pd.Series([r.get("D365 Amount")]), errors="coerce").iloc[0]

        mask = (
            p_store.eq(store)
            & p_auth.eq(auth_code)
            & (p_amt - float(amount)).abs().le(0.005)
            & p_pay.isin(["VISA", "MASTERCARD"])
        )

        candidates = p[mask]
        status = "UNRESOLVED"
        resolved = ""

        if len(candidates) == 1:
            resolved = core._norm_payment(candidates.iloc[0].get("POS Payment", ""))
            t.at[idx, "D365 Payment"] = resolved
            status = "RESOLVED_EXACT"
        elif len(candidates) > 1:
            # Same-date can disambiguate repeated auth/amount only if unique.
            d365_date = pd.to_datetime(r.get("Date"), errors="coerce")
            if pd.notna(d365_date):
                cdates = pd.to_datetime(candidates.get("POS Date"), errors="coerce")
                same_date = candidates[cdates.dt.normalize().eq(d365_date.normalize())]
                if len(same_date) == 1:
                    resolved = core._norm_payment(same_date.iloc[0].get("POS Payment", ""))
                    t.at[idx, "D365 Payment"] = resolved
                    status = "RESOLVED_EXACT_SAME_DATE"
                else:
                    status = "AMBIGUOUS"
            else:
                status = "AMBIGUOUS"

        audits.append({
            "D365 Index": idx,
            "Store Code": store,
            "Date": r.get("Date"),
            "Receipt ID": r.get("Receipt ID", ""),
            "Auth Code": auth_code,
            "D365 Amount": amount,
            "Original Payment": "CREDIT_CARD",
            "Resolved Payment": resolved,
            "Candidate Count": int(len(candidates)),
            "Resolution Status": status,
            "Rule": "Store + Auth + Exact Amount -> unique VISA/MASTERCARD POS evidence",
        })

    # Rebuild match key/unique ID for resolved rows only; core.reconcile remains untouched.
    for idx in generic_idx:
        if str(t.at[idx, "D365 Payment"]).upper() == "CREDIT_CARD":
            continue
        r = t.loc[idx]
        t.at[idx, "D365 Match Key"] = (
            f"{str(r['Store Code']).strip()}|"
            f"{pd.to_datetime(r['Date'], errors='coerce').strftime('%Y-%m-%d') if pd.notna(pd.to_datetime(r['Date'], errors='coerce')) else ''}|"
            f"{core.auth(r['Auth Code'])}|{core._norm_payment(r['D365 Payment'])}|"
            f"{float(r['D365 Amount']):.2f}"
        )
        t.at[idx, "Unique Transaction ID"] = hashlib.sha1(
            (
                f"{r['Store Code']}|{r['Date']}|{r['Receipt ID']}|"
                f"{r['Auth Code']}|{r['D365 Payment']}|{r['D365 Amount']}"
            ).encode()
        ).hexdigest()[:20]

    return t, pd.DataFrame(audits)

from __future__ import annotations
import re
import pandas as pd

def _norm_ref(value):
    if pd.isna(value):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().strip())

def classify_payment_method_mismatch(unmatched_d365, unmatched_pos, amount_tolerance=0.005):
    """Diagnostic only. Never changes matched rows or core matching."""
    d = pd.DataFrame() if unmatched_d365 is None else unmatched_d365.copy()
    p = pd.DataFrame() if unmatched_pos is None else unmatched_pos.copy()
    if d.empty or p.empty:
        return d, p, pd.DataFrame()

    def pick(df, names):
        return next((n for n in names if n in df.columns), None)

    dc = {
        "ref": pick(d, ["Auth Code","D365 Auth","Authorization"]),
        "amt": pick(d, ["D365 Amount","D365 Total","Amount"]),
        "pay": pick(d, ["D365 Payment","D365 Tender","Payment Type"]),
    }
    pc = {
        "ref": pick(p, ["POS Auth","Auth Code","Provider Reference","Transaction Reference"]),
        "amt": pick(p, ["POS Amount","POS Total","Amount"]),
        "pay": pick(p, ["POS Payment","POS Tender","Payment Type"]),
    }
    if any(v is None for v in list(dc.values()) + list(pc.values())):
        return d, p, pd.DataFrame()

    d["_R"] = d[dc["ref"]].map(_norm_ref)
    p["_R"] = p[pc["ref"]].map(_norm_ref)
    d["_A"] = pd.to_numeric(d[dc["amt"]], errors="coerce")
    p["_A"] = pd.to_numeric(p[pc["amt"]], errors="coerce")
    d["_P"] = d[dc["pay"]].fillna("").astype(str).str.upper().str.strip()
    p["_P"] = p[pc["pay"]].fillna("").astype(str).str.upper().str.strip()

    for frame in (d, p):
        if "Exception Status" not in frame.columns:
            frame["Exception Status"] = ""
        if "Exception Remarks" not in frame.columns:
            frame["Exception Remarks"] = ""

    audit = []
    used_p = set()

    for di, dr in d.iterrows():
        if not dr["_R"] or pd.isna(dr["_A"]) or not dr["_P"]:
            continue
        cand = p[
            p["_R"].eq(dr["_R"])
            & ((p["_A"] - dr["_A"]).abs() <= amount_tolerance)
            & (~p.index.isin(used_p))
        ]
        # Require unique evidence on both sides.
        reverse_d = d[
            d["_R"].eq(dr["_R"])
            & ((d["_A"] - dr["_A"]).abs() <= amount_tolerance)
        ]
        if len(cand) != 1 or len(reverse_d) != 1:
            continue
        pi = cand.index[0]
        pr = cand.loc[pi]
        if not pr["_P"] or pr["_P"] == dr["_P"]:
            continue

        used_p.add(pi)
        amount = float(dr["_A"])
        remark = (
            f"Auth Code and amount matched (SAR {amount:,.2f}), but payment method differs: "
            f"D365 = {dr['_P']}, Provider = {pr['_P']}. "
            "Please verify/correct the payment method in D365 Store Tender."
        )
        for frame, idx in ((d, di), (p, pi)):
            frame.at[idx, "Exception Status"] = "Payment Method Mismatch"
            frame.at[idx, "Exception Remarks"] = remark

        audit.append({
            "Normalized Auth": dr["_R"],
            "Amount": amount,
            "D365 Payment": dr["_P"],
            "Provider Payment": pr["_P"],
            "Status": "Payment Method Mismatch",
            "Remarks": remark,
        })

    return (
        d.drop(columns=["_R","_A","_P"], errors="ignore"),
        p.drop(columns=["_R","_A","_P"], errors="ignore"),
        pd.DataFrame(audit),
    )

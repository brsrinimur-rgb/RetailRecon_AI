from __future__ import annotations

import re
import pandas as pd
import core

# db.py is optional for this page only. If it exists, the production masters
# are used. If it is temporarily absent, the page still loads and reports
# unresolved Store Codes instead of crashing at import time.
try:
    import db
except Exception:
    db = None


def norm(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return re.sub(r"\s+", " ", str(v).strip()).upper()


class _UploadLike:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


def _read_sheets(name, data):
    """Read each physical file independently so core can detect its real header."""
    try:
        return core.read_upload(_UploadLike(name, data)) or {}
    except Exception:
        return {}


def _safe_apply_master(pos, loader_name, apply_name):
    """Apply a production master without allowing a missing db/master to kill the run."""
    if db is None:
        return pos
    try:
        loader = getattr(db, loader_name, None)
        applier = getattr(core, apply_name, None)
        if loader is None or applier is None:
            return pos
        master = loader()
        if master is None:
            return pos
        if hasattr(master, "empty") and master.empty:
            return pos
        return applier(pos, master)
    except Exception:
        return pos


def build_pos_dataset(pos_pairs):
    parts = []

    for name, data in pos_pairs:
        for sheet, df in _read_sheets(name, data).items():
            if df is None or df.empty:
                continue

            # Do not treat provider payout/settlement files as POS transactions.
            try:
                if core.classify_settlement_source(f"{name}-{sheet}", df):
                    continue
            except Exception:
                pass

            forced = None
            try:
                typ = core.classify(f"{name}-{sheet}", df)
                if typ in {"AMEX", "TABBY", "TAMARA", "TAP"}:
                    forced = typ
            except Exception:
                pass

            try:
                n = core.normalize_pos(df, f"{name} [{sheet}]", forced)
            except Exception:
                continue

            if n is not None and not n.empty:
                parts.append(n)

    cols = [
        "merchant_id", "store_code", "provider", "reference", "auth_code",
        "pos_date", "pos_amount", "source_file", "source_row"
    ]
    if not parts:
        return pd.DataFrame(columns=cols)

    pos = pd.concat(parts, ignore_index=True)

    # Same production resolution order as the main POS reconciliation:
    # Store Mapping -> Merchant ID -> Terminal ID, with the strongest
    # terminal mapping applied last.
    pos = _safe_apply_master(pos, "load_store_mapping_master", "apply_store_mapping_master")
    pos = _safe_apply_master(pos, "load_merchant_master", "apply_merchant_master")
    pos = _safe_apply_master(pos, "load_terminal_master", "apply_terminal_master")

    def col(name, default=""):
        if name in pos.columns:
            return pos[name]
        return pd.Series([default] * len(pos), index=pos.index)

    provider = col("Provider").astype(str)
    payment = col("POS Payment").astype(str)
    provider = provider.where(
        provider.str.strip().ne("") & provider.str.lower().ne("nan"),
        payment
    )

    out = pd.DataFrame({
        "merchant_id": col("Merchant ID").map(norm),
        "store_code": col("POS Store").map(norm),
        "provider": provider.map(norm),
        "reference": col("Provider Reference").map(norm),
        "auth_code": col("Auth Code").map(norm),
        "pos_date": pd.to_datetime(col("POS Date"), errors="coerce"),
        "pos_amount": pd.to_numeric(col("POS Amount"), errors="coerce"),
        "source_file": col("Source File").astype(str),
    })

    out["source_row"] = range(2, len(out) + 2)
    return out


def build_gl_dataset(gl_pairs):
    parts = []

    for name, data in gl_pairs:
        for sheet, df in _read_sheets(name, data).items():
            if df is None or df.empty:
                continue
            try:
                n = core.normalize_d365_gl(df, f"{name} [{sheet}]")
            except Exception:
                continue
            if n is not None and not n.empty:
                parts.append(n)

    cols = [
        "merchant_id", "store_code", "provider", "reference", "auth_code",
        "gl_date", "gl_amount", "main_account", "voucher", "journal",
        "source_file", "source_row"
    ]
    if not parts:
        return pd.DataFrame(columns=cols)

    gl = pd.concat(parts, ignore_index=True)

    def col(name, default=""):
        if name in gl.columns:
            return gl[name]
        return pd.Series([default] * len(gl), index=gl.index)

    out = pd.DataFrame({
        "merchant_id": "",
        "store_code": col("Store Code").map(norm),
        "provider": "",
        "reference": col("Sales Order").map(norm),
        "auth_code": "",
        "gl_date": pd.to_datetime(col("GL Date"), errors="coerce"),
        "gl_amount": pd.to_numeric(col("Absolute Amount"), errors="coerce"),
        "main_account": col("Main Account").map(norm),
        "voucher": col("Voucher").map(norm),
        "journal": col("Journal Number").map(norm),
        "source_file": col("Source File").astype(str),
    })
    out["source_row"] = range(2, len(out) + 2)
    return out


def _empty_detail():
    return pd.DataFrame(columns=[
        "POS Row", "Merchant ID", "Store Code", "Provider", "POS Reference",
        "POS Date", "POS Amount", "GL Row", "GL Main Account", "GL Voucher",
        "GL Journal", "GL Date", "GL Amount", "Difference", "Status",
        "Match Rule", "Reason", "GL Source File", "Bucket POS Rows",
        "Bucket GL Rows"
    ])


def reconcile_pos_to_gl(pos, gl, tolerance=0.50):
    """Strict 1:1 matcher retained for audit/testing; bucket mode is recommended."""
    pos = pos.reset_index(drop=True)
    gl = gl.reset_index(drop=True)
    used = set()
    rows = []

    def row_base(p):
        return {
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"],
            "Store Code": p["store_code"], "Provider": p["provider"],
            "POS Reference": p["reference"], "POS Date": p["pos_date"],
            "POS Amount": p["pos_amount"], "GL Row": "",
            "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": pd.NaT, "GL Amount": float("nan"),
            "Difference": float("nan"), "Status": "", "Match Rule": "",
            "Reason": "", "GL Source File": ""
        }

    for _, p in pos.iterrows():
        pool = gl.loc[~gl.index.isin(used)].copy()
        filters = []

        for field in ["merchant_id", "reference", "auth_code", "store_code", "provider"]:
            val = p[field]
            if val:
                x = pool[pool[field].eq(val)]
                if not x.empty:
                    pool = x
                    filters.append(field.replace("_", " ").title())

        if pd.notna(p["pos_date"]):
            gd = pd.to_datetime(pool["gl_date"], errors="coerce")
            x = pool[gd.dt.normalize() == p["pos_date"].normalize()]
            if not x.empty:
                pool = x
                filters.append("Date")

        out = row_base(p)

        if len(pool) == 1 and filters:
            g = pool.iloc[0]
            used.add(g.name)
            pa = pd.to_numeric(pd.Series([p["pos_amount"]]), errors="coerce").iloc[0]
            ga = pd.to_numeric(pd.Series([g["gl_amount"]]), errors="coerce").iloc[0]

            if pd.isna(pa):
                status = "POS DATA INCOMPLETE"
                reason = "POS statement amount is blank/non-numeric."
            elif pd.isna(ga):
                status = "GL NOT POSTED"
                reason = "GL evidence row identified but GL amount is blank."
            elif abs(float(pa) - float(ga)) <= tolerance:
                status = "GL MATCHED"
                reason = "POS Statement Amount equals D365 GL Amount within tolerance."
            else:
                status = "GL AMOUNT EXCEPTION"
                reason = "POS Statement Amount does not equal D365 GL Amount within tolerance."

            out.update({
                "GL Row": g["source_row"], "GL Main Account": g["main_account"],
                "GL Voucher": g["voucher"], "GL Journal": g["journal"],
                "GL Date": g["gl_date"], "GL Amount": ga,
                "Difference": float(pa - ga) if pd.notna(pa) and pd.notna(ga) else float("nan"),
                "Status": status, "Match Rule": " + ".join(filters),
                "Reason": reason, "GL Source File": g["source_file"]
            })
        elif pool.empty:
            out.update({
                "Status": "IDENTIFIER MISMATCH",
                "Reason": "No GL evidence matched the available identifiers."
            })
        else:
            out.update({
                "Status": "GL REVIEW REQUIRED",
                "Match Rule": " + ".join(filters),
                "Reason": "Multiple GL candidates; no deterministic 1:1 evidence selected."
            })
        rows.append(out)

    d = pd.DataFrame(rows) if rows else _empty_detail()
    matched = d[d["Status"] == "GL MATCHED"].copy()
    exc = d[d["Status"] != "GL MATCHED"].copy()

    summary = pd.DataFrame([{
        "POS Rows": len(pos), "GL Rows": len(gl), "GL Matched": len(matched),
        "GL Amount Exceptions": int((d["Status"] == "GL AMOUNT EXCEPTION").sum()),
        "GL Not Posted": int((d["Status"] == "GL NOT POSTED").sum()),
        "Review Required": int((d["Status"] == "GL REVIEW REQUIRED").sum()),
        "Identifier Mismatch": int((d["Status"] == "IDENTIFIER MISMATCH").sum()),
        "POS Data Incomplete": int((d["Status"] == "POS DATA INCOMPLETE").sum()),
        "Unmatched GL Rows": len(gl) - len(used),
        "Tolerance SAR": tolerance,
        "Overall Status": "RECONCILED" if exc.empty else "EXCEPTIONS REQUIRE REVIEW",
        "Match Granularity": "Row-to-row (1:1)"
    }])

    return {
        "detail": d, "matched": matched, "exceptions": exc,
        "unmatched_gl": gl.loc[~gl.index.isin(used)].copy(),
        "summary": summary
    }


def reconcile_pos_to_gl_by_bucket(pos, gl, tolerance=0.50):
    """
    Production matcher: Store Code + Date bucket.

    D365 commonly contains multiple GL lines for one store/day, so a
    deterministic POS-row -> GL-row match is not appropriate. This method
    reconciles the total POS amount against the total GL amount for each
    Store Code + posting Date.
    """
    pos = pos.copy().reset_index(drop=True)
    gl = gl.copy().reset_index(drop=True)

    pos["bucket_date"] = pd.to_datetime(pos["pos_date"], errors="coerce").dt.normalize()
    gl["bucket_date"] = pd.to_datetime(gl["gl_date"], errors="coerce").dt.normalize()
    pos["pos_amount"] = pd.to_numeric(pos["pos_amount"], errors="coerce")
    gl["gl_amount"] = pd.to_numeric(gl["gl_amount"], errors="coerce")

    # Normalize identity strings once.
    pos["store_code"] = pos["store_code"].map(norm)
    gl["store_code"] = gl["store_code"].map(norm)

    pos_valid = pos[
        pos["store_code"].ne("") &
        pos["bucket_date"].notna() &
        pos["pos_amount"].notna()
    ].copy()

    pos_bad = pos.drop(pos_valid.index).copy()

    gl_valid = gl[
        gl["store_code"].ne("") &
        gl["bucket_date"].notna() &
        gl["gl_amount"].notna()
    ].copy()

    pos_bucket = (
        pos_valid.groupby(["store_code", "bucket_date"], as_index=False)
        .agg(pos_count=("pos_amount", "size"), pos_total=("pos_amount", "sum"))
    )
    gl_bucket = (
        gl_valid.groupby(["store_code", "bucket_date"], as_index=False)
        .agg(gl_count=("gl_amount", "size"), gl_total=("gl_amount", "sum"))
    )

    merged = pos_bucket.merge(
        gl_bucket,
        on=["store_code", "bucket_date"],
        how="outer",
        indicator=True
    )

    for c in ["pos_count", "gl_count"]:
        merged[c] = merged[c].fillna(0).astype(int)
    for c in ["pos_total", "gl_total"]:
        merged[c] = merged[c].fillna(0.0)

    merged["bucket_diff"] = merged["pos_total"] - merged["gl_total"]

    def status(row):
        if row["_merge"] == "left_only":
            return "GL NOT POSTED"
        if row["_merge"] == "right_only":
            return "UNMATCHED GL"
        if abs(float(row["bucket_diff"])) <= tolerance:
            return "GL MATCHED"
        return "GL AMOUNT EXCEPTION"

    merged["bucket_status"] = merged.apply(status, axis=1)

    reasons = {
        "GL MATCHED":
            "Sum of POS Amount equals sum of D365 GL Amount for this Store+Date within tolerance.",
        "GL AMOUNT EXCEPTION":
            "Sum of POS Amount does not equal sum of D365 GL Amount for this Store+Date within tolerance.",
        "GL NOT POSTED":
            "POS activity exists for this Store+Date but no D365 GL activity was found.",
        "UNMATCHED GL":
            "D365 GL activity exists for this Store+Date with no corresponding POS statement rows."
    }
    merged["bucket_reason"] = merged["bucket_status"].map(reasons)

    bucket_lookup = merged.set_index(["store_code", "bucket_date"]).to_dict("index")

    rows = []
    for _, p in pos_valid.iterrows():
        b = bucket_lookup[(p["store_code"], p["bucket_date"])]
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"],
            "Store Code": p["store_code"], "Provider": p["provider"],
            "POS Reference": p["reference"], "POS Date": p["pos_date"],
            "POS Amount": p["pos_amount"], "GL Row": "",
            "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": p["bucket_date"], "GL Amount": b["gl_total"],
            "Difference": float(b["bucket_diff"]),
            "Status": b["bucket_status"],
            "Match Rule": "Store Code + Date (Bucket Sum)",
            "Reason": b["bucket_reason"], "GL Source File": "",
            "Bucket POS Rows": int(b["pos_count"]),
            "Bucket GL Rows": int(b["gl_count"])
        })

    for _, p in pos_bad.iterrows():
        if pd.isna(p["pos_amount"]):
            status = "POS DATA INCOMPLETE"
            reason = "POS Amount is blank/non-numeric."
        else:
            status = "IDENTIFIER MISMATCH"
            reason = "Store Code or Date is missing; cannot allocate the POS row to a GL bucket."

        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"],
            "Store Code": p["store_code"], "Provider": p["provider"],
            "POS Reference": p["reference"], "POS Date": p["pos_date"],
            "POS Amount": p["pos_amount"], "GL Row": "",
            "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": pd.NaT, "GL Amount": float("nan"),
            "Difference": float("nan"), "Status": status,
            "Match Rule": "", "Reason": reason, "GL Source File": "",
            "Bucket POS Rows": 0, "Bucket GL Rows": 0
        })

    detail = pd.DataFrame(rows) if rows else _empty_detail()
    matched = detail[detail["Status"] == "GL MATCHED"].copy()
    exceptions = detail[detail["Status"] != "GL MATCHED"].copy()

    unmatched_keys = set(
        map(tuple, merged.loc[
            merged["bucket_status"] == "UNMATCHED GL",
            ["store_code", "bucket_date"]
        ].to_numpy())
    )

    if unmatched_keys:
        gl_valid["_key"] = list(zip(gl_valid["store_code"], gl_valid["bucket_date"]))
        unmatched_gl = gl_valid[gl_valid["_key"].isin(unmatched_keys)].drop(columns="_key")
    else:
        unmatched_gl = gl_valid.iloc[0:0].copy()

    summary = pd.DataFrame([{
        "POS Rows": len(pos),
        "GL Rows": len(gl),
        "GL Matched": len(matched),
        "GL Amount Exceptions": int((detail["Status"] == "GL AMOUNT EXCEPTION").sum()),
        "GL Not Posted": int((detail["Status"] == "GL NOT POSTED").sum()),
        "Review Required": 0,
        "Identifier Mismatch": int((detail["Status"] == "IDENTIFIER MISMATCH").sum()),
        "POS Data Incomplete": int((detail["Status"] == "POS DATA INCOMPLETE").sum()),
        "Unmatched GL Rows": len(unmatched_gl),
        "Tolerance SAR": tolerance,
        "Overall Status": "RECONCILED" if exceptions.empty else "EXCEPTIONS REQUIRE REVIEW",
        "Match Granularity": "Store Code + Date bucket (sum of amounts)"
    }])

    return {
        "detail": detail,
        "matched": matched,
        "exceptions": exceptions,
        "unmatched_gl": unmatched_gl,
        "summary": summary,
        "buckets": merged.sort_values(["store_code", "bucket_date"]).reset_index(drop=True)
    }

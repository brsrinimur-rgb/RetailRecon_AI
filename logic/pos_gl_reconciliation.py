"""
logic/pos_gl_reconciliation.py — FIXED

Root cause of "POS and GL report matching is not working":
  1. pages/35_POS_GL_Reconciliation.py read every uploaded file with a naive
     pd.read_excel(header=0) and concatenated ALL files/sheets into one blob
     before normalizing. Real POS exports (e.g. ANB Details_mada/Details_CC)
     have title rows above the real header, so header=0 grabbed the wrong
     row and produced "Unnamed: 0..N" columns -> normalize_pos found none of
     its aliases (Merchant ID population fell to ~8%, mostly noise).
  2. normalize_gl looked for literal "Merchant ID"/"Store Code"/"Provider"/
     "Auth Code" columns on the GL side. Real D365 "General journal account
     entry" exports do not have those columns at all -- Store Code has to be
     PARSED out of the combined "Ledger account" dimension string
     (e.g. "11020907-601--Sale-10415---" -> store 601). Because that parsing
     never happened, every GL identity field was 100% blank, so every POS
     row's identity filters found nothing to narrow on for GL Rows -- with
     6,542 candidate GL rows still in the pool, `len(pool)==1` was never
     true, so every POS row fell through to "GL REVIEW REQUIRED" and 0 GL
     rows were ever marked used. That exactly matches the reported result:
     0 GL Matched / 5,454 Review Required / 0 Unmatched-GL touched.

Fix: reuse core.py's proven, already-in-production parsers instead of the
narrow reimplementation that caused both bugs --
  - core.read_upload(file)          -> per-sheet header auto-detection
  - core.normalize_pos(df, ...)     -> real POS/provider alias handling,
                                        Store Map resolution, TAP/TABBY/
                                        TAMARA/AMEX provider detection
  - core.normalize_d365_gl(df, ...) -> Ledger Account dimension parsing for
                                        Store Code / Main Account, Sales
                                        Order extraction from Description

reconcile_pos_to_gl() -- the original row-to-row matching algorithm and the
report's column/sheet layout -- is UNCHANGED, kept as a selectable mode.

SECOND PASS (2026-08-27, after checking a real re-run of this fix,
report2/report3): row-to-row matching still produced ~0 GL Matched even
with correct identity fields, because real D365 exports post many GL lines
per store per day, not one -- added reconcile_pos_to_gl_by_bucket(), which
compares SUM(POS Amount) vs SUM(GL Amount) per Store+Date instead. Checking
THAT against the same real re-run surfaced two more real issues, both fixed
here:
  3. A single Store+Date GL bucket can hold CARD, TABBY, TAMARA, CASH, and
     TAP clearing-account lines all at once -- comparing a card-only POS
     total against that combined total produced wild differences. Buckets
     are now keyed by Store + expected D365 clearing account (via
     core._gl_expected_account_for_tender(), the same mapping
     core.trace_d365_source_to_gl() already uses elsewhere in this app),
     not just Store + Date.
  4. Real D365 "General journal account entry" exports can carry
     Sales/COGS/Tax/Discount/Inventory postings under the same Store
     dimension as the clearing lines -- build_gl_dataset() now filters to
     Controlled Clearing Account rows only, the same filter
     core.trace_d365_source_to_gl() and related functions already apply.
"""

from __future__ import annotations
import re
import pandas as pd
import core
import db


def norm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).strip()).upper()


class _UploadLike:
    """Wraps (filename, bytes) so it satisfies core.read_upload()'s file-like
    interface (.name / .getvalue())."""
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


def _sheets_for(name, data):
    try:
        return core.read_upload(_UploadLike(name, data))
    except Exception:
        return {}


def build_pos_dataset(pos_pairs):
    """pos_pairs: list of (filename, bytes). Returns the internal matching
    schema (merchant_id, store_code, provider, reference, auth_code,
    pos_date, pos_amount, source_file, source_row)."""
    parts = []
    for name, data in pos_pairs:
        for sheet, df in _sheets_for(name, data).items():
            if df is None or df.empty:
                continue
            # Skip provider payout/settlement sheets -- those are bank-side
            # evidence, not POS transaction rows, and would corrupt identity
            # matching if normalized as POS transactions.
            try:
                if core.classify_settlement_source(f"{name}-{sheet}", df):
                    continue
            except Exception:
                pass
            typ = None
            try:
                typ = core.classify(f"{name}-{sheet}", df)
            except Exception:
                pass
            forced = typ if typ in {"AMEX", "TABBY", "TAMARA", "TAP"} else None
            try:
                n = core.normalize_pos(df, f"{name} [{sheet}]", forced)
            except Exception:
                continue
            if n is None or n.empty:
                continue
            parts.append(n)

    if not parts:
        return pd.DataFrame(columns=[
            "merchant_id", "store_code", "provider", "reference", "auth_code",
            "pos_date", "pos_amount", "source_file", "source_row"
        ])

    pos = pd.concat(parts, ignore_index=True)

    # Store-resolution chain (identical priority order to
    # pages/1_POS_Reconciliation.py): Store Mapping Master (weakest) ->
    # Merchant ID Master -> Terminal ID Master (strongest, applied last so
    # it always wins). Many real POS/provider exports (e.g. ANB
    # Details_mada/Details_CC) carry no Store column at all -- only a
    # constant company name like "UNITED LUXURY CORP" -- so without this
    # step POS Store never becomes a real D365 Store Code and GL Store Code
    # never has anything to match against, even after the parsing fix
    # above. This reuses the SAME masters already maintained live in pages
    # 14/16/17 and read by page 1's own reconciliation -- nothing new to
    # configure.
    try:
        store_master = db.load_store_mapping_master()
        if not pos.empty and store_master is not None and not store_master.empty:
            pos = core.apply_store_mapping_master(pos, store_master)
    except Exception:
        pass
    try:
        merchant_master = db.load_merchant_master()
        if not pos.empty:
            pos = core.apply_merchant_master(pos, merchant_master)
    except Exception:
        pass
    try:
        terminal_master = db.load_terminal_master()
        if not pos.empty:
            pos = core.apply_terminal_master(pos, terminal_master)
    except Exception:
        pass

    out = pd.DataFrame({
        "merchant_id": pos["Merchant ID"].map(norm),
        "store_code": pos["POS Store"].map(norm),
        "provider": pos["Provider"].where(pos["Provider"].astype(str).str.len() > 0, pos["POS Payment"]).map(norm),
        "reference": pos["Provider Reference"].map(norm),
        "auth_code": pos["Auth Code"].map(norm),
        "pos_date": pd.to_datetime(pos["POS Date"], errors="coerce"),
        "pos_amount": pd.to_numeric(pos["POS Amount"], errors="coerce"),
        "source_file": pos["Source File"],
    })
    out["source_row"] = range(2, len(out) + 2)
    return out


def build_gl_dataset(gl_pairs):
    """gl_pairs: list of (filename, bytes). Returns the internal matching
    schema (merchant_id, store_code, provider, reference, auth_code,
    gl_date, gl_amount, main_account, voucher, journal, source_file,
    source_row)."""
    parts = []
    for name, data in gl_pairs:
        for sheet, df in _sheets_for(name, data).items():
            if df is None or df.empty:
                continue
            try:
                n = core.normalize_d365_gl(df, f"{name} [{sheet}]")
            except Exception:
                continue
            if n is None or n.empty:
                continue
            parts.append(n)

    if not parts:
        return pd.DataFrame(columns=[
            "merchant_id", "store_code", "provider", "reference", "auth_code",
            "gl_date", "gl_amount", "main_account", "voucher", "journal",
            "source_file", "source_row"
        ])

    gl = pd.concat(parts, ignore_index=True)

    # Defensive: real D365 "General journal account entry" exports can carry
    # Sales/COGS/Tax/Discount/Inventory postings under the same Store
    # dimension as the card/provider clearing lines. Only clearing-account
    # rows (core.D365_CLEARING_ACCOUNT_MAP) are ever comparable to a POS/
    # provider statement -- this is the exact same filter
    # core.trace_d365_source_to_gl() and friends already apply
    # (`actual_gl[actual_gl["Controlled Clearing Account"].fillna(False)]`).
    gl = gl[gl["Controlled Clearing Account"].fillna(False)].copy()
    if gl.empty:
        return pd.DataFrame(columns=[
            "merchant_id", "store_code", "provider", "reference", "auth_code",
            "gl_date", "gl_amount", "main_account", "voucher", "journal",
            "source_file", "source_row"
        ])

    out = pd.DataFrame({
        # D365 GL exports carry no merchant_id/provider/auth_code -- left
        # blank on purpose. reconcile_pos_to_gl() already skips any filter
        # whose POS-side value has nothing to match, so this is safe and
        # matches the report's own stated rule ("Merchant ID, Store,
        # Provider, Reference/Auth and Date establish identity" -- Store +
        # Date + Sales Order/Reference are the fields D365 actually has).
        "merchant_id": "",
        "store_code": gl["Store Code"].map(norm),
        "provider": "",
        "reference": gl["Sales Order"].map(norm),
        "auth_code": "",
        "gl_date": pd.to_datetime(gl["GL Date"], errors="coerce"),
        "gl_amount": pd.to_numeric(gl["Absolute Amount"], errors="coerce"),
        "main_account": gl["Main Account"].map(norm),
        "voucher": gl["Voucher"].map(norm),
        "journal": gl["Journal Number"].map(norm),
        "source_file": gl["Source File"],
    })
    out["source_row"] = range(2, len(out) + 2)
    return out


# Kept for backward compatibility / direct unit testing against a single
# already-loaded DataFrame -- no longer used by pages/35 (which now calls
# build_pos_dataset / build_gl_dataset directly on the raw uploaded files,
# since header detection has to happen per-file, before concatenation).
def normalize_pos(df, source_file=""):
    return build_pos_dataset([(source_file or "POS", None)]) if df is None else _legacy_normalize(df, source_file, "pos")


def normalize_gl(df, source_file=""):
    return build_gl_dataset([(source_file or "GL", None)]) if df is None else _legacy_normalize(df, source_file, "gl")


def _legacy_normalize(df, source_file, kind):
    if kind == "pos":
        try:
            n = core.normalize_pos(df, source_file or "POS", None)
        except Exception:
            n = pd.DataFrame()
        if n.empty:
            return pd.DataFrame(columns=["merchant_id", "store_code", "provider", "reference", "auth_code", "pos_date", "pos_amount", "source_file", "source_row"])
        out = pd.DataFrame({
            "merchant_id": n["Merchant ID"].map(norm),
            "store_code": n["POS Store"].map(norm),
            "provider": n["Provider"].map(norm),
            "reference": n["Provider Reference"].map(norm),
            "auth_code": n["Auth Code"].map(norm),
            "pos_date": pd.to_datetime(n["POS Date"], errors="coerce"),
            "pos_amount": pd.to_numeric(n["POS Amount"], errors="coerce"),
            "source_file": n["Source File"],
        })
        out["source_row"] = range(2, len(out) + 2)
        return out
    else:
        try:
            n = core.normalize_d365_gl(df, source_file or "GL")
        except Exception:
            n = pd.DataFrame()
        if n.empty:
            return pd.DataFrame(columns=["merchant_id", "store_code", "provider", "reference", "auth_code", "gl_date", "gl_amount", "main_account", "voucher", "journal", "source_file", "source_row"])
        out = pd.DataFrame({
            "merchant_id": "", "store_code": n["Store Code"].map(norm), "provider": "",
            "reference": n["Sales Order"].map(norm), "auth_code": "",
            "gl_date": pd.to_datetime(n["GL Date"], errors="coerce"),
            "gl_amount": pd.to_numeric(n["Absolute Amount"], errors="coerce"),
            "main_account": n["Main Account"].map(norm), "voucher": n["Voucher"].map(norm),
            "journal": n["Journal Number"].map(norm), "source_file": n["Source File"],
        })
        out["source_row"] = range(2, len(out) + 2)
        return out


def reconcile_pos_to_gl(pos, gl, tolerance=0.50):
    pos = pos.reset_index(drop=True); gl = gl.reset_index(drop=True)
    used = set(); rows = []
    for _, p in pos.iterrows():
        pool = gl.loc[~gl.index.isin(used)].copy()
        filters = []
        for field in ["merchant_id", "reference", "auth_code", "store_code", "provider"]:
            val = p[field]
            if val:
                x = pool[pool[field].eq(val)]
                if not x.empty: pool = x; filters.append(field.replace("_", " ").title())
        if pd.notna(p["pos_date"]):
            x = pool[pd.to_datetime(pool["gl_date"], errors="coerce").dt.normalize() == p["pos_date"].normalize()]
            if not x.empty: pool = x; filters.append("Date")
        if len(pool) == 1 and filters:
            g = pool.iloc[0]; used.add(g.name)
            pa = pd.to_numeric(pd.Series([p["pos_amount"]]), errors="coerce").iloc[0]
            ga = pd.to_numeric(pd.Series([g["gl_amount"]]), errors="coerce").iloc[0]
            if pd.isna(pa): status = "POS DATA INCOMPLETE"
            elif pd.isna(ga): status = "GL NOT POSTED"
            elif abs(float(pa) - float(ga)) <= tolerance: status = "GL MATCHED"
            else: status = "GL AMOUNT EXCEPTION"
            reason = ("POS Statement Amount equals D365 GL Amount within tolerance." if status == "GL MATCHED"
                      else "POS Statement Amount does not equal D365 GL Amount within tolerance." if status == "GL AMOUNT EXCEPTION"
                      else "GL evidence row identified but GL amount is blank." if status == "GL NOT POSTED"
                      else "POS statement amount is blank/non-numeric.")
            rows.append({"POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
                         "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
                         "GL Row": g["source_row"], "GL Main Account": g["main_account"], "GL Voucher": g["voucher"], "GL Journal": g["journal"],
                         "GL Date": g["gl_date"], "GL Amount": ga, "Difference": float(pa - ga) if pd.notna(pa) and pd.notna(ga) else float("nan"),
                         "Status": status, "Match Rule": " + ".join(filters), "Reason": reason, "GL Source File": g["source_file"]})
        elif pool.empty:
            rows.append({"POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"], "Provider": p["provider"],
                         "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"], "GL Row": "", "GL Main Account": "",
                         "GL Voucher": "", "GL Journal": "", "GL Date": pd.NaT, "GL Amount": float("nan"), "Difference": float("nan"),
                         "Status": "IDENTIFIER MISMATCH", "Match Rule": "", "Reason": "No GL evidence matched the available identifiers.", "GL Source File": ""})
        else:
            rows.append({"POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"], "Provider": p["provider"],
                         "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"], "GL Row": "", "GL Main Account": "",
                         "GL Voucher": "", "GL Journal": "", "GL Date": pd.NaT, "GL Amount": float("nan"), "Difference": float("nan"),
                         "Status": "GL REVIEW REQUIRED", "Match Rule": " + ".join(filters),
                         "Reason": "Multiple GL candidates; no deterministic evidence selected.", "GL Source File": ""})
    d = pd.DataFrame(rows); matched = d[d.Status == "GL MATCHED"].copy(); exc = d[d.Status != "GL MATCHED"].copy()
    summary = pd.DataFrame([{"POS Rows": len(pos), "GL Rows": len(gl), "GL Matched": len(matched),
                             "GL Amount Exceptions": int((d.Status == "GL AMOUNT EXCEPTION").sum()), "GL Not Posted": int((d.Status == "GL NOT POSTED").sum()),
                             "Review Required": int((d.Status == "GL REVIEW REQUIRED").sum()), "Identifier Mismatch": int((d.Status == "IDENTIFIER MISMATCH").sum()),
                             "POS Data Incomplete": int((d.Status == "POS DATA INCOMPLETE").sum()), "Unmatched GL Rows": len(gl) - len(used),
                             "Tolerance SAR": tolerance, "Overall Status": "RECONCILED" if exc.empty else "EXCEPTIONS REQUIRE REVIEW"}])
    return {"detail": d, "matched": matched, "exceptions": exc, "unmatched_gl": gl.loc[~gl.index.isin(used)].copy(), "summary": summary}




def reconcile_pos_to_gl_by_bucket(pos, gl, tolerance=0.50, settlement_lag_days=0):
    """
    Bucket-level reconciliation: compares SUM(POS Amount) vs SUM(GL Amount)
    per Store + Date, with the POS tender used only to select the expected D365 clearing account, instead of requiring
    reconcile_pos_to_gl()'s 1:1 POS row <-> GL row match.

    Correction added after checking a real second verification run
    (report2/report3, 2026-08-27) against this function's first version:

    GROUP BY PROVIDER, NOT JUST STORE+DATE. A single real Store+Date GL
    bucket can hold CARD, TABBY, TAMARA, CASH, and TAP clearing-account
    lines all at once. Comparing a card-only POS total against that
    combined total produced wild, meaningless differences (94% "GL AMOUNT
    EXCEPTION" in that run). Buckets are now keyed by (Store Code, expected
    D365 clearing account(s), Date), using
    core._gl_expected_account_for_tender() -- the SAME mapping
    core.trace_d365_source_to_gl() already uses for Store Tender -> GL
    matching elsewhere in this app -- so a MADA/VISA/MASTERCARD POS
    transaction is only ever compared against the card clearing account
    (11020907), never against that day's TABBY/CASH/TAMARA lines.

    On settlement_lag_days (default 0, tunable): tested a 1-day lag here
    (by analogy with this project's V30 finding that ANB books a card
    batch's BANK credit under the next day's date) and it made real results
    worse, not better, on this dataset -- 0 matches at lag=1 vs 250 at
    lag=0. That tracks: V30's lag is for the BANK settlement date (money
    physically landing, which genuinely takes an extra day), not the D365
    GL/journal posting date, which books same-day as an accrual entry.
    Default is 0 for that reason; the parameter is still exposed in case a
    given org's D365 configuration genuinely lags GL postings by design.

    Known simplification: one global lag is applied to every provider alike.
    Real provider settlement timing varies (V30/V31 found AMEX bundles
    multiple days into one wire and doesn't follow a fixed lag at all) --
    if AMEX/TABBY/TAMARA buckets still show as exceptions, that may need
    the same provider-specific handling already built for bank settlement
    (see V30/V31), not a bigger lag.
    """
    pos = pos.copy().reset_index(drop=True)
    gl = gl.copy().reset_index(drop=True)
    pos["pos_date_n"] = pd.to_datetime(pos["pos_date"], errors="coerce").dt.normalize()
    gl["gl_date_n"] = pd.to_datetime(gl["gl_date"], errors="coerce").dt.normalize()
    pos["pos_amount"] = pd.to_numeric(pos["pos_amount"], errors="coerce")
    gl["gl_amount"] = pd.to_numeric(gl["gl_amount"], errors="coerce")

    def _expected_accounts(row):
        """Return the D365 clearing account(s) expected for this POS tender.
        Store+Date+Amount are the only common reconciliation evidence.
        Provider is used only internally to select the correct GL clearing
        account and is never presented as a required GL matching key.
        """
        try:
            accounts = core._gl_expected_account_for_tender(
                row.get("provider", ""), row.get("store_code", "")
            )
            if isinstance(accounts, str):
                accounts = [accounts]
            return frozenset(norm(x) for x in (accounts or []) if norm(x))
        except Exception:
            return frozenset()

    pos["expected_accounts"] = pos.apply(_expected_accounts, axis=1)
    pos["group_key"] = pos["expected_accounts"].apply(lambda s: "+".join(sorted(s)) if s else "")

    can_bucket = (pos["store_code"] != "") & pos["pos_date_n"].notna() & (pos["group_key"] != "")
    has_amount = pos["pos_amount"].notna()
    pos_valid = pos[can_bucket & has_amount].copy()
    pos_bad = pos[~(can_bucket & has_amount)].copy()

    pos_valid["bucket_gl_date"] = pos_valid["pos_date_n"] + pd.to_timedelta(int(settlement_lag_days or 0), unit="D")

    gl_valid = gl[(gl["store_code"] != "") & gl["gl_date_n"].notna()].copy()

    pos_bucket = (pos_valid.groupby(["store_code", "group_key", "bucket_gl_date"])
                  .agg(pos_count=("pos_amount", "size"), pos_total=("pos_amount", "sum"),
                       pos_date=("pos_date_n", "first"))
                  .reset_index())
    # carry the expected_accounts set back onto each bucket row
    acct_lookup = (pos_valid.drop_duplicates(["store_code", "group_key"])
                    .set_index(["store_code", "group_key"])["expected_accounts"])
    pos_bucket["expected_accounts"] = pos_bucket.apply(
        lambda r: acct_lookup.get((r["store_code"], r["group_key"]), frozenset()), axis=1
    )

    claimed_idx = set()
    gl_counts = []
    gl_totals = []
    for _, b in pos_bucket.iterrows():
        accts = b["expected_accounts"]
        sub = gl_valid[
            (gl_valid["store_code"] == b["store_code"]) &
            (gl_valid["gl_date_n"] == b["bucket_gl_date"]) &
            (gl_valid["main_account"].isin(accts))
        ]
        claimed_idx.update(sub.index.tolist())
        gl_counts.append(len(sub))
        gl_totals.append(float(sub["gl_amount"].sum()) if len(sub) else 0.0)
    pos_bucket["gl_count"] = gl_counts
    pos_bucket["gl_total"] = gl_totals
    pos_bucket["bucket_diff"] = pos_bucket["pos_total"] - pos_bucket["gl_total"]

    def _status(r):
        if r["gl_count"] == 0:
            return "GL NOT POSTED"
        if abs(r["bucket_diff"]) <= tolerance:
            return "GL MATCHED"
        return "GL AMOUNT EXCEPTION"
    pos_bucket["bucket_status"] = pos_bucket.apply(_status, axis=1)
    reason_map = {
        "GL MATCHED": "Sum of POS Amount equals sum of D365 GL Amount for this Store+Provider+Date (settlement-lag adjusted) within tolerance.",
        "GL AMOUNT EXCEPTION": "Sum of POS Amount does not equal sum of D365 GL Amount for this Store+Provider+Date (settlement-lag adjusted) within tolerance.",
        "GL NOT POSTED": "POS activity exists for this Store+Provider+Date but no matching D365 GL clearing-account activity was found in the settlement-lag window.",
    }
    pos_bucket["bucket_reason"] = pos_bucket["bucket_status"].map(reason_map)

    bkey = pos_bucket.set_index(["store_code", "group_key", "bucket_gl_date"])

    rows = []
    for _, p in pos_valid.iterrows():
        key = (p["store_code"], p["group_key"], p["pos_date_n"] + pd.to_timedelta(int(settlement_lag_days or 0), unit="D"))
        b = bkey.loc[key]
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
            "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
            "GL Row": "", "GL Main Account": p["group_key"], "GL Voucher": "", "GL Journal": "",
            "GL Date": key[2], "GL Amount": b["gl_total"], "Difference": float(b["bucket_diff"]),
            "Status": b["bucket_status"], "Match Rule": "Store + Provider Clearing Account + Date (Bucket Sum)",
            "Reason": b["bucket_reason"], "GL Source File": "",
            "Bucket POS Rows": int(b["pos_count"]), "Bucket GL Rows": int(b["gl_count"]),
        })
    for _, p in pos_bad.iterrows():
        if pd.isna(p["pos_amount"]):
            reason, status = "POS Amount missing/non-numeric.", "POS DATA INCOMPLETE"
        elif p["group_key"] == "":
            reason, status = "Payment/provider type does not map to a known D365 clearing account.", "IDENTIFIER MISMATCH"
        else:
            reason, status = "Store Code or Date missing; cannot allocate to a Store+Date GL bucket.", "IDENTIFIER MISMATCH"
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
            "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
            "GL Row": "", "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": pd.NaT, "GL Amount": float("nan"), "Difference": float("nan"),
            "Status": status, "Match Rule": "", "Reason": reason, "GL Source File": "",
            "Bucket POS Rows": 0, "Bucket GL Rows": 0,
        })

    d = pd.DataFrame(rows)
    matched = d[d.Status == "GL MATCHED"].copy()
    exc = d[d.Status != "GL MATCHED"].copy()

    unmatched_gl = gl_valid.loc[~gl_valid.index.isin(claimed_idx)].copy()

    summary = pd.DataFrame([{
        "POS Rows": len(pos), "GL Rows": len(gl),
        "GL Matched": len(matched),
        "GL Amount Exceptions": int((d.Status == "GL AMOUNT EXCEPTION").sum()),
        "GL Not Posted": int((d.Status == "GL NOT POSTED").sum()),
        "Review Required": 0,
        "Identifier Mismatch": int((d.Status == "IDENTIFIER MISMATCH").sum()),
        "POS Data Incomplete": int((d.Status == "POS DATA INCOMPLETE").sum()),
        "Unmatched GL Rows": len(unmatched_gl),
        "Tolerance SAR": tolerance,
        "Settlement Lag Days": settlement_lag_days,
        "Overall Status": "RECONCILED" if exc.empty else "EXCEPTIONS REQUIRE REVIEW",
        "Match Granularity": "Store + Date bucket; expected D365 clearing account is used only to prevent cross-provider GL contamination. Amount is reconciled by bucket sum.",
    }])
    bucket_report = pos_bucket.rename(columns={
        "store_code": "Store Code",
        "pos_date": "POS Date",
        "group_key": "Expected GL Clearing Account",
        "pos_count": "POS Rows",
        "pos_total": "POS Total",
        "gl_count": "GL Rows",
        "gl_total": "GL Total",
        "bucket_diff": "Difference",
        "bucket_status": "Status",
        "bucket_reason": "Reason",
    })[
        ["Store Code", "POS Date", "Expected GL Clearing Account",
         "POS Rows", "POS Total", "GL Rows", "GL Total",
         "Difference", "Status", "Reason"]
    ].sort_values(["Store Code", "POS Date"]).reset_index(drop=True)

    return {
        "detail": d,
        "matched": matched,
        "exceptions": exc,
        "unmatched_gl": unmatched_gl,
        "summary": summary,
        "buckets": bucket_report,
    }

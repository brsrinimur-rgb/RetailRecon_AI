"""
logic/pos_gl_reconciliation.py

CHANGE HISTORY (most recent first) -- kept here because this module has been
patched several times against real production files, and each pass fixed a
real, evidence-based problem. Read this before changing the matching logic
again.

PASS 4 (2026-08-27) -- "Finance Control Tower" rework, per user's explicit
production-readiness review after report4:
  - Bucket key reverted to Store Code + Date ONLY, per the user's explicit
    instruction. PASS 3 had grouped by Store + provider clearing account +
    Date to stop cross-provider totals being compared to each other; the
    user's call is that Store+Date is the correct, simpler accounting
    control key, and that duplicate/completeness/variance CONTROLS should
    do the work instead of a more complex matching key. Provider/Merchant/
    Terminal/Auth Code remain on every row as supporting investigation
    detail, never as part of the match key.
  - Duplicate-file control: detect_duplicate_files() flags byte-identical
    uploads and same-content-different-filename uploads before
    reconciliation runs (the exact "uploaded yesterday's file twice"
    scenario the user described).
  - Row-level duplicate detection on both sides (POS: Store+Date+Reference+
    Amount; GL: Voucher+Journal+Main Account+Store+Date), auto-excluded
    from bucket sums (keeping one copy), counts reported.
  - GL bucket totals now sum Signed Amount (not Absolute Amount) so
    reversal/correction pairs net to their real economic effect instead of
    both legs adding as positive.
  - Cross-store swap detection: flags mirror-pair buckets where Store A's
    POS total matches Store B's GL total and vice versa (exactly the
    Store 633 <-> Store 659 pattern found in report4).
  - Exceptions now carry a rule-based "Likely Cause" and are sorted by
    ABS(Difference) descending (variance ranking).
  - New helper functions for period completeness and an upload control
    summary, meant to run BEFORE the user commits to a full reconciliation
    (see pages/35_POS_GL_Reconciliation.py's Validate step).

PASS 3 (2026-08-27, report4): grouped by Store + expected D365 clearing
account + Date; found and fixed a too-tight flat tolerance on bucket sums
(scaled per line item instead). Superseded by PASS 4 above on the grouping
key specifically; the tolerance-scaling and Controlled-Clearing-Account
filtering from this pass are kept.

PASS 2 (2026-08-27, report2/report3): first bucket-sum matching
(reconcile_pos_to_gl_by_bucket), because PASS 1's row-to-row matching
produced ~0 GL Matched against real D365 exports (many GL lines post per
store per day, not one).

PASS 1 (2026-08-27, original bug report): root-caused the original "0
matches" bug to two bugs in this module and the page that used it -- no
real header-row detection on upload, and no D365 Ledger Account dimension
parsing for Store Code. Fixed by reusing core.py's proven read_upload() /
normalize_pos() / normalize_d365_gl() plus the Store/Merchant/Terminal
Master chain, instead of this module's own narrow reimplementation.
reconcile_pos_to_gl() (row-to-row) is kept from this pass as a selectable
mode.
"""

from __future__ import annotations
import re
import hashlib
import pandas as pd
import core
import db


def norm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v).strip()).upper()


class _UploadLike:
    """Wraps (filename, bytes) so it satisfies core.read_upload()'s
    file-like interface (.name / .getvalue())."""
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


# ---------------------------------------------------------------------------
# 1. Duplicate-file control (checked BEFORE reconciliation runs)
# ---------------------------------------------------------------------------

def detect_exact_duplicate_files(pairs):
    """
    pairs: list of (filename, bytes). Flags byte-identical uploads -- the
    literal "uploaded the same file twice" case, catches it even if the
    uploader assigns the two uploads different internal names. Cheap and
    reliable; works before any parsing/normalization.

    Returns [{"file_a","file_b","reason"}, ...].
    """
    exact = []
    byte_hash = {}
    for name, data in pairs:
        h = hashlib.sha256(data).hexdigest()
        if h in byte_hash:
            exact.append({"file_a": byte_hash[h], "file_b": name,
                          "reason": "Byte-identical file content -- this is the same file uploaded twice."})
        else:
            byte_hash[h] = name
    return exact


def _content_duplicates(dataset, amount_col, date_col):
    """
    Shared implementation for detect_content_duplicate_pos/gl. Groups the
    ALREADY-NORMALIZED dataset by source_file and compares (row count,
    total of the real amount column, date range) -- deliberately built on
    the business amount/date fields core.py already identified, not raw
    file columns, so ID-like columns (Terminal ID, Merchant ID, Card
    Number...) can never dominate the signature and cause false positives.
    """
    if dataset is None or dataset.empty:
        return []
    g = dataset.groupby("source_file").agg(
        rows=(amount_col, "size"), total=(amount_col, "sum"),
        dmin=(date_col, "min"), dmax=(date_col, "max"),
    )
    dupes = []
    seen = {}
    for src, row in g.iterrows():
        sig = (int(row["rows"]), round(float(row["total"]) if pd.notna(row["total"]) else 0.0, 2),
               str(row["dmin"]), str(row["dmax"]))
        base_name = str(src).split(" [")[0]
        prior = seen.get(sig)
        if prior and prior.split(" [")[0] != base_name:
            dupes.append({"file_a": prior, "file_b": src,
                          "reason": f"Same row count ({int(row['rows'])}), same total amount (~SAR {row['total']:,.2f}), same date range -- looks like the same data under a different filename."})
        else:
            seen.setdefault(sig, src)
    return dupes


def detect_content_duplicate_pos(pos_dataset):
    """pos_dataset: output of build_pos_dataset(). See _content_duplicates()."""
    return _content_duplicates(pos_dataset, "pos_amount", "pos_date")


def detect_content_duplicate_gl(gl_dataset):
    """gl_dataset: output of build_gl_dataset(). See _content_duplicates()."""
    return _content_duplicates(gl_dataset, "gl_signed_amount", "gl_date")


def detect_duplicate_files(pairs, dataset=None, amount_col=None, date_col=None):
    """
    Convenience wrapper combining the exact-byte check (always available)
    with the content check (only if a normalized `dataset` is supplied --
    pass the build_pos_dataset()/build_gl_dataset() output with
    amount_col="pos_amount"/date_col="pos_date" or
    amount_col="gl_signed_amount"/date_col="gl_date").
    """
    exact = detect_exact_duplicate_files(pairs)
    content = _content_duplicates(dataset, amount_col, date_col) if dataset is not None and amount_col else []
    return {"exact_duplicates": exact, "content_duplicates": content,
            "has_duplicates": bool(exact or content)}


# ---------------------------------------------------------------------------
# Normalization (unchanged from PASS 1/2: reuse core.py's proven parsers)
# ---------------------------------------------------------------------------

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

    cols = ["merchant_id", "store_code", "provider", "reference", "auth_code",
            "pos_date", "pos_amount", "source_file", "source_row"]
    if not parts:
        return pd.DataFrame(columns=cols)

    pos = pd.concat(parts, ignore_index=True)

    # Store-resolution chain (identical priority order to
    # pages/1_POS_Reconciliation.py): Store Mapping Master (weakest) ->
    # Merchant ID Master -> Terminal ID Master (strongest, applied last so
    # it always wins). Many real POS/provider exports (e.g. ANB
    # Details_mada/Details_CC) carry no Store column at all -- only a
    # constant company name like "UNITED LUXURY CORP" -- so without this
    # step POS Store never becomes a real D365 Store Code.
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
    gl_date, gl_amount [absolute, reference only], gl_signed_amount [used
    for bucket sums], main_account, voucher, journal, source_file,
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

    cols = ["merchant_id", "store_code", "provider", "reference", "auth_code",
            "gl_date", "gl_amount", "gl_signed_amount", "main_account", "voucher",
            "journal", "source_file", "source_row"]
    if not parts:
        return pd.DataFrame(columns=cols)

    gl = pd.concat(parts, ignore_index=True)

    # Only clearing-account rows are ever comparable to a POS/provider
    # statement -- real D365 "General journal account entry" exports carry
    # Sales/COGS/Tax/Discount/Inventory postings under the same Store
    # dimension. This is the same filter core.trace_d365_source_to_gl() and
    # related functions already apply
    # (`actual_gl[actual_gl["Controlled Clearing Account"].fillna(False)]`).
    gl = gl[gl["Controlled Clearing Account"].fillna(False)].copy()
    if gl.empty:
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame({
        "merchant_id": "",
        "store_code": gl["Store Code"].map(norm),
        "provider": "",
        "reference": gl["Sales Order"].map(norm),
        "auth_code": "",
        "gl_date": pd.to_datetime(gl["GL Date"], errors="coerce"),
        # Debit/Credit control: preserve the signed amount for bucket
        # sums (a reversal/correction pair nets to its real economic
        # effect) and keep Absolute Amount only as a reference column --
        # never sum Absolute Amount blindly.
        "gl_amount": pd.to_numeric(gl["Absolute Amount"], errors="coerce"),
        "gl_signed_amount": pd.to_numeric(gl["Signed Amount"], errors="coerce"),
        "main_account": gl["Main Account"].map(norm),
        "voucher": gl["Voucher"].map(norm),
        "journal": gl["Journal Number"].map(norm),
        "source_file": gl["Source File"],
    })
    out["source_row"] = range(2, len(out) + 2)
    return out


# ---------------------------------------------------------------------------
# 2. Store+Date completeness control
# ---------------------------------------------------------------------------

def validate_pos_completeness(pos):
    """
    Checks every normalized POS row for a usable Store Code, Date and
    Amount BEFORE any bucketing happens. Returns a dict of counts plus a
    sample of the offending rows, meant to be shown to the user in the
    upload control summary (not buried in the exceptions sheet).
    """
    if pos is None or pos.empty:
        return {"total_rows": 0, "missing_store": 0, "missing_date": 0,
                "missing_amount": 0, "clean_rows": 0, "sample": pos}
    missing_store = pos["store_code"] == ""
    missing_date = pos["pos_date"].isna()
    missing_amount = pos["pos_amount"].isna()
    bad = missing_store | missing_date | missing_amount
    sample = pos[bad].copy()
    sample["Missing Store Code"] = missing_store[bad]
    sample["Missing Date"] = missing_date[bad]
    sample["Missing Amount"] = missing_amount[bad]
    return {
        "total_rows": len(pos),
        "missing_store": int(missing_store.sum()),
        "missing_date": int(missing_date.sum()),
        "missing_amount": int(missing_amount.sum()),
        "clean_rows": int((~bad).sum()),
        "sample": sample.head(200),
    }


# ---------------------------------------------------------------------------
# 8. Period completeness
# ---------------------------------------------------------------------------

def period_completeness(pos, gl):
    """
    Summarizes the calendar-date coverage on each side: min/max date,
    distinct dates, and which dates appear on one side but not the other.
    """
    pos_dates = set(pd.to_datetime(pos["pos_date"], errors="coerce").dt.normalize().dropna()) if pos is not None and not pos.empty else set()
    gl_dates = set(pd.to_datetime(gl["gl_date"], errors="coerce").dt.normalize().dropna()) if gl is not None and not gl.empty else set()
    missing_in_gl = sorted(pos_dates - gl_dates)
    missing_in_pos = sorted(gl_dates - pos_dates)
    return {
        "pos_date_min": min(pos_dates) if pos_dates else None,
        "pos_date_max": max(pos_dates) if pos_dates else None,
        "pos_distinct_dates": len(pos_dates),
        "gl_date_min": min(gl_dates) if gl_dates else None,
        "gl_date_max": max(gl_dates) if gl_dates else None,
        "gl_distinct_dates": len(gl_dates),
        "dates_pos_only": missing_in_gl,
        "dates_gl_only": missing_in_pos,
    }


# ---------------------------------------------------------------------------
# 9. Upload control summary
# ---------------------------------------------------------------------------

def upload_control_summary(pos_pairs, gl_pairs, pos, gl):
    """
    Pre-reconciliation snapshot: how many files/rows were loaded, what date
    range and which stores/GL accounts they cover. Meant to be shown right
    after Validate, before the user commits to RUN.
    """
    pos_stores = sorted(set(pos["store_code"]) - {""}) if pos is not None and not pos.empty else []
    gl_stores = sorted(set(gl["store_code"]) - {""}) if gl is not None and not gl.empty else []
    gl_accounts = sorted(set(gl["main_account"]) - {""}) if gl is not None and not gl.empty else []
    period = period_completeness(pos, gl)
    return {
        "pos_files": len(pos_pairs), "gl_files": len(gl_pairs),
        "pos_rows": 0 if pos is None else len(pos), "gl_rows": 0 if gl is None else len(gl),
        "pos_stores": pos_stores, "gl_stores": gl_stores, "gl_accounts": gl_accounts,
        "stores_pos_only": sorted(set(pos_stores) - set(gl_stores)),
        "stores_gl_only": sorted(set(gl_stores) - set(pos_stores)),
        "period": period,
    }


# ---------------------------------------------------------------------------
# 3 & 4. Row-level duplicate detection (GL and POS)
# ---------------------------------------------------------------------------

def _flag_pos_duplicates(pos):
    """
    Flags POS rows that look like the same transaction counted more than
    once: same Store + Date + Reference/Auth Code + Amount. Requires a
    non-blank reference so unrelated cash-only rows sharing a round amount
    aren't falsely flagged.
    """
    pos = pos.copy()
    ref = pos["reference"].astype(str)
    ref = ref.where(ref.str.len() > 0, pos["auth_code"].astype(str))
    pos["_dup_ref"] = ref
    eligible = (pos["store_code"] != "") & pos["pos_date"].notna() & (pos["_dup_ref"] != "") & pos["pos_amount"].notna()
    key_cols = ["store_code", "pos_date", "_dup_ref", "pos_amount"]
    group_dup = pd.Series(False, index=pos.index)
    extra_dup = pd.Series(False, index=pos.index)
    if eligible.any():
        sub = pos[eligible]
        group_dup.loc[sub.index] = sub.duplicated(subset=key_cols, keep=False)
        extra_dup.loc[sub.index] = sub.duplicated(subset=key_cols, keep="first")
    pos["is_duplicate_pos"] = group_dup
    pos["is_duplicate_pos_extra"] = extra_dup
    return pos.drop(columns=["_dup_ref"])


def _flag_gl_duplicates(gl):
    """
    Flags GL rows sharing Voucher + Journal + Main Account + Store + Date
    (Voucher/Journal numbers are meant to be unique per real D365 posting,
    so a repeated combination is a strong duplicate-upload signal).
    """
    gl = gl.copy()
    eligible = (gl["voucher"] != "") & (gl["journal"] != "") & (gl["store_code"] != "") & gl["gl_date"].notna()
    key_cols = ["voucher", "journal", "main_account", "store_code", "gl_date"]
    group_dup = pd.Series(False, index=gl.index)
    extra_dup = pd.Series(False, index=gl.index)
    if eligible.any():
        sub = gl[eligible]
        group_dup.loc[sub.index] = sub.duplicated(subset=key_cols, keep=False)
        extra_dup.loc[sub.index] = sub.duplicated(subset=key_cols, keep="first")
    gl["is_duplicate_gl"] = group_dup
    gl["is_duplicate_gl_extra"] = extra_dup
    return gl


# ---------------------------------------------------------------------------
# 7. Cross-store swap detection
# ---------------------------------------------------------------------------

def _detect_store_swaps(bucket_df, tolerance):
    """
    For each pair of buckets on the SAME date but different stores, checks
    whether Store A's POS Total lines up with Store B's GL Total (and vice
    versa) -- a mirror pair, the signature of a Store Code swap somewhere
    in the pipeline. Returns {(store, date): suspected_counterpart_store}.
    """
    swaps = {}
    for date, grp in bucket_df.groupby("bucket_gl_date"):
        grp = grp.reset_index(drop=True)
        n = len(grp)
        for i in range(n):
            a = grp.iloc[i]
            if max(abs(a["pos_total"]), abs(a["gl_total"])) <= tolerance * 2:
                continue
            for j in range(n):
                if i == j:
                    continue
                b = grp.iloc[j]
                if a["store_code"] == b["store_code"]:
                    continue
                if abs(a["pos_total"] - b["gl_total"]) <= tolerance and abs(a["gl_total"] - b["pos_total"]) <= tolerance:
                    swaps[(a["store_code"], date)] = b["store_code"]
    return swaps


# ---------------------------------------------------------------------------
# 10. Exception reason engine
# ---------------------------------------------------------------------------

def _classify_exception(row, swap_map):
    key = (row["store_code"], row["bucket_gl_date"])
    if key in swap_map:
        return f"POSSIBLE STORE CODE SWAP with Store {swap_map[key]} -- this store's POS total matches the other store's GL total and vice versa."
    if row.get("pos_duplicate_rows", 0) or row.get("gl_duplicate_rows", 0):
        return (f"Duplicate rows detected and excluded from totals "
                f"({int(row.get('pos_duplicate_rows',0))} POS, {int(row.get('gl_duplicate_rows',0))} GL) -- "
                f"remaining variance may still need review.")
    pos_total, gl_total = row["pos_total"], row["gl_total"]
    if gl_total and pos_total:
        ratio = pos_total / gl_total
        if abs(ratio - 2) < 0.08:
            return "POS Total is ~2x GL Total -- check for a duplicate POS file upload for this Store+Date."
        if abs(ratio - 0.5) < 0.08:
            return "GL Total is ~2x POS Total -- check for a duplicate GL file upload, or a missing POS file for this Store+Date."
    pos_count, gl_count = row["pos_count"], row["gl_count"]
    if pos_count and gl_count:
        if gl_count < pos_count * 0.5:
            return f"GL has far fewer lines ({int(gl_count)}) than POS transactions ({int(pos_count)}) -- check for a missing/partial GL file for this date."
        if pos_count < gl_count * 0.5:
            return f"POS has far fewer transactions ({int(pos_count)}) than GL lines ({int(gl_count)}) -- check for a missing/partial POS file for this date."
    return "Amount variance has no obvious cause from row-count or ratio patterns -- needs manual review."


# ---------------------------------------------------------------------------
# Row-to-row matching (PASS 1, kept as a selectable mode)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Bucket matching -- Store Code + Date only (PASS 4 default), with the
# full control stack: duplicate exclusion, signed-amount sums, variance
# ranking, swap detection, exception classification.
# ---------------------------------------------------------------------------

def reconcile_pos_to_gl_by_bucket(pos, gl, tolerance=0.50, settlement_lag_days=0,
                                   exclude_duplicate_pos=True, exclude_duplicate_gl=True):
    """
    Bucket key is Store Code + Date ONLY (per explicit user decision --
    do not add Merchant ID/Provider/Terminal/Auth Code to the match key;
    those stay available as investigation columns). Compares SUM(POS
    Amount) vs SUM(GL Signed Amount) per bucket.

    Controls applied before summing:
      - Duplicate GL rows (same Voucher+Journal+Main Account+Store+Date)
        and duplicate POS rows (same Store+Date+Reference/Auth+Amount) are
        detected and, by default, excluded from the sums (one copy kept);
        counts are reported on every bucket and in the row-level detail.
      - Bucket tolerance scales with line-item count
        (tolerance * max(POS rows, GL rows) in the bucket) so summing many
        independently-rounded transactions doesn't manufacture false
        exceptions.
      - GL side sums Signed Amount, not Absolute Amount, so reversal/
        correction pairs net out correctly.

    After bucketing:
      - Cross-store swap detection flags mirror-pair buckets.
      - Every exception gets a rule-based "Likely Cause".
      - Exceptions are sorted by ABS(Difference) descending (variance
        ranking) so the largest financial risk surfaces first.
    """
    pos = pos.copy().reset_index(drop=True)
    gl = gl.copy().reset_index(drop=True)
    pos["pos_date_n"] = pd.to_datetime(pos["pos_date"], errors="coerce").dt.normalize()
    gl["gl_date_n"] = pd.to_datetime(gl["gl_date"], errors="coerce").dt.normalize()
    pos["pos_amount"] = pd.to_numeric(pos["pos_amount"], errors="coerce")
    gl["gl_signed_amount"] = pd.to_numeric(gl["gl_signed_amount"], errors="coerce")
    gl["gl_amount"] = pd.to_numeric(gl["gl_amount"], errors="coerce")

    pos = _flag_pos_duplicates(pos)
    gl = _flag_gl_duplicates(gl)

    can_bucket = (pos["store_code"] != "") & pos["pos_date_n"].notna()
    has_amount = pos["pos_amount"].notna()
    pos_all = pos[can_bucket & has_amount].copy()
    pos_bad = pos[~(can_bucket & has_amount)].copy()
    pos_all["bucket_gl_date"] = pos_all["pos_date_n"] + pd.to_timedelta(int(settlement_lag_days or 0), unit="D")

    gl_all = gl[(gl["store_code"] != "") & gl["gl_date_n"].notna()].copy()

    pos_sum_src = pos_all[~(exclude_duplicate_pos & pos_all["is_duplicate_pos_extra"])] if exclude_duplicate_pos else pos_all
    gl_sum_src = gl_all[~(exclude_duplicate_gl & gl_all["is_duplicate_gl_extra"])] if exclude_duplicate_gl else gl_all

    pos_bucket = (pos_all.groupby(["store_code", "bucket_gl_date"])
                  .agg(pos_count_all=("pos_amount", "size"), pos_duplicate_rows=("is_duplicate_pos_extra", "sum"))
                  .reset_index())
    pos_sum = (pos_sum_src.groupby(["store_code", "bucket_gl_date"])
               .agg(pos_count=("pos_amount", "size"), pos_total=("pos_amount", "sum"), pos_date=("pos_date_n", "first"))
               .reset_index())
    pos_bucket = pos_bucket.merge(pos_sum, on=["store_code", "bucket_gl_date"], how="left")
    pos_bucket["pos_count"] = pos_bucket["pos_count"].fillna(0).astype(int)
    pos_bucket["pos_total"] = pos_bucket["pos_total"].fillna(0.0)

    gl_bucket = (gl_all.groupby(["store_code", "gl_date_n"])
                 .agg(gl_count_all=("gl_signed_amount", "size"), gl_duplicate_rows=("is_duplicate_gl_extra", "sum"))
                 .reset_index().rename(columns={"gl_date_n": "bucket_gl_date"}))
    gl_sum = (gl_sum_src.groupby(["store_code", "gl_date_n"])
              .agg(gl_count=("gl_signed_amount", "size"), gl_total=("gl_signed_amount", "sum"))
              .reset_index().rename(columns={"gl_date_n": "bucket_gl_date"}))
    gl_bucket = gl_bucket.merge(gl_sum, on=["store_code", "bucket_gl_date"], how="left")
    gl_bucket["gl_count"] = gl_bucket["gl_count"].fillna(0).astype(int)
    gl_bucket["gl_total"] = gl_bucket["gl_total"].fillna(0.0)

    merged = pos_bucket.merge(gl_bucket, on=["store_code", "bucket_gl_date"], how="outer", indicator=True)
    for c in ["pos_count", "pos_total", "pos_duplicate_rows", "gl_count", "gl_total", "gl_duplicate_rows"]:
        merged[c] = merged[c].fillna(0)
    merged["bucket_diff"] = merged["pos_total"] - merged["gl_total"]
    # Do not let a large transaction count turn a SAR 0.50 tolerance into
    # hundreds/thousands of SAR. That would weaken the finance control.
    calculated_tolerance = tolerance * merged[["pos_count", "gl_count"]].max(axis=1).clip(lower=1)
    merged["bucket_tolerance"] = calculated_tolerance.clip(upper=50.0)

    def _status(r):
        if r["_merge"] == "left_only" or r["gl_count"] == 0:
            return "GL NOT POSTED"
        if r["_merge"] == "right_only" or r["pos_count"] == 0:
            return "UNMATCHED GL"
        if abs(r["bucket_diff"]) <= r["bucket_tolerance"]:
            return "GL MATCHED"
        return "GL AMOUNT EXCEPTION"
    merged["bucket_status"] = merged.apply(_status, axis=1)

    swap_map = _detect_store_swaps(merged[merged.bucket_status == "GL AMOUNT EXCEPTION"], tolerance)

    def _reason(r):
        if r["bucket_status"] == "GL MATCHED":
            return "Sum of POS Amount equals sum of D365 GL Amount for this Store+Date within tolerance."
        if r["bucket_status"] == "GL NOT POSTED":
            return "POS activity exists for this Store+Date but no matching D365 GL clearing-account activity was found."
        if r["bucket_status"] == "UNMATCHED GL":
            return "D365 GL clearing-account activity exists for this Store+Date with no corresponding POS statement rows."
        return _classify_exception(r, swap_map)
    merged["bucket_reason"] = merged.apply(_reason, axis=1)
    merged["store_swap_with"] = merged.apply(lambda r: swap_map.get((r["store_code"], r["bucket_gl_date"]), ""), axis=1)

    bkey = merged.set_index(["store_code", "bucket_gl_date"])

    rows = []
    for _, p in pos_all.iterrows():
        key = (p["store_code"], p["bucket_gl_date"])
        b = bkey.loc[key]
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
            "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
            "GL Row": "", "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": key[1], "GL Amount": b["gl_total"], "Difference": float(b["bucket_diff"]),
            "Status": b["bucket_status"], "Match Rule": "Store + Date (Bucket Sum)",
            "Reason": b["bucket_reason"], "GL Source File": "",
            "Bucket POS Rows": int(b["pos_count"]), "Bucket GL Rows": int(b["gl_count"]),
            "Bucket Tolerance": float(b["bucket_tolerance"]),
            "Is Duplicate POS Row": bool(p["is_duplicate_pos"]),
            "Store Swap Suspected With": b["store_swap_with"],
        })
    for _, p in pos_bad.iterrows():
        reason = "POS Amount missing/non-numeric." if pd.isna(p["pos_amount"]) else "Store Code or Date missing; cannot allocate to a Store+Date GL bucket."
        status = "POS DATA INCOMPLETE" if pd.isna(p["pos_amount"]) else "IDENTIFIER MISMATCH"
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
            "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
            "GL Row": "", "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": pd.NaT, "GL Amount": float("nan"), "Difference": float("nan"),
            "Status": status, "Match Rule": "", "Reason": reason, "GL Source File": "",
            "Bucket POS Rows": 0, "Bucket GL Rows": 0, "Bucket Tolerance": float("nan"),
            "Is Duplicate POS Row": bool(p.get("is_duplicate_pos", False)), "Store Swap Suspected With": "",
        })

    d = pd.DataFrame(rows)
    matched = d[d.Status == "GL MATCHED"].copy()
    exc = d[d.Status != "GL MATCHED"].copy()
    exc["_abs_diff"] = exc["Difference"].abs()
    exc = exc.sort_values("_abs_diff", ascending=False, na_position="last").drop(columns=["_abs_diff"])

    unmatched_gl_keys = set(merged[merged.bucket_status == "UNMATCHED GL"][["store_code", "bucket_gl_date"]].apply(tuple, axis=1))
    if unmatched_gl_keys:
        gl_all["_key"] = list(zip(gl_all["store_code"], gl_all["gl_date_n"]))
        unmatched_gl = gl_all[gl_all["_key"].isin(unmatched_gl_keys)].drop(columns=["_key"]).copy()
    else:
        unmatched_gl = gl_all.iloc[0:0].copy()

    bucket_summary = merged.rename(columns={
        "store_code": "Store Code", "bucket_gl_date": "Date",
        "pos_count": "POS Rows", "pos_total": "POS Total",
        "gl_count": "GL Rows", "gl_total": "GL Total",
        "bucket_diff": "Difference", "bucket_tolerance": "Bucket Tolerance",
        "bucket_status": "Status", "bucket_reason": "Reason",
        "pos_duplicate_rows": "Duplicate POS Rows Excluded", "gl_duplicate_rows": "Duplicate GL Rows Excluded",
        "store_swap_with": "Store Swap Suspected With",
    })[["Store Code", "Date", "POS Rows", "POS Total", "GL Rows", "GL Total", "Difference",
        "Bucket Tolerance", "Duplicate POS Rows Excluded", "Duplicate GL Rows Excluded",
        "Store Swap Suspected With", "Status", "Reason"]].copy()
    bucket_summary["_abs_diff"] = bucket_summary["Difference"].abs()
    bucket_summary = bucket_summary.sort_values(["Status", "_abs_diff"], ascending=[True, False]).drop(columns=["_abs_diff"])

    top_exceptions = (bucket_summary[bucket_summary["Status"] == "GL AMOUNT EXCEPTION"]
                       .assign(_ad=lambda x: x["Difference"].abs())
                       .sort_values("_ad", ascending=False).drop(columns=["_ad"]).head(20))

    total_pos_dup = int(pos_all["is_duplicate_pos_extra"].sum())
    total_gl_dup = int(gl_all["is_duplicate_gl_extra"].sum())

    # Finance KPI: a "match" is one reconciled Store+Date accounting bucket,
    # NOT the number of POS transaction rows repeated inside that bucket.
    matched_buckets = int((merged["bucket_status"] == "GL MATCHED").sum())
    exception_buckets = int((merged["bucket_status"] == "GL AMOUNT EXCEPTION").sum())
    not_posted_buckets = int((merged["bucket_status"] == "GL NOT POSTED").sum())
    unmatched_gl_buckets = int((merged["bucket_status"] == "UNMATCHED GL").sum())

    summary = pd.DataFrame([{
        "POS Rows": len(pos), "GL Rows": len(gl),
        "Store-Date Buckets": len(merged),
        "GL Matched": matched_buckets,
        "GL Matched Buckets": matched_buckets,
        "GL Amount Exceptions": exception_buckets,
        "GL Amount Exception Buckets": exception_buckets,
        "GL Not Posted": not_posted_buckets,
        "Unmatched GL Buckets": unmatched_gl_buckets,
        "POS Transaction Rows Matched": int((d.Status == "GL MATCHED").sum()),
        "Identifier Mismatch": int((d.Status == "IDENTIFIER MISMATCH").sum()),
        "POS Data Incomplete": int((d.Status == "POS DATA INCOMPLETE").sum()),
        "Duplicate POS Rows Excluded": total_pos_dup,
        "Duplicate GL Rows Excluded": total_gl_dup,
        "Unmatched GL Rows": len(unmatched_gl),
        "POS Total (SAR)": float(pos_sum_src["pos_amount"].sum()) if not pos_sum_src.empty else 0.0,
        "GL Total (SAR)": float(gl_sum_src["gl_signed_amount"].sum()) if not gl_sum_src.empty else 0.0,
        "Tolerance SAR": tolerance,
        "Settlement Lag Days": settlement_lag_days,
        "Overall Status": "RECONCILED" if exc.empty else "EXCEPTIONS REQUIRE REVIEW",
        "Match Granularity": "Store + Date bucket (sum of amounts); amount decides match/exception, not the key",
    }])
    summary["Net Difference (SAR)"] = summary["POS Total (SAR)"] - summary["GL Total (SAR)"]

    matched_bucket_summary = bucket_summary[bucket_summary["Status"] == "GL MATCHED"].copy()

    return {"detail": d, "matched": matched, "exceptions": exc, "unmatched_gl": unmatched_gl,
            "bucket_summary": bucket_summary, "matched_bucket_summary": matched_bucket_summary,
            "top_exceptions": top_exceptions, "summary": summary}

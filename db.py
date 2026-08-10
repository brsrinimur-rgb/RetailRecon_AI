"""
Shared persistence layer for RetailRecon AI.

Streamlit keeps st.session_state isolated per browser session, which breaks the
maker-checker workflow: a JV created by "maker" is invisible to "checker" logged
in from a different session. This module backs JV batches, approval decisions,
correction logs, late-transaction adjustments, the close calendar and GL config
with a small SQLite file (retailrecon.db, created next to this file) so every
login reads and writes the same data and nothing is lost on a server restart.

Reconciliation results (ct_result: matched/unmatched/pos/bank/quarantine) stay
in st.session_state on purpose - they are large, upload-triggered, and only
needed live by the person running "RUN RECONCILIATION" / "CREATE WEEKLY STORE
JVs". Everything downstream of JV creation (approval, posting, verification,
corrections, adjustments, GL config, close calendar) is shared state and lives
here instead.
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from datetime import datetime
import pandas as pd

DB_PATH = Path(__file__).parent / "retailrecon.db"

JV_COLUMNS = [
    "Journal Batch", "Store Code", "Week", "Group", "Account", "Debit", "Credit",
    "Narration", "Difference", "Balanced", "Approval Status", "D365 Status", "Voucher",
]


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS jv_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journal_batch TEXT,
        line_number INTEGER,
        approval_status TEXT,
        d365_status TEXT,
        voucher TEXT,
        balanced INTEGER,
        validation_passed INTEGER,
        row_json TEXT,
        created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS approval_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, user TEXT, decision TEXT, batches TEXT, comment TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS correction_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, d365_row INTEGER, new_auth TEXT, reason TEXT, user TEXT, status TEXT
    )""")
    # Correction approval audit columns (backward-compatible migration).
    _corr_cols={r[1] for r in conn.execute("PRAGMA table_info(correction_log)").fetchall()}
    for _name,_type in [
        ("original_auth","TEXT"),
        ("store_code","TEXT"),
        ("receipt_id","TEXT"),
        ("approver","TEXT"),
        ("approval_time","TEXT"),
        ("approval_comment","TEXT"),
    ]:
        if _name not in _corr_cols:
            conn.execute(f"ALTER TABLE correction_log ADD COLUMN {_name} {_type}")
    conn.execute("""CREATE TABLE IF NOT EXISTS adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, store TEXT, provider TEXT, amount REAL, reason TEXT, status TEXT, user TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS close_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT, owner TEXT, due_date TEXT, status TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gl_config (
        key TEXT PRIMARY KEY, gl_account TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS master_data_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, user TEXT, master TEXT, action TEXT,
        rows_before INTEGER, rows_after INTEGER,
        added_keys TEXT, updated_keys TEXT, removed_keys TEXT,
        before_snapshot TEXT, after_snapshot TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS merchant_master (
        merchant_id TEXT PRIMARY KEY, store_code TEXT, store_name TEXT, notes TEXT, updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS terminal_master (
        terminal_id TEXT PRIMARY KEY, store_code TEXT, store_name TEXT, notes TEXT, updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS store_mapping_master (
        provider_store_name TEXT PRIMARY KEY,
        store_code TEXT,
        active TEXT,
        notes TEXT,
        updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS commission_rate_master (
        payment_type TEXT PRIMARY KEY,
        commission_rate REAL,
        vat_rate REAL,
        validation_method TEXT,
        effective_from TEXT,
        effective_to TEXT,
        active TEXT,
        notes TEXT,
        updated_at TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS accounting_period_control (
        legal_entity TEXT PRIMARY KEY,
        closed_through_date TEXT,
        next_open_date TEXT,
        status TEXT,
        updated_by TEXT,
        updated_at TEXT,
        notes TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS accounting_period_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT,
        user TEXT,
        legal_entity TEXT,
        action TEXT,
        old_closed_through_date TEXT,
        new_closed_through_date TEXT,
        old_next_open_date TEXT,
        new_next_open_date TEXT,
        reason TEXT
    )""")
    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------------------- JV batches
def replace_jv(df: pd.DataFrame):
    """
    Save JV rows. The full row is kept as JSON so persistence never again
    silently drops columns when core.create_jv()'s output shape changes -
    this previously wrote to a table ("jv_batches") that init_db() never
    created, meaning every JV Creation click crashed. Fields used for
    filtering/updates elsewhere (approval, posting, validation) are also
    stored in real columns so those operations stay fast and simple.
    """
    import json
    import numpy as np

    conn = get_conn()
    conn.execute("DELETE FROM jv_batches")

    if df is None or df.empty:
        conn.commit()
        conn.close()
        return

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, (pd.Timestamp,)):
            return "" if pd.isna(v) else v.isoformat()
        if isinstance(v, (np.generic,)):
            v = v.item()
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        return v

    def value(row, *names, default=""):
        for name in names:
            if name in row.index:
                v = row.get(name)
                if pd.isna(v) if not isinstance(v, str) else False:
                    return default
                return v
        return default

    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for _, r in df.iterrows():
        journal_batch = str(value(r, "Journal Batch", "Journal batch number", default=""))
        line_number = value(r, "Line number", default=None)
        try:
            line_number = int(line_number) if line_number not in (None, "") else None
        except (TypeError, ValueError):
            line_number = None
        approval_status = str(value(r, "Approval Status", default="PENDING"))
        d365_status = str(value(r, "D365 Status", default="NOT POSTED"))
        voucher = str(value(r, "Voucher", default=""))
        balanced = bool(value(r, "Balanced", default=False))
        validation_passed = bool(value(r, "Validation Passed", default=True))
        row_json = json.dumps({k: _clean(v) for k, v in r.to_dict().items()}, default=str)

        rows.append((
            journal_batch, line_number, approval_status, d365_status, voucher,
            1 if balanced else 0, 1 if validation_passed else 0, row_json, now
        ))

    conn.executemany(
        """INSERT INTO jv_batches
           (journal_batch,line_number,approval_status,d365_status,voucher,
            balanced,validation_passed,row_json,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        rows
    )
    conn.commit()
    conn.close()


def load_jv() -> pd.DataFrame:
    import json

    conn = get_conn()
    rows = conn.execute(
        """SELECT id, journal_batch, approval_status, d365_status, voucher,
                  balanced, validation_passed, row_json
           FROM jv_batches ORDER BY id"""
    ).fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame(columns=JV_COLUMNS)

    records = []
    for _id, jbatch, appr, d365, voucher, balanced, valid, row_json in rows:
        d = json.loads(row_json) if row_json else {}
        # The indexed columns are the live/authoritative values (they get
        # updated in place by update_jv_approval/update_jv_posting without
        # rewriting row_json), so they win over whatever was serialized at
        # creation time.
        d["Approval Status"] = appr
        d["D365 Status"] = d365
        d["Voucher"] = voucher
        d["Balanced"] = bool(balanced)
        d["Validation Passed"] = bool(valid)
        if "Journal Batch" not in d:
            d["Journal Batch"] = jbatch
        records.append(d)

    out = pd.DataFrame(records)
    if "Date" in out.columns:
        pass  # keep as stored (string); pages format for display as needed
    return out


def update_jv_approval(batches: list[str], status: str):
    conn = get_conn()
    conn.executemany(
        "UPDATE jv_batches SET approval_status=? WHERE journal_batch=?",
        [(status, b) for b in batches],
    )
    conn.commit()
    conn.close()


def update_jv_posting(batch: str, voucher: str):
    conn = get_conn()
    conn.execute(
        "UPDATE jv_batches SET d365_status='POSTED', voucher=? WHERE journal_batch=?",
        (voucher, batch),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------- approval log
def append_approval_log(user, decision, batches, comment):
    conn = get_conn()
    conn.execute(
        "INSERT INTO approval_log (time,user,decision,batches,comment) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), user, decision, ",".join(batches), comment),
    )
    conn.commit()
    conn.close()


def load_approval_log() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        """SELECT time AS "Time", user AS "User", decision AS "Decision",
                  batches AS "Batches", comment AS "Comment"
           FROM approval_log ORDER BY id DESC""",
        conn,
    )
    conn.close()
    return df


# ----------------------------------------------------------- correction log
def append_correction_log(
    d365_row, new_auth, reason, user,
    original_auth="", store_code="", receipt_id=""
):
    """
    Submit an Auth Code correction for maker-checker approval.
    The original transaction identity is captured so approved corrections can
    be safely reapplied on reconciliation reruns.
    """
    conn=get_conn()
    conn.execute(
        """INSERT INTO correction_log
           (time,d365_row,new_auth,reason,user,status,original_auth,store_code,receipt_id,
            approver,approval_time,approval_comment)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(timespec="seconds"),
            int(d365_row),
            str(new_auth).strip(),
            str(reason).strip(),
            str(user).strip(),
            "PENDING APPROVAL",
            str(original_auth).strip(),
            str(store_code).strip(),
            str(receipt_id).strip(),
            "",
            "",
            "",
        ),
    )
    conn.commit()
    conn.close()


def load_correction_log(status=None) -> pd.DataFrame:
    conn=get_conn()
    sql="""SELECT id AS "ID", time AS "Submitted At", d365_row AS "D365 Row",
                  store_code AS "Store Code", receipt_id AS "Receipt ID",
                  original_auth AS "Original Auth", new_auth AS "New Auth",
                  reason AS "Reason", user AS "Submitted By", status AS "Status",
                  approver AS "Approver", approval_time AS "Approval Time",
                  approval_comment AS "Approval Comment"
           FROM correction_log"""
    params=[]
    if status:
        sql += " WHERE status=?"
        params=[status]
    sql += " ORDER BY id DESC"
    df=pd.read_sql_query(sql,conn,params=params)
    conn.close()
    return df


def decide_correction(correction_id, decision, approver, comment=""):
    """
    Approve or reject a pending correction.
    Enforces maker-checker: submitter cannot approve/reject their own request.
    Returns (ok, message).
    """
    decision=str(decision).strip().upper()
    if decision not in {"APPROVED","REJECTED"}:
        return False,"Decision must be APPROVED or REJECTED."

    conn=get_conn()
    row=conn.execute(
        "SELECT user,status,new_auth FROM correction_log WHERE id=?",
        (int(correction_id),)
    ).fetchone()
    if row is None:
        conn.close()
        return False,"Correction request not found."

    maker,status,new_auth=row
    if str(status).upper()!="PENDING APPROVAL":
        conn.close()
        return False,f"Correction is already {status}."
    if str(maker).strip().lower()==str(approver).strip().lower():
        conn.close()
        return False,"Maker-checker control: you cannot approve or reject your own correction."

    conn.execute(
        """UPDATE correction_log
           SET status=?, approver=?, approval_time=?, approval_comment=?
           WHERE id=? AND status='PENDING APPROVAL'""",
        (
            decision,
            str(approver).strip(),
            datetime.now().isoformat(timespec="seconds"),
            str(comment).strip(),
            int(correction_id),
        ),
    )
    conn.commit()
    conn.close()
    return True,f"Correction {decision.lower()}."


def load_approved_corrections() -> pd.DataFrame:
    return load_correction_log("APPROVED")


def apply_approved_corrections(tender: pd.DataFrame) -> pd.DataFrame:
    """
    Apply approved Auth Code corrections to normalized D365 Store Tender rows.

    Matching priority:
      1) Store Code + Receipt ID + Original Auth (strongest)
      2) D365 Row + Original Auth
      3) D365 Row for legacy correction records

    Original Auth is preserved in 'Original Auth Code' and correction audit
    fields are stamped onto the transaction.
    """
    if tender is None or tender.empty:
        return tender

    approved=load_approved_corrections()
    if approved.empty:
        out=tender.copy()
        if "Original Auth Code" not in out.columns:
            out["Original Auth Code"]=out.get("Auth Code","")
        return out

    out=tender.copy()
    if "Original Auth Code" not in out.columns:
        out["Original Auth Code"]=out["Auth Code"].astype(str)
    if "Auth Correction ID" not in out.columns:
        out["Auth Correction ID"]=""
    if "Auth Correction Approved By" not in out.columns:
        out["Auth Correction Approved By"]=""
    if "Auth Correction Approval Time" not in out.columns:
        out["Auth Correction Approval Time"]=""

    # Apply oldest-to-newest so the latest approved correction wins.
    for _,c in approved.sort_values("ID").iterrows():
        new_auth=str(c.get("New Auth","")).strip()
        if not new_auth:
            continue

        original=str(c.get("Original Auth","")).strip()
        store=str(c.get("Store Code","")).strip()
        receipt=str(c.get("Receipt ID","")).strip()
        row_no=c.get("D365 Row",None)

        mask=pd.Series(False,index=out.index)

        if store and receipt:
            mask = (
                out["Store Code"].astype(str).str.strip().eq(store)
                & out["Receipt ID"].astype(str).str.strip().eq(receipt)
            )
            if original:
                mask &= out["Original Auth Code"].astype(str).str.strip().eq(original)

        if not mask.any() and row_no is not None and "D365 Row" in out.columns:
            try:
                mask=out["D365 Row"].astype(int).eq(int(row_no))
                if original:
                    mask &= out["Original Auth Code"].astype(str).str.strip().eq(original)
            except Exception:
                pass

        if not mask.any() and row_no is not None and "D365 Row" in out.columns and not original:
            try:
                mask=out["D365 Row"].astype(int).eq(int(row_no))
            except Exception:
                pass

        if mask.any():
            out.loc[mask,"Auth Code"]=new_auth
            out.loc[mask,"Auth Correction ID"]=str(c.get("ID",""))
            out.loc[mask,"Auth Correction Approved By"]=str(c.get("Approver",""))
            out.loc[mask,"Auth Correction Approval Time"]=str(c.get("Approval Time",""))

    return out



# ------------------------------------------------------------- adjustments
def append_adjustment(store, provider, amount, reason, user):
    conn = get_conn()
    conn.execute(
        """INSERT INTO adjustments (date,store,provider,amount,reason,status,user)
           VALUES (?,?,?,?,?,?,?)""",
        (datetime.now().date().isoformat(), store, provider, float(amount), reason, "PENDING APPROVAL", user),
    )
    conn.commit()
    conn.close()


def load_adjustments() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        """SELECT date AS "Date", store AS "Store", provider AS "Provider",
                  amount AS "Amount", reason AS "Reason", status AS "Status", user AS "User"
           FROM adjustments ORDER BY id DESC""",
        conn,
    )
    conn.close()
    return df


# ----------------------------------------------------------- close calendar
_DEFAULT_CLOSE_TASKS = [
    ("POS Reconciliation", "Finance", 0, "In Progress"),
    ("Bank Settlement", "Treasury", 1, "Open"),
    ("JV Approval", "Finance Manager", 2, "Open"),
    ("D365 Verification", "Finance", 3, "Open"),
]


def load_close_calendar() -> pd.DataFrame:
    from datetime import date, timedelta
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM close_calendar").fetchone()[0]
    if n == 0:
        today = date.today()
        rows = [(t, o, (today + timedelta(days=d)).isoformat(), s) for t, o, d, s in _DEFAULT_CLOSE_TASKS]
        conn.executemany(
            "INSERT INTO close_calendar (task,owner,due_date,status) VALUES (?,?,?,?)", rows
        )
        conn.commit()
    df = pd.read_sql_query(
        """SELECT id, task AS "Task", owner AS "Owner", due_date AS "Due Date", status AS "Status"
           FROM close_calendar ORDER BY id""",
        conn,
    )
    conn.close()
    return df


def save_close_calendar(df: pd.DataFrame):
    conn = get_conn()
    for _, r in df.iterrows():
        conn.execute(
            "UPDATE close_calendar SET task=?, owner=?, due_date=?, status=? WHERE id=?",
            (r["Task"], r["Owner"], str(r["Due Date"]), r["Status"], int(r["id"])),
        )
    conn.commit()
    conn.close()


# ----------------------------------------------------------------- gl_config
def load_gl_config() -> dict:
    import core
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM gl_config").fetchone()[0]
    if n == 0:
        conn.executemany(
            "INSERT INTO gl_config (key, gl_account) VALUES (?,?)",
            list(core.D365_JV_DEFAULTS.items()),
        )
        conn.commit()
    rows = conn.execute("SELECT key, gl_account FROM gl_config").fetchall()
    conn.close()
    cfg = {k: v for k, v in rows}
    # Backfill any keys added to D365_JV_DEFAULTS after this DB was first
    # seeded (e.g. a new payment group's GL account), without touching
    # keys Finance has already edited.
    missing = {k: v for k, v in core.D365_JV_DEFAULTS.items() if k not in cfg}
    if missing:
        conn = get_conn()
        conn.executemany(
            "INSERT OR IGNORE INTO gl_config (key, gl_account) VALUES (?,?)",
            list(missing.items()),
        )
        conn.commit()
        conn.close()
        cfg.update(missing)
    return cfg


def save_gl_config(mapping: dict):
    conn = get_conn()
    for k, v in mapping.items():
        conn.execute(
            "UPDATE gl_config SET gl_account=? WHERE key=?", (str(v), k)
        )
    conn.commit()
    conn.close()

# ------------------------------------------------- master-data audit/validation
def validate_master_rows(df, id_col, code_col, label):
    """
    Reject bad master-data uploads outright rather than silently dropping or
    overwriting rows: blank IDs, blank Store Codes, and duplicate IDs within
    the SAME upload are all hard errors. A user accidentally replacing a
    Terminal/Merchant/Store mapping can affect many transactions at once, so
    bad input must never be partially or silently applied.
    Returns a list of error strings; empty list means the upload is clean.
    """
    errs = []
    if df is None or df.empty:
        return errs

    ids = df[id_col].astype(str).str.strip() if id_col in df.columns else pd.Series(dtype=str)
    codes = df[code_col].astype(str).str.strip() if code_col in df.columns else pd.Series(dtype=str)

    blank_id_rows = df.index[(ids == "") | (ids.str.lower() == "nan")].tolist()
    if blank_id_rows:
        errs.append(f"{label}: {len(blank_id_rows)} row(s) have a blank {id_col} (row numbers: {[r+1 for r in blank_id_rows][:10]})")

    blank_code_rows = df.index[(codes == "") | (codes.str.lower() == "nan")].tolist()
    if blank_code_rows:
        errs.append(f"{label}: {len(blank_code_rows)} row(s) have a blank Store Code (row numbers: {[r+1 for r in blank_code_rows][:10]})")

    dupes = ids[(ids != "") & (ids.str.lower() != "nan")]
    dupe_ids = dupes[dupes.duplicated(keep=False)].unique().tolist()
    if dupe_ids:
        errs.append(f"{label}: duplicate {id_col} value(s) within this upload: {dupe_ids[:10]}")

    return errs


def _log_master_change(user, master, action, before_df, after_df, key_col, code_col):
    def _keymap(d):
        if d is None or d.empty or key_col not in d.columns:
            return {}
        m = {}
        for _, r in d.iterrows():
            k = str(r.get(key_col, "")).strip()
            if k:
                m[k] = str(r.get(code_col, "")).strip()
        return m

    before_map = _keymap(before_df)
    after_map = _keymap(after_df)
    added = sorted(set(after_map) - set(before_map))
    removed = sorted(set(before_map) - set(after_map))
    updated = sorted(k for k in (set(before_map) & set(after_map)) if before_map[k] != after_map[k])

    conn = get_conn()
    conn.execute(
        "INSERT INTO master_data_audit_log "
        "(time,user,master,action,rows_before,rows_after,added_keys,updated_keys,removed_keys, "
        " before_snapshot,after_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            datetime.now().isoformat(timespec="seconds"), user or "unknown", master, action,
            len(before_map), len(after_map),
            json.dumps({k: (before_map.get(k), after_map.get(k)) for k in added}),
            json.dumps({k: (before_map.get(k), after_map.get(k)) for k in updated}),
            json.dumps({k: (before_map.get(k), after_map.get(k)) for k in removed}),
            (before_df.to_json(orient="records") if before_df is not None and not before_df.empty else "[]"),
            (after_df.to_json(orient="records") if after_df is not None and not after_df.empty else "[]"),
        ),
    )
    conn.commit()
    conn.close()
    return {"added": added, "updated": updated, "removed": removed}


def load_master_audit_log(master=None) -> pd.DataFrame:
    conn = get_conn()
    q = ('SELECT time AS "Time", user AS "User", master AS "Master", action AS "Action", '
         'rows_before AS "Rows Before", rows_after AS "Rows After", '
         'added_keys AS "Added", updated_keys AS "Updated (old -> new)", removed_keys AS "Removed" '
         'FROM master_data_audit_log')
    params = ()
    if master:
        q += " WHERE master=?"
        params = (master,)
    q += " ORDER BY id DESC"
    df = pd.read_sql_query(q, conn, params=params)
    conn.close()
    return df


def load_terminal_master():

    conn=get_conn()
    df=pd.read_sql_query("""SELECT terminal_id AS "Terminal ID",store_code AS "Store Code",
    store_name AS "Store Name",notes AS "Notes",updated_at AS "Updated At"
    FROM terminal_master ORDER BY terminal_id""",conn)
    conn.close();return df

def save_terminal_master(df,mode="merge",user=None):
    """
    Save Terminal ID -> Store Code mappings.

    Allowed:
      - One Store Code with multiple Terminal IDs.
      - Same Terminal ID repeated with the same Store Code (collapsed).

    Rejected:
      - Same Terminal ID assigned to different Store Codes.
    """
    cols={str(c).strip().lower():c for c in df.columns}
    tc=cols.get("terminal id") or cols.get("terminal_id") or cols.get("terminal")
    sc=cols.get("store code") or cols.get("store_code")
    nc=cols.get("store name") or cols.get("store_name")
    xc=cols.get("notes") or cols.get("note")
    if tc is None or sc is None:
        raise ValueError("Required columns: Terminal ID and Store Code.")

    d=df.copy()

    def _norm(v):
        if pd.isna(v):
            return ""
        s=str(v).strip()
        if s.endswith(".0") and s[:-2].isdigit():
            s=s[:-2]
        return s

    d[tc]=d[tc].apply(_norm)
    d[sc]=d[sc].apply(_norm)

    errs=[]
    blank_ids=d.index[d[tc]==""].tolist()
    blank_stores=d.index[d[sc]==""].tolist()
    if blank_ids:
        errs.append(f"POS Terminal Master: {len(blank_ids)} blank Terminal ID row(s).")
    if blank_stores:
        errs.append(f"POS Terminal Master: {len(blank_stores)} blank Store Code row(s).")

    conflicts=[]
    for tid,g in d[(d[tc]!="") & (d[sc]!="")].groupby(tc):
        stores=sorted(set(g[sc]))
        if len(stores)>1:
            conflicts.append(f"{tid} -> {stores}")
    if conflicts:
        errs.append(
            "The same Terminal ID is assigned to multiple Store Codes: "
            + "; ".join(conflicts[:20])
        )

    if errs:
        raise ValueError("Upload rejected:\n- " + "\n- ".join(errs))

    # Harmless exact repeats are collapsed.
    d=d.drop_duplicates(subset=[tc],keep="last").copy()

    before=load_terminal_master()
    conn=get_conn()
    if mode=="replace":
        conn.execute("DELETE FROM terminal_master")

    now=datetime.now().isoformat(timespec="seconds")
    for _,r in d.iterrows():
        tid=str(r.get(tc,"")).strip()
        store=str(r.get(sc,"")).strip()
        name="" if nc is None or pd.isna(r.get(nc)) else str(r.get(nc)).strip()
        notes="" if xc is None or pd.isna(r.get(xc)) else str(r.get(xc)).strip()

        conn.execute(
            """INSERT INTO terminal_master VALUES (?,?,?,?,?)
               ON CONFLICT(terminal_id) DO UPDATE SET
                 store_code=excluded.store_code,
                 store_name=excluded.store_name,
                 notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (tid,store,name,notes,now)
        )

    conn.commit()
    conn.close()

    after=load_terminal_master()
    return _log_master_change(
        user,"terminal_master",mode,before,after,"Terminal ID","Store Code"
    )


# ------------------------------------------------------------ merchant master
def load_merchant_master():
    conn=get_conn()
    df=pd.read_sql_query("""SELECT merchant_id AS "Merchant ID",store_code AS "Store Code",
    store_name AS "Store Name",notes AS "Notes",updated_at AS "Updated At"
    FROM merchant_master ORDER BY merchant_id""",conn)
    conn.close();return df

def save_merchant_master(df,mode="merge",user=None):
    cols={str(c).strip().lower():c for c in df.columns}
    mc=cols.get("merchant id") or cols.get("merchant_id") or cols.get("merchant")
    sc=cols.get("store code") or cols.get("store_code")
    nc=cols.get("store name") or cols.get("store_name")
    xc=cols.get("notes") or cols.get("note")
    if mc is None or sc is None:raise ValueError("Required columns: Merchant ID and Store Code.")

    errs=validate_master_rows(df,mc,sc,"Merchant ID Master")
    if errs:
        raise ValueError("Upload rejected - fix the following and re-upload:\n- " + "\n- ".join(errs))

    before=load_merchant_master()

    conn=get_conn()
    if mode=="replace":conn.execute("DELETE FROM merchant_master")
    now=datetime.now().isoformat(timespec="seconds")
    for _,r in df.iterrows():
        mid=str(r.get(mc,"")).strip()
        if mid.endswith(".0") and mid[:-2].isdigit():mid=mid[:-2]
        store=str(r.get(sc,"")).strip()
        if store.endswith(".0") and store[:-2].isdigit():store=store[:-2]
        if not mid or mid.lower()=="nan":continue
        name="" if nc is None or pd.isna(r.get(nc)) else str(r.get(nc)).strip()
        notes="" if xc is None or pd.isna(r.get(xc)) else str(r.get(xc)).strip()
        conn.execute("""INSERT INTO merchant_master VALUES (?,?,?,?,?)
        ON CONFLICT(merchant_id) DO UPDATE SET store_code=excluded.store_code,
        store_name=excluded.store_name,notes=excluded.notes,updated_at=excluded.updated_at""",
        (mid,store,name,notes,now))
    conn.commit();conn.close()

    after=load_merchant_master()
    return _log_master_change(user,"merchant_master",mode,before,after,"Merchant ID","Store Code")

# ------------------------------------------------------ store mapping master
def load_store_mapping_master():
    conn=get_conn()
    df=pd.read_sql_query(
        """SELECT provider_store_name AS "Provider Store Name",
                  store_code AS "Store Code",
                  active AS "Active",
                  notes AS "Notes",
                  updated_at AS "Updated At"
           FROM store_mapping_master
           ORDER BY provider_store_name""",
        conn
    )
    conn.close()
    return df

def save_store_mapping_master(df,mode="merge",user=None):
    if df is None:
        return
    cols={str(c).strip().lower():c for c in df.columns}
    nc=cols.get("provider store name") or cols.get("store name") or cols.get("provider_store_name")
    sc=cols.get("store code") or cols.get("store_code")
    ac=cols.get("active")
    xc=cols.get("notes") or cols.get("note")
    if nc is None or sc is None:
        raise ValueError("Required columns: Provider Store Name and Store Code.")

    errs=validate_master_rows(df,nc,sc,"Store Mapping Master")
    if errs:
        raise ValueError("Upload rejected - fix the following and re-upload:\n- " + "\n- ".join(errs))

    before=load_store_mapping_master()

    conn=get_conn()
    if mode=="replace":
        conn.execute("DELETE FROM store_mapping_master")
    now=datetime.now().isoformat(timespec="seconds")

    for _,r in df.iterrows():
        name="" if pd.isna(r.get(nc)) else str(r.get(nc)).strip()
        code="" if pd.isna(r.get(sc)) else str(r.get(sc)).strip()
        if code.endswith(".0") and code[:-2].isdigit():
            code=code[:-2]
        if not name:
            continue
        active="Yes" if ac is None or pd.isna(r.get(ac)) else str(r.get(ac)).strip()
        notes="" if xc is None or pd.isna(r.get(xc)) else str(r.get(xc)).strip()
        conn.execute(
            """INSERT INTO store_mapping_master(provider_store_name,store_code,active,notes,updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(provider_store_name) DO UPDATE SET
                 store_code=excluded.store_code,
                 active=excluded.active,
                 notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (name,code,active,notes,now)
        )
    conn.commit()
    conn.close()

    after=load_store_mapping_master()
    return _log_master_change(user,"store_mapping_master",mode,before,after,"Provider Store Name","Store Code")



# ------------------------------------------------ commission rate master
_DEFAULT_COMMISSION_RATES = [
    ("MADA", 0.55, 15.0, "CONTRACT_RATE", "", "", "Yes", "Finance confirmed"),
    ("VISA", 1.55, 15.0, "CONTRACT_RATE", "", "", "Yes", "Finance confirmed"),
    ("MASTERCARD", 1.55, 15.0, "CONTRACT_RATE", "", "", "Yes", "Finance confirmed"),
    ("GCC NET", 1.50, 15.0, "CONTRACT_RATE", "", "", "Yes", "Finance confirmed"),
    ("AMEX", 3.00, 15.0, "CONTRACT_RATE", "", "", "Yes", "Finance confirmed"),
    ("TABBY", None, 15.0, "PROVIDER_ACTUAL", "", "", "Yes", "Contract rate pending"),
    ("TAMARA", None, 15.0, "PROVIDER_ACTUAL", "", "", "Yes", "Contract rate pending"),
    ("TAP", None, 15.0, "PROVIDER_ACTUAL", "", "", "Yes", "Contract rate pending"),
]

def _seed_commission_rates():
    conn=get_conn()
    n=conn.execute("SELECT COUNT(*) FROM commission_rate_master").fetchone()[0]
    if n==0:
        now=datetime.now().isoformat(timespec="seconds")
        conn.executemany(
            """INSERT INTO commission_rate_master
               (payment_type,commission_rate,vat_rate,validation_method,effective_from,effective_to,active,notes,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(*r,now) for r in _DEFAULT_COMMISSION_RATES]
        )
        conn.commit()
    conn.close()

def load_commission_rate_master():
    _seed_commission_rates()
    conn=get_conn()
    df=pd.read_sql_query(
        """SELECT payment_type AS "Payment Type",
                  commission_rate AS "Commission Rate %",
                  vat_rate AS "VAT Rate %",
                  validation_method AS "Validation Method",
                  effective_from AS "Effective From",
                  effective_to AS "Effective To",
                  active AS "Active",
                  notes AS "Notes",
                  updated_at AS "Updated At"
           FROM commission_rate_master
           ORDER BY CASE payment_type
             WHEN 'MADA' THEN 1
             WHEN 'VISA' THEN 2
             WHEN 'MASTERCARD' THEN 3
             WHEN 'GCC NET' THEN 4
             WHEN 'AMEX' THEN 5
             WHEN 'TABBY' THEN 6
             WHEN 'TAMARA' THEN 7
             WHEN 'TAP' THEN 8
             ELSE 99 END, payment_type""",
        conn
    )
    conn.close()
    return df

def save_commission_rate_master(df, mode="replace"):
    if df is None:
        return
    cols={str(c).strip().lower():c for c in df.columns}
    pc=cols.get("payment type")
    rc=cols.get("commission rate %") or cols.get("commission rate")
    vc=cols.get("vat rate %") or cols.get("vat rate")
    mc=cols.get("validation method")
    ef=cols.get("effective from")
    et=cols.get("effective to")
    ac=cols.get("active")
    nc=cols.get("notes")
    if pc is None:
        raise ValueError("Commission Rate Master requires Payment Type.")

    conn=get_conn()
    if mode=="replace":
        conn.execute("DELETE FROM commission_rate_master")

    now=datetime.now().isoformat(timespec="seconds")
    for _,r in df.iterrows():
        pay="" if pd.isna(r.get(pc)) else str(r.get(pc)).strip().upper()
        if not pay:
            continue
        rate=None
        if rc is not None and not pd.isna(r.get(rc)) and str(r.get(rc)).strip()!="":
            rate=float(r.get(rc))
        vat=15.0
        if vc is not None and not pd.isna(r.get(vc)) and str(r.get(vc)).strip()!="":
            vat=float(r.get(vc))
        method="CONTRACT_RATE" if rate is not None else "PROVIDER_ACTUAL"
        if mc is not None and not pd.isna(r.get(mc)) and str(r.get(mc)).strip():
            method=str(r.get(mc)).strip().upper()
        eff_from="" if ef is None or pd.isna(r.get(ef)) else str(r.get(ef)).strip()
        eff_to="" if et is None or pd.isna(r.get(et)) else str(r.get(et)).strip()
        active="Yes" if ac is None or pd.isna(r.get(ac)) else str(r.get(ac)).strip()
        notes="" if nc is None or pd.isna(r.get(nc)) else str(r.get(nc)).strip()

        conn.execute(
            """INSERT INTO commission_rate_master
               (payment_type,commission_rate,vat_rate,validation_method,effective_from,effective_to,active,notes,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(payment_type) DO UPDATE SET
                 commission_rate=excluded.commission_rate,
                 vat_rate=excluded.vat_rate,
                 validation_method=excluded.validation_method,
                 effective_from=excluded.effective_from,
                 effective_to=excluded.effective_to,
                 active=excluded.active,
                 notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (pay,rate,vat,method,eff_from,eff_to,active,notes,now)
        )
    conn.commit()
    conn.close()


# --------------------------------------------------- accounting period control
def _period_date_text(v):
    d = pd.to_datetime(v, errors="coerce")
    return "" if pd.isna(d) else d.date().isoformat()

def load_accounting_period_control(legal_entity="ULC"):
    init_db()
    conn = get_conn()
    row = conn.execute(
        "SELECT legal_entity, closed_through_date, next_open_date, status, "
        "updated_by, updated_at, notes "
        "FROM accounting_period_control WHERE legal_entity=?",
        (legal_entity,)
    ).fetchone()
    if row is None:
        now = datetime.now().isoformat(timespec="seconds")
        row = (legal_entity, "", "", "OPEN", "system", now, "")
        conn.execute(
            "INSERT INTO accounting_period_control "
            "(legal_entity,closed_through_date,next_open_date,status,updated_by,updated_at,notes) "
            "VALUES (?,?,?,?,?,?,?)",
            row
        )
        conn.commit()
    conn.close()
    return {
        "Legal Entity": row[0],
        "Closed Through Date": row[1],
        "Next Open Date": row[2],
        "Status": row[3],
        "Updated By": row[4],
        "Updated At": row[5],
        "Notes": row[6],
    }

def save_accounting_period_control(
    legal_entity, closed_through_date, next_open_date, status, user, reason
):
    init_db()
    if not str(reason or "").strip():
        raise ValueError("Reason is mandatory for accounting-period changes.")

    old = load_accounting_period_control(legal_entity)
    closed_txt = _period_date_text(closed_through_date)
    open_txt = _period_date_text(next_open_date)

    if closed_txt and open_txt and pd.Timestamp(open_txt) <= pd.Timestamp(closed_txt):
        raise ValueError("Next Open Date must be after Closed Through Date.")

    now = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    conn.execute(
        "INSERT INTO accounting_period_control "
        "(legal_entity,closed_through_date,next_open_date,status,updated_by,updated_at,notes) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(legal_entity) DO UPDATE SET "
        "closed_through_date=excluded.closed_through_date, "
        "next_open_date=excluded.next_open_date, "
        "status=excluded.status, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at, notes=excluded.notes",
        (legal_entity, closed_txt, open_txt, status, user, now, str(reason).strip())
    )
    conn.execute(
        "INSERT INTO accounting_period_audit "
        "(time,user,legal_entity,action,old_closed_through_date,new_closed_through_date,"
        "old_next_open_date,new_next_open_date,reason) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            now, user, legal_entity, "PERIOD_CONTROL_CHANGE",
            old.get("Closed Through Date",""), closed_txt,
            old.get("Next Open Date",""), open_txt,
            str(reason).strip()
        )
    )
    conn.commit()
    conn.close()

def load_accounting_period_audit(legal_entity=None):
    init_db()
    conn = get_conn()
    sql = (
        'SELECT time AS "Time", user AS "User", legal_entity AS "Legal Entity", '
        'action AS "Action", old_closed_through_date AS "Old Closed Through", '
        'new_closed_through_date AS "New Closed Through", '
        'old_next_open_date AS "Old Next Open", '
        'new_next_open_date AS "New Next Open", reason AS "Reason" '
        'FROM accounting_period_audit'
    )
    params = ()
    if legal_entity:
        sql += " WHERE legal_entity=?"
        params = (legal_entity,)
    sql += " ORDER BY id DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df

def is_accounting_date_open(accounting_date, legal_entity="ULC"):
    ctrl = load_accounting_period_control(legal_entity)
    d = pd.to_datetime(accounting_date, errors="coerce")
    if pd.isna(d):
        return False, "Accounting Date is missing or invalid."

    closed = pd.to_datetime(ctrl.get("Closed Through Date",""), errors="coerce")
    next_open = pd.to_datetime(ctrl.get("Next Open Date",""), errors="coerce")

    if pd.notna(closed) and d.normalize() <= closed.normalize():
        return False, f"Accounting period is closed through {closed:%d-%b-%Y}."
    if pd.notna(next_open) and d.normalize() < next_open.normalize():
        return False, f"Accounting Date must be on or after {next_open:%d-%b-%Y}."
    return True, "OPEN"

def resolve_accounting_date(source_date, requested_accounting_date=None, legal_entity="ULC"):
    if requested_accounting_date is not None:
        d = pd.to_datetime(requested_accounting_date, errors="coerce")
        ok, msg = is_accounting_date_open(d, legal_entity)
        if not ok:
            raise ValueError(msg)
        return d.normalize()

    ctrl = load_accounting_period_control(legal_entity)
    src = pd.to_datetime(source_date, errors="coerce")
    closed = pd.to_datetime(ctrl.get("Closed Through Date",""), errors="coerce")
    next_open = pd.to_datetime(ctrl.get("Next Open Date",""), errors="coerce")

    if pd.notna(src) and pd.notna(closed) and src.normalize() <= closed.normalize() and pd.notna(next_open):
        return next_open.normalize()

    if pd.notna(src):
        ok, _ = is_accounting_date_open(src, legal_entity)
        if ok:
            return src.normalize()

    if pd.notna(next_open):
        return next_open.normalize()
    return pd.Timestamp.today().normalize()

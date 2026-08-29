"""
logic/provider_gl_mapping.py

Admin-maintained Provider -> D365 GL clearing account override, added V42
per the user's explicit ask: "Provider mapping should ultimately come from
configurable master data rather than core.py ... this should become a
Finance/Admin-maintained Provider->GL Mapping Master. Then PROVIDER MAPPING
REQUIRED can be resolved without code deployment."

Same architecture as logic/swap_tracking.py (self-contained SQLite,
decoupled from db.py and core.py, additive-only): an override for a
(provider, store) pair is checked FIRST; if none exists, the caller's
`core_fn` (normally core._gl_expected_account_for_tender) is used exactly
as before. A provider that already resolves correctly today behaves
IDENTICALLY after this module exists -- it only adds a way to teach the
app a new provider value without editing core.py or redeploying.

A store-specific override (provider, "601") wins over a blank-store
override (provider, "") -- mirrors core._gl_expected_account_for_tender()'s
own Store 613 TAP/TAP_GATEWAY special case, so an admin can add a
store-specific correction without it silently overriding every other
store's mapping for that provider.

CAVEAT (same one swap_tracking.py's own docstring calls out, deliberately
NOT solved differently here -- see V42's change-history note in
logic/pos_gl_reconciliation.py for why): on some hosting setups (notably
Streamlit Community Cloud) local filesystem writes aren't guaranteed to
survive an app restart or redeploy -- only guaranteed for the life of the
running container. If that's how this app is hosted, this SQLite file
could get wiped on a redeploy, silently resetting any overrides an admin
added. If a durable backend is already used elsewhere in this app (db.py),
point _connect() at that instead -- every function here is written so only
_connect() would need to change.
"""

from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "retailrecon_provider_gl_mapping.sqlite"


def _connect(db_path=None):
    path = str(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provider_gl_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            store_code TEXT NOT NULL DEFAULT '',
            gl_accounts TEXT NOT NULL,
            added_by TEXT,
            added_at TEXT NOT NULL,
            note TEXT
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_store
        ON provider_gl_overrides (provider, store_code)
    """)
    conn.commit()
    return conn


def _norm_provider(p):
    return str(p or "").strip().upper()


def _norm_store(s):
    return str(s or "").strip()


def save_provider_gl_mapping(provider, gl_accounts, store_code="", added_by="", note="", db_path=None):
    """
    Adds or updates an override: `provider` (+ optional `store_code`; blank
    means "applies to every store unless a store-specific override also
    exists") -> `gl_accounts` (an iterable of D365 account code strings,
    e.g. ["11020913"]). Returns True on success, False on any failure
    (invalid input, or a database error -- this is an admin convenience,
    never load-bearing for the reconciliation itself).
    """
    provider = _norm_provider(provider)
    store_code = _norm_store(store_code)
    accounts_str = ",".join(sorted({str(a).strip() for a in gl_accounts if str(a).strip()}))
    if not provider or not accounts_str:
        return False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn = _connect(db_path)
        conn.execute(
            "INSERT INTO provider_gl_overrides (provider, store_code, gl_accounts, added_by, added_at, note) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(provider, store_code) DO UPDATE SET "
            "gl_accounts=excluded.gl_accounts, added_by=excluded.added_by, "
            "added_at=excluded.added_at, note=excluded.note",
            (provider, store_code, accounts_str, added_by, now, note),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def delete_provider_gl_mapping(provider, store_code="", db_path=None):
    """Removes one override (exact provider+store_code match). Returns True
    on success (including "nothing matched"), False on a database error."""
    provider = _norm_provider(provider)
    store_code = _norm_store(store_code)
    try:
        conn = _connect(db_path)
        conn.execute("DELETE FROM provider_gl_overrides WHERE provider=? AND store_code=?", (provider, store_code))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def list_provider_gl_mappings(db_path=None):
    """Every override currently stored, as a list of dicts: provider,
    store_code (""=all stores), gl_accounts (list of account code strings),
    added_by, added_at, note. Degrades to [] on any database error."""
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT provider, store_code, gl_accounts, added_by, added_at, note "
            "FROM provider_gl_overrides ORDER BY provider, store_code"
        ).fetchall()
        conn.close()
        return [
            {"provider": r[0], "store_code": r[1],
             "gl_accounts": [a for a in (r[2].split(",") if r[2] else []) if a],
             "added_by": r[3] or "", "added_at": r[4], "note": r[5] or ""}
            for r in rows
        ]
    except Exception:
        return []


def load_override_map(db_path=None):
    """{(provider, store_code): set(accounts)} for every stored override,
    including the ("provider", "") blank-store entries. Meant to be loaded
    ONCE per reconciliation run and passed as `_override_cache` to
    expected_accounts_for_provider() for every row, rather than hitting
    SQLite per row."""
    return {(m["provider"], m["store_code"]): set(m["gl_accounts"]) for m in list_provider_gl_mappings(db_path)}


def expected_accounts_for_provider(provider, store_code="", core_fn=None, db_path=None, _override_cache=None):
    """
    Resolves the expected D365 GL clearing account(s) for a POS provider.
    Checks the Admin-maintained override table FIRST (a store-specific
    override wins over a blank-store override for the same provider);
    falls back to `core_fn(provider, store_code)` (pass
    core._gl_expected_account_for_tender) when no override exists.

    Returns (accounts: set[str], from_override: bool) -- `from_override`
    lets a caller note in a reason/UI string whether a match came from an
    admin-added mapping vs. the built-in core.py table, without changing
    any downstream logic.

    `_override_cache`: optional pre-loaded dict from load_override_map(),
    so a caller resolving many rows in a loop (e.g. every bucket in a run)
    doesn't re-open SQLite per row. If omitted, loads fresh from `db_path`
    on every call -- fine for occasional use, wasteful in a hot loop.
    """
    provider_n = _norm_provider(provider)
    store_n = _norm_store(store_code)
    overrides = _override_cache if _override_cache is not None else load_override_map(db_path)
    if (provider_n, store_n) in overrides:
        return set(overrides[(provider_n, store_n)]), True
    if (provider_n, "") in overrides:
        return set(overrides[(provider_n, "")]), True
    if core_fn is not None:
        try:
            return set(core_fn(provider, store_code)), False
        except Exception:
            return set(), False
    return set(), False

"""
logic/swap_tracking.py

Persistent memory for Store Code swaps detected by
reconcile_pos_to_gl_by_bucket()'s cross-store swap detector (PASS 4+), added
in PASS 7 after the Store 633<->659 swap first found in report 4 turned up
again, completely unchanged, in report 5 weeks later. The swap detector
itself has no memory -- it re-derives the same finding fresh every run, with
nothing distinguishing "just found this for the first time" from "this has
been sitting unresolved for a month." That distinction matters to Finance:
a swap that keeps coming back is an escalating problem, not routine noise.

Same architecture as the earlier Run History module (self-contained SQLite,
decoupled from db.py, additive-only, zero changes to the matching/detection
logic itself) -- this module only ever READS reconcile_pos_to_gl_by_bucket()'s
already-computed "Store Swap Suspected With" column and records/annotates
what it finds. It never influences a match/exception decision.

CAVEAT (same one Run History's spec called out, repeated here because it
applies identically): on some hosting setups (notably Streamlit Community
Cloud) local filesystem writes aren't guaranteed to survive an app restart
or redeploy -- only guaranteed for the life of the running container. If
that's how this app is hosted, this SQLite file could get wiped on a
redeploy, silently resetting "first seen"/"times seen" history. If a
durable backend is already used elsewhere in this app (db.py), point
_connect() at that instead -- every other function here is written so only
_connect() would need to change.
"""

from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "retailrecon_swap_tracking.sqlite"


def _connect(db_path=None):
    path = str(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS swap_sightings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_a TEXT NOT NULL,
            store_b TEXT NOT NULL,
            bucket_date TEXT NOT NULL,
            run_label TEXT,
            seen_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_swap_key
        ON swap_sightings (store_a, store_b, bucket_date)
    """)
    conn.commit()
    return conn


def _canonical_pair(a, b):
    a, b = str(a).strip(), str(b).strip()
    return (a, b) if a <= b else (b, a)


def extract_swap_pairs(bucket_summary):
    """
    Derives canonical (store_a, store_b, date) tuples from
    reconcile_pos_to_gl_by_bucket()'s "bucket_summary" output -- a detected
    swap shows up on BOTH stores' rows pointing at each other, so this
    dedupes to one entry per pair+date.
    """
    if bucket_summary is None or bucket_summary.empty or "Store Swap Suspected With" not in bucket_summary.columns:
        return []
    swapped = bucket_summary[bucket_summary["Store Swap Suspected With"].astype(str).str.len() > 0]
    seen = set()
    pairs = []
    for _, r in swapped.iterrows():
        a, b = _canonical_pair(r["Store Code"], r["Store Swap Suspected With"])
        d = r["Date"]
        key = (a, b, str(d))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((a, b, d))
    return pairs


def record_and_annotate_swaps(bucket_summary, db_path=None, run_label=None):
    """
    Records every swap pair currently detected in `bucket_summary` (see
    extract_swap_pairs()) as one sighting, then returns a dataframe
    annotating each pair+date with its full sighting history: First Seen,
    Times Seen (including this run), and a Status of "NEW" (first time this
    exact Store A/Store B/Date combination has ever been recorded) or
    "RECURRING" (seen in an earlier run too -- still unresolved).

    Safe to call every run, including runs with zero swaps (returns an
    empty dataframe). A database error (e.g. read-only filesystem) degrades
    to returning the current run's swaps un-annotated (Status "NEW",
    Times Seen 1) rather than breaking the page -- persistence is a nice-to-
    have on top of the swap detector, never a dependency of it.
    """
    cols = ["Store A", "Store B", "Date", "First Seen", "Times Seen (Including This Run)", "Status"]
    pairs = extract_swap_pairs(bucket_summary)
    if not pairs:
        return pd.DataFrame(columns=cols)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn = _connect(db_path)
        for a, b, d in pairs:
            conn.execute(
                "INSERT INTO swap_sightings (store_a, store_b, bucket_date, run_label, seen_at) VALUES (?,?,?,?,?)",
                (a, b, str(d), run_label, now),
            )
        conn.commit()

        rows = []
        for a, b, d in pairs:
            cur = conn.execute(
                "SELECT MIN(seen_at), COUNT(*) FROM swap_sightings WHERE store_a=? AND store_b=? AND bucket_date=?",
                (a, b, str(d)),
            )
            first_seen, times_seen = cur.fetchone()
            rows.append({
                "Store A": a, "Store B": b, "Date": d,
                "First Seen": first_seen, "Times Seen (Including This Run)": times_seen,
                "Status": "NEW" if times_seen <= 1 else f"RECURRING -- unresolved since {first_seen}",
            })
        conn.close()
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        # Persistence is additive, not load-bearing -- degrade gracefully.
        return pd.DataFrame(
            [{"Store A": a, "Store B": b, "Date": d, "First Seen": now,
              "Times Seen (Including This Run)": 1, "Status": "NEW (history unavailable this run)"}
             for a, b, d in pairs],
            columns=cols,
        )

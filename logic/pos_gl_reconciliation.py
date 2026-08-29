"""
logic/pos_gl_reconciliation.py

CHANGE HISTORY (most recent first) -- kept here because this module has been
patched several times against real production files, and each pass fixed a
real, evidence-based problem. Read this before changing the matching logic
again.

PASS 10 / V42 "Audit Integrity & Master Data" (2026-08-28) -- a small,
focused set of fixes from the user's review of the actual V41 files, again
explicitly NOT touching the reconciliation mathematics:
  1. Deterministic Run Signature -- Python's built-in hash() is process-
     salted by design (PYTHONHASHSEED) and can differ for the identical
     input across app restarts; the page computed Run Signature with it,
     so the same exact upload set could get a different signature after a
     redeploy. Now computed as SHA256 over a sorted, canonical
     serialization of the upload signatures instead.
  2. Import Audit frozen into the result -- previously the Excel export
     read Import Audit from st.session_state.v53_import_audit, which could
     describe a different file population than the reconciliation result
     next to it (e.g. after a later Validate click). Now built from the
     SAME pos_audit/gl_audit that fed this exact reconcile_pos_to_gl_by_
     bucket() call and attached to the result dict itself (r["import_audit"]),
     alongside "summary" -- the export can no longer mix populations.
  3. (Fixed together with #2) The RUN path's "reuse validated data" branch
     and its "reparse" branch both now populate the SAME import_audit that
     gets attached to the result -- previously only the reparse branch
     refreshed session-state audit, so a Validate-then-RUN-different-files
     sequence without clicking Validate again could export a stale audit.
  4. GL completeness wording corrected -- "silently excluded" no longer
     describes what happens once V41's Import Audit and this Validate
     panel exist; changed to "excluded from reconciliation totals and
     reported below."
  5. Blank-provider POS activity gets its own visible count. V41's
     coverage split intentionally treats a blank Provider value as
     "mappable" (so it doesn't spuriously trigger PROVIDER MAPPING
     REQUIRED), but that also meant a bucket with real blank-provider POS
     activity had no dedicated visibility. New per-bucket "POS Rows With
     Blank Provider"/"POS Amount With Blank Provider (SAR)" columns, a
     bucket-summary total, and a reason-text note when a bucket with
     uncovered GL also has meaningful blank-provider POS activity.
  6. Provider->GL mapping can now be taught without a code deployment.
     New logic/provider_gl_mapping.py: a self-contained, additive
     Provider(+optional Store)->GL account override table (same SQLite
     architecture as logic/swap_tracking.py, same disclosed Streamlit-
     Community-Cloud persistence caveat -- NOT migrated to a durable
     backend this pass, an explicitly separate, deferred item). The
     coverage computation in reconcile_pos_to_gl_by_bucket() and
     detect_incomplete_pos_provider_coverage() now check this override
     table FIRST, falling back to core._gl_expected_account_for_tender()
     unchanged when no override exists -- so a provider that already
     resolves correctly today behaves identically; this only adds a way to
     teach the app a new one. The page gained a small inline "Add a
     provider mapping" admin form in the Validate step.
  8. Chronic banner wording broadened -- the page's chronic-store banner
     used to say "this usually means a missing POS/provider file", which
     stopped being reliably true once V41 split chronic causes four ways.
     Now says the store has a persistent control failure and points at the
     Failure Pattern column instead of guessing the cause in the banner
     text.
  10. Row-to-row mode labeled "Diagnostic / Legacy" in the granularity
      picker, with help text explaining it doesn't carry V40/V41's control
      stack (provider coverage, chronic detection, import audit, run
      metadata, stronger Overall Status) -- it was drifting further out of
      sync with the production (bucket) path every pass without anything
      on screen saying so.

Deliberately NOT done this pass, per the user's own scoping of V42 as
"small and focused" (each explicitly flagged as a separate, open item, not
silently dropped): splitting QUARANTINED into parser-error vs unknown-
format sub-reasons (explicitly framed by the user as prep for the still-
pending generic Universal POS auto-mapper, a separate future pass); moving
swap_tracking.py's sightings table off local SQLite onto a durable backend
(the same open caveat that module's own docstring has always disclosed,
now shared by provider_gl_mapping.py rather than solved for one new table
and not the other).

PASS 9 / V41 "Production Reliability" (2026-08-28) -- ten more fixes from
the user's line-by-line review of the actual V40 files, explicitly NOT
touching the reconciliation mathematics (Store+Date bucket key, GL MATCHED
determination) again:
  1. Stale validation/result state auto-invalidates. The page now computes
     the CURRENT upload signature once per rerun and compares it against
     what Validate/RUN actually used; a mismatch clears v53_validated (with
     a "Uploads changed" banner) and flags a stale-result banner over the
     dashboard, instead of silently continuing to show old normalized data
     or an old result next to a changed uploader.
  2. Run metadata frozen into the result. reconcile_pos_to_gl_by_bucket()
     gained optional run_id/run_signature/pos_file_count/gl_file_count/
     run_timestamp params, stored verbatim in `summary`; the page passes
     these at RUN time and reads "Files Loaded" from them, not from the
     live pos_pairs/gl_pairs lists that can drift after a run.
  3. Unique source identity per upload. build_pos_dataset()/
     build_gl_dataset() now pass core.normalize_pos()/normalize_d365_gl() a
     filename+SHA256[:8]+sheet internal name ("source_key"), while a clean
     filename+sheet ("source_file") is kept for anything shown to Finance.
     Two uploads sharing a filename but different content are no longer
     silently grouped together by every duplicate-detection groupby.
  4. Import Audit / Quarantine. Both build functions now return
     (dataset, audit) -- one row per (file, sheet) actually attempted,
     Status OK/SKIPPED/FILTERED/QUARANTINED with a Failure Reason. The
     broad `except Exception: continue` that used to make a bad file/sheet
     vanish with no trace is now visible in the Validate step and in the
     Excel export.
  5. UPLOAD INCOMPLETE vs PROVIDER MAPPING REQUIRED. A bucket's uncovered
     GL is now only called UPLOAD INCOMPLETE when every POS provider in the
     bucket mapped cleanly; if an unmapped provider value is present
     instead, the bucket is tagged PROVIDER MAPPING REQUIRED so Finance
     doesn't go looking for a missing file when the real issue is a
     master-data mapping gap. (Required fixing covered_diff to compare
     against POS total restricted to mappable providers only -- see the
     comment at that computation.)
  6. Uncovered GL Absolute Exposure. Kept the signed "Uncovered GL Activity
     (SAR)" figure but added an absolute-value sum alongside it -- the
     signed figure can have positive/negative buckets cancel out and
     understate real exposure.
  7. Accounting Residual Severity. Full Variance Severity (renamed from
     "Severity") stays the headline materiality tag; a new Accounting
     Residual Severity applies the same scale to covered_diff alone, so a
     bucket that only LOOKS extreme because most of its variance is
     uncovered provider activity doesn't read the same as one whose real
     covered-account residual is actually that large.
  8. GL row duplicate exclusion made visible, not just configurable. The
     checkbox already existed; its label now states the full 6-field key
     (V40 added Signed Amount) and a caption surfaces the actual excluded
     count with a plain-language note on the residual risk whenever it's
     nonzero.
  9. Chronic classification split four ways. detect_chronic_exception_stores()
     now attributes a chronic store's failing days to Upload Incomplete,
     Amount Variance, GL Not Posted, or Unmatched GL (whichever dominates),
     or CHRONIC (MIXED CAUSES) with a per-cause breakdown -- V40's two-way
     split treated GL Not Posted and Unmatched GL as the same "not upload
     incomplete" bucket, hiding that they're different control failures.
 10. Two UI corrections: the Top 20 Exceptions caption no longer claims
     severity-first ordering (V40 item 8 sorts by absolute difference
     alone); and the Excel export has always written 10 sheets in bucket
     mode (now 11 with Import Audit), not 9 as an earlier write-up said.

PASS 8 / V40 "Production Controls" (2026-08-28) -- ten fixes from the user's
line-by-line review of the actual PASS 7 files, in the user's stated
priority order. Note on naming: the user described item 1 as "restoring
V38 Daily Provider Coverage" -- to be transparent, this specific per-
Store+Date GL/provider coverage SPLIT inside the bucket match itself did
not exist in any earlier pass under any name. PASS 5/V36 added
detect_incomplete_pos_provider_coverage(), a STORE-WIDE (not per-date)
coverage WARNING shown in the Validate step; this pass's V38 was page 1
adapter wiring, unrelated. What follows is a genuinely new capability,
built exactly to the behavior the user specified, not a restoration of
something that regressed.
  1. [HIGHEST PRIORITY] Per-Store+Date GL provider coverage split. Before
     this pass, a GL AMOUNT EXCEPTION bucket's "GL Total" summed every
     clearing account posted for that Store+Date, even when some of that
     GL activity had no POS/provider file uploaded for that EXACT date
     (detect_incomplete_pos_provider_coverage only ever checked "was this
     provider uploaded ANYWHERE in the store's whole upload", not per-date,
     so it could never catch or correct this). Now, for every bucket, POS
     providers actually present for that Store+Date are mapped to their
     expected D365 clearing accounts (core._gl_expected_account_for_tender,
     the same mapping trace_d365_source_to_gl already uses, including the
     Store 613 TAP/TAP_GATEWAY dual-account override); GL activity in any
     other clearing account for that bucket is split out as
     gl_total_uncovered. If removing that uncovered GL amount brings POS
     Total and the remaining (covered) GL Total within tolerance, the
     bucket is now tagged UPLOAD INCOMPLETE instead of GL AMOUNT EXCEPTION
     -- the reason text names the specific uncovered account(s) and dollar
     amount. If uncovered GL activity exists but does NOT fully explain the
     gap, the bucket stays GL AMOUNT EXCEPTION (a real accounting question)
     but its reason text now also names the uncovered amount as a
     contributing factor, instead of silently folding it into one
     unexplained number. Bucket key, tolerance logic and GL MATCHED
     determination (based on the FULL bucket difference) are unchanged.
  2. Swap-history run-level idempotency (logic/swap_tracking.py). Streamlit
     reruns the whole page script on every widget interaction; the swap-
     tracking call sat in that unconditional display block, so one real
     reconciliation run could log 2, 3, 4+ sightings of the same swap from
     UI noise alone, inflating "Times Seen". Fixed with a `run_id` generated
     once per actual RUN-button click (pages/35_POS_GL_Reconciliation.py,
     stored in st.session_state so later reruns of the same result reuse
     it) and an idempotent insert keyed on (run_id, store_a, store_b,
     bucket_date) -- see swap_tracking.py's own change history for the
     schema-migration details.
  3. Removed the filename-only pre-filter (`if item[0] not in _seen`) on
     both POS and GL upload collection in the page -- it silently dropped a
     second file sharing an already-seen filename BEFORE SHA256/content
     duplicate detection ever ran, so a real same-name duplicate could
     never even be flagged. Every uploaded file now reaches the duplicate-
     control layer; none of the three duplicate tiers auto-excludes a file
     (unchanged), so this only affects what gets FLAGGED, not what gets
     summed.
  4. Validated-upload identity is now (filename, sha256(bytes)) instead of
     filename alone (`v53_pos_pairs_sig`/`v53_gl_pairs_sig` and the RUN
     button's `same_upload` check) -- a same-named re-upload with different
     content used to be silently treated as "the same upload" and could
     reuse stale cached normalized data.
  5. Overall Status is now derived from bucket statuses directly (`all
     bucket_status == GL MATCHED` and no IDENTIFIER MISMATCH / POS DATA
     INCOMPLETE rows), not from the POS-row-grain `exc` dataframe. A GL-only
     UNMATCHED GL bucket produces zero POS detail rows, so the old
     `exc.empty` check could say RECONCILED with real unmatched GL activity
     still outstanding.
  6. _flag_gl_duplicates()'s key now includes gl_signed_amount (previously
     Voucher+Journal+Main Account+Store+Date only) -- two legitimate GL
     lines sharing those five dimensions but posting different amounts
     could previously be wrongly treated as duplicates and one silently
     excluded from the GL total. File-level duplicate detection (tiered
     exact/probable/possible, all warning-only) remains the primary
     control; this keeps row-level GL exclusion conservative on top of it.
  7. Duplicate-file warnings in the Validate step are now severity-
     differentiated instead of one undifferentiated red banner: Exact ->
     st.error (red), Probable -> st.warning (orange), Possible -> st.info
     (blue/neutral) with wording that no longer asserts double-counting
     definitely occurred for that weakest tier -- possible duplicates are
     same row-count+total+date-range only, which the PASS 5 docstring
     itself already called out as something two different legitimate files
     could share by coincidence.
  8. top_exceptions now ranks ALL non-MATCHED bucket statuses together by
     absolute dollar difference (previously GL AMOUNT EXCEPTION only) --
     a large-dollar UNMATCHED GL, GL NOT POSTED or UPLOAD INCOMPLETE bucket
     no longer disappears from the executive Top 20 just because its status
     isn't GL AMOUNT EXCEPTION. Status/Reason columns are preserved so the
     type of problem stays visible in the ranked list.
  9. New validate_gl_completeness(gl) -- the GL-side equivalent of
     validate_pos_completeness(), checking every normalized GL row for a
     usable Store Code, GL Date, Main Account and Signed Amount before
     bucketing, wired into the page's Validate step next to the existing
     POS completeness check.
  10. detect_chronic_exception_stores() now splits a chronic store's
      failing days by cause using the new per-bucket coverage split from
      item 1: a new "Failure Pattern" column reads CHRONIC UPLOAD
      INCOMPLETE when >=60% of a chronic store's failing days are UPLOAD
      INCOMPLETE, CHRONIC ACCOUNTING VARIANCE when <=20% are, or CHRONIC
      (MIXED CAUSES) in between -- distinguishing "this store is probably
      missing a POS provider file all period" from "this store has a real
      recurring accounting break" instead of treating every non-matched day
      as the same kind of problem.

What did NOT change, per explicit instruction: the Store+Date(+Amount)
bucket key itself, the chronic-store/duplicate-date/severity controls'
core design (only chronic-store's classification was refined, item 10),
and the persistent-swap-tracking concept (only its run-level idempotency
was fixed, item 2).

PASS 7 (2026-08-28) -- four control-tower additions, all directly evidence-
based from report 5 (46 real files, 601 Store+Date buckets):
  1. Chronic-failure detection (detect_chronic_exception_stores) -- report 5
     showed Store 613 failing on 31/31 days of July, GL exceeding POS every
     single day, 23.6% of the entire run's net difference. That's a
     different, more serious signal than an isolated exception and was
     sitting unflagged as 31 separate rows in Top 20 Exceptions/bucket
     summary. Flags any store whose failure rate or longest consecutive-day
     failing streak crosses a threshold, with the store's total dollar
     exposure, so a systemic upload-completeness gap surfaces as ONE finding
     instead of being buried across dozens of individual bucket rows.
  2. Cross-store duplicate-date detection (detect_duplicate_date_signature)
     -- report 5's per-bucket duplicate counts, read one row at a time,
     hid a clear pattern: 07-04 and 07-10 each had 18-20 different stores
     showing excluded duplicate POS rows the same day -- the fingerprint of
     a whole day's POS export being uploaded twice. Existing duplicate
     detection is file-by-file; this rolls the already-computed per-bucket
     "Duplicate POS Rows Excluded" counts up by DATE across all stores, so
     that pattern is one flagged finding instead of something a human has
     to notice by eyeballing 601 rows (which is how it was actually found).
  3. Extreme-variance severity tagging (_severity(), new "Severity" column
     on bucket_summary/top_exceptions) -- Store 644's 07-27 bucket (43x
     ratio, SAR 472K) fell through every existing reason pattern into
     generic "needs manual review" and could get lost among 364 other
     GL AMOUNT EXCEPTION buckets. Buckets whose ratio or absolute
     difference crosses a materiality threshold are now tagged EXTREME/
     HIGH/NORMAL and the reason text says so explicitly, so the single
     biggest dollar risk in a run is never just one row among hundreds.
  4. Persistent swap tracking (new logic/swap_tracking.py) -- the Store
     633<->659 swap first found in report 4 was still present, unchanged,
     in report 5 weeks later. The swap detector re-finds it fresh every run
     with no memory of having reported it before. New self-contained SQLite
     module (same pattern as the V28 Run History module) records every
     detected swap pair and annotates each run's swaps as NEW vs RECURRING
     (with first-seen date and times-seen count), so a swap that keeps
     coming back reads as an unresolved, escalating problem instead of a
     fresh-looking one-off every time.

PASS 6 (2026-08-27) -- Universal POS Import, adapters phase (per user's
"Universal POS Import" guide). Added logic/pos_format_adapters.py: a
pre-processing layer that detects three new named bank formats
(ADCB_CHAIN_DAILY, NBK_MERCHANT_STATEMENT, ANB_HIVE_POS) from their raw
column signatures and renames those columns onto synonym strings
core.normalize_pos() already recognizes, then calls it unchanged. Zero
lines of core.py touched, deliberately -- V32's audit found the real repo
already has newer core.py changes (V40-V44) not reflected in any local copy
this session has, so editing/re-delivering core.py directly risked
reverting fixes this session can't see. build_pos_dataset() now routes the
generic (non-AMEX/TABBY/TAMARA/TAP) parsing path through
pos_format_adapters.normalize_pos_universal() instead of calling
core.normalize_pos() directly; every previously-supported format's path is
untouched (the new detector only fires on the three new signatures). Also
added a new internal `reversal_amount` column (0.0 for all formats except
NBK_MERCHANT_STATEMENT's preserved RETURN rows) -- audit/reference only,
not yet surfaced in the bucket-reconciliation output tables (a follow-on,
not done in this pass). The generic fallback auto-mapper (confidence
scoring + pos_format_knowledge.json persistence) from the same guide is
explicitly NOT part of this pass -- separate, larger follow-on.

PASS 5 (2026-08-27) -- fixes to PASS 4 found by the user reading the actual
delivered code, not just the change history. All were real bugs/gaps:
  1. CRITICAL: the "GL Matched"/"GL Amount Exceptions" summary counts were
     counting POS-transaction rows (d[d.Status=="..."]), not Store+Date
     buckets -- a single matched bucket with 350 POS rows showed as
     "Matched = 350" on the dashboard, even though the real accounting
     match is 1 bucket. Now counted at the bucket level (`merged`), with
     POS/GL row counts reported separately and clearly labeled.
  2. CRITICAL: bucket_tolerance = tolerance * max(pos_count, gl_count) had
     no ceiling -- a bucket with 5,000 POS rows and a SAR 0.50 per-line
     tolerance could silently accept a SAR 2,500 real difference as
     "GL MATCHED". Added a hard max_bucket_tolerance ceiling (default SAR
     25.00, configurable) -- bucket_tolerance is now
     min(per-line tolerance * count, max_bucket_tolerance), never
     unbounded.
  3. The POS-row-grain detail table repeated the bucket's GL total and
     difference on every individual POS row under the generic "GL Amount"/
     "Difference" column names, which reads as if each POS transaction
     individually matched that amount. Renamed to "Bucket GL Total"/
     "Bucket Difference"/"Bucket POS Total" plus an explicit "Match Level"
     column, so it's unambiguous this is a bucket-level figure repeated for
     reference, not a per-transaction match.
  4. New dedicated UPLOAD COMPLETENESS control
     (detect_incomplete_pos_provider_coverage) -- when a GL clearing
     account has no matching POS provider uploaded anywhere for that
     store, that's flagged as a likely missing POS file, separate from
     the accounting exceptions list (was previously only inferrable from
     the exception reason text).
  5. New GL sign-direction preflight (validate_gl_sign_convention) -- a
     control/warning, not an auto-correction, since which sign D365 uses
     for a clearing-account balance is a Finance configuration fact this
     code should never guess at.
  6. Duplicate-file detection is now three-tier: 🔴 Exact (SHA256
     byte-identical), 🟠 Probable (>=90% of individual transactions --
     Store+Date+Amount -- match between the two files), 🟡 Possible (same
     row count + total + date range only, which two different legitimate
     daily files could in principle share by coincidence). None of the
     three tiers auto-excludes a file from processing -- all are shown as
     warnings for a human to resolve before running, exactly as before.

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
try:
    from . import pos_format_adapters
except ImportError:
    # Fallback for ad-hoc/standalone execution outside the `logic` package
    # (e.g. a flat test harness) -- the real Streamlit app always resolves
    # the package-relative import above.
    import pos_format_adapters
try:
    from . import provider_gl_mapping
except ImportError:
    import provider_gl_mapping


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


def _dup_key_disp_cols(dataset):
    """
    V41 item 3: duplicate-detection grouping now uses "source_key" (a
    filename+SHA256[:8]+sheet internal identity -- see build_pos_dataset/
    build_gl_dataset) instead of the plain "source_file" display name, so
    two uploads sharing a filename but different content are never grouped
    together by the identity check. "source_file" (clean, no hash) is kept
    for reporting file_a/file_b to the user. Falls back to "source_file" for
    both if "source_key" isn't present (e.g. an older/synthetic dataset in
    a test), so this stays backward compatible.
    """
    key_col = "source_key" if "source_key" in dataset.columns else "source_file"
    disp_col = "source_file" if "source_file" in dataset.columns else key_col
    return key_col, disp_col


def _content_duplicates(dataset, amount_col, date_col):
    """
    Shared implementation for detect_content_duplicate_pos/gl. Groups the
    ALREADY-NORMALIZED dataset by source identity and compares (row count,
    total of the real amount column, date range) -- deliberately built on
    the business amount/date fields core.py already identified, not raw
    file columns, so ID-like columns (Terminal ID, Merchant ID, Card
    Number...) can never dominate the signature and cause false positives.
    """
    if dataset is None or dataset.empty:
        return []
    key_col, disp_col = _dup_key_disp_cols(dataset)
    g = dataset.groupby(key_col).agg(
        rows=(amount_col, "size"), total=(amount_col, "sum"),
        dmin=(date_col, "min"), dmax=(date_col, "max"),
        disp=(disp_col, "first"),
    )
    dupes = []
    seen = {}
    for src, row in g.iterrows():
        sig = (int(row["rows"]), round(float(row["total"]) if pd.notna(row["total"]) else 0.0, 2),
               str(row["dmin"]), str(row["dmax"]))
        base_name = str(src).split(" [")[0]
        prior = seen.get(sig)
        if prior and prior[1].split(" [")[0] != base_name:
            dupes.append({"file_a": prior[0], "file_b": row["disp"],
                          "reason": f"Same row count ({int(row['rows'])}), same total amount (~SAR {row['total']:,.2f}), same date range -- looks like the same data under a different filename."})
        else:
            seen.setdefault(sig, (row["disp"], src))
    return dupes


def detect_content_duplicate_pos(pos_dataset):
    """pos_dataset: output of build_pos_dataset(). 🟡 POSSIBLE tier -- see
    _content_duplicates(). Same row count + total + date range only; two
    different legitimate daily files could in principle share this by
    coincidence, so this tier is a prompt to look, never proof."""
    return _content_duplicates(pos_dataset, "pos_amount", "pos_date")


def detect_content_duplicate_gl(gl_dataset):
    """gl_dataset: output of build_gl_dataset(). 🟡 POSSIBLE tier -- see
    detect_content_duplicate_pos()."""
    return _content_duplicates(gl_dataset, "gl_signed_amount", "gl_date")


def _transaction_fingerprint(dataset, amount_col, date_col):
    """Per source identity (source_key -- see _dup_key_disp_cols), the set
    of (Store Code, Date, rounded Amount) tuples for that file's rows --
    used by _probable_duplicates() to test whether two files contain the
    SAME underlying transactions, which is much stronger evidence than
    matching row count/total/date-range alone. Returns (fingerprints,
    display_names) so callers can report the clean filename to the user
    while grouping on the hash-qualified identity."""
    if dataset is None or dataset.empty:
        return {}, {}
    key_col, disp_col = _dup_key_disp_cols(dataset)
    d = dataset.copy()
    d["_fp_date"] = pd.to_datetime(d[date_col], errors="coerce").dt.date.astype(str)
    d["_fp_amt"] = pd.to_numeric(d[amount_col], errors="coerce").round(2)
    fps = {src: set(zip(grp["store_code"], grp["_fp_date"], grp["_fp_amt"]))
           for src, grp in d.groupby(key_col)}
    disp = {src: grp[disp_col].iloc[0] for src, grp in d.groupby(key_col)}
    return fps, disp


def _probable_duplicates(dataset, amount_col, date_col, min_overlap=0.90, min_rows=5):
    """
    🟠 PROBABLE tier: flags a pair of files where at least `min_overlap`
    (default 90%) of one file's individual (Store+Date+Amount) transactions
    are also present in the other file. This is deliberately a stronger,
    separate test from _content_duplicates()'s row-count/total/date-range
    check (🟡 POSSIBLE), per the explicit feedback that two different
    legitimate files could coincidentally share a row count/total/date
    range without actually being the same data.
    """
    fps, disp = _transaction_fingerprint(dataset, amount_col, date_col)
    names = [n for n, s in fps.items() if len(s) >= min_rows]
    dupes = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_key, b_key = names[i], names[j]
            if a_key.split(" [")[0] == b_key.split(" [")[0]:
                continue  # same source file, different sheet -- not a duplicate upload
            a, b = fps[a_key], fps[b_key]
            overlap = len(a & b) / min(len(a), len(b))
            if overlap >= min_overlap:
                dupes.append({"file_a": disp.get(a_key, a_key), "file_b": disp.get(b_key, b_key),
                              "reason": f"{overlap:.0%} of individual transactions (Store+Date+Amount) in these files are identical -- almost certainly the same underlying data uploaded twice."})
    return dupes


def detect_probable_duplicate_pos(pos_dataset):
    """pos_dataset: output of build_pos_dataset(). 🟠 PROBABLE tier."""
    return _probable_duplicates(pos_dataset, "pos_amount", "pos_date")


def detect_probable_duplicate_gl(gl_dataset):
    """gl_dataset: output of build_gl_dataset(). 🟠 PROBABLE tier."""
    return _probable_duplicates(gl_dataset, "gl_signed_amount", "gl_date")


def detect_duplicate_files(pairs, dataset=None, amount_col=None, date_col=None):
    """
    Convenience wrapper combining all three tiers -- exact-byte (always
    available) with probable/possible (only if a normalized `dataset` is
    supplied -- pass the build_pos_dataset()/build_gl_dataset() output with
    amount_col="pos_amount"/date_col="pos_date" or
    amount_col="gl_signed_amount"/date_col="gl_date").
    """
    exact = detect_exact_duplicate_files(pairs)
    probable = _probable_duplicates(dataset, amount_col, date_col) if dataset is not None and amount_col else []
    possible = _content_duplicates(dataset, amount_col, date_col) if dataset is not None and amount_col else []
    return {"exact_duplicates": exact, "probable_duplicates": probable, "possible_duplicates": possible,
            "has_duplicates": bool(exact or probable or possible)}


# ---------------------------------------------------------------------------
# Normalization (unchanged from PASS 1/2: reuse core.py's proven parsers)
# ---------------------------------------------------------------------------

_AUDIT_COLS = ["File", "Sheet", "Detected Type", "Rows Loaded", "Parser", "Status", "Failure Reason"]


def build_pos_dataset(pos_pairs):
    """pos_pairs: list of (filename, bytes). Returns (dataset, audit) where
    dataset has the internal matching schema (merchant_id, store_code,
    provider, reference, auth_code, pos_date, pos_amount, source_file,
    source_key, source_row) and audit is an Import Audit / Quarantine
    dataframe (V41 item 4) -- one row per (file, sheet) actually attempted,
    whether it succeeded, was skipped (settlement/payout), or was
    quarantined (couldn't be parsed at all). Before this pass, a broad
    `except Exception: continue` meant a file/sheet that failed to parse
    simply vanished from the run with no visible trace.
    """
    parts = []
    audit_rows = []
    for name, data in pos_pairs:
        sha8 = hashlib.sha256(data).hexdigest()[:8]
        try:
            sheets = _sheets_for(name, data)
        except Exception as e:
            sheets = {}
        if not sheets:
            audit_rows.append({"File": name, "Sheet": "", "Detected Type": "", "Rows Loaded": 0,
                                "Parser": "core.read_upload", "Status": "QUARANTINED",
                                "Failure Reason": "File could not be read at all (unsupported format, corrupt file, or no readable sheets)."})
            continue
        for sheet, df in sheets.items():
            # V41 item 3: internal_name carries a short content hash so two
            # uploads sharing a filename (but different bytes) get distinct
            # source identity for every downstream duplicate-detection
            # group-by; display_name (no hash) is what Finance ever sees.
            display_name = f"{name} [{sheet}]"
            internal_name = f"{name}#{sha8} [{sheet}]"
            if df is None or df.empty:
                audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": "", "Rows Loaded": 0,
                                    "Parser": "", "Status": "QUARANTINED",
                                    "Failure Reason": "Sheet is empty after header detection."})
                continue
            # Skip provider payout/settlement sheets -- those are bank-side
            # evidence, not POS transaction rows, and would corrupt identity
            # matching if normalized as POS transactions.
            try:
                if core.classify_settlement_source(f"{name}-{sheet}", df):
                    audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": "SETTLEMENT/PAYOUT",
                                        "Rows Loaded": 0, "Parser": "core.classify_settlement_source (skipped)",
                                        "Status": "SKIPPED",
                                        "Failure Reason": "Bank-side settlement/payout sheet, not a POS transaction sheet -- intentionally excluded from POS matching, not a parser failure."})
                    continue
            except Exception:
                pass
            typ = None
            try:
                typ = core.classify(f"{name}-{sheet}", df)
            except Exception:
                pass
            forced = typ if typ in {"AMEX", "TABBY", "TAMARA", "TAP"} else None
            n = None
            named_fmt = None
            parser_used = ""
            failure_reason = ""
            try:
                if forced is None:
                    # Named-bank-format pre-processing (Universal POS Import
                    # guide, 2026-08-27): ADCB_CHAIN_DAILY /
                    # NBK_MERCHANT_STATEMENT / ANB_HIVE_POS get their raw
                    # columns renamed onto core.normalize_pos()'s existing
                    # synonym strings before it runs; every other format's
                    # path here is byte-identical to before (see
                    # logic/pos_format_adapters.py -- no core.py changes).
                    n, named_fmt = pos_format_adapters.normalize_pos_universal(df, internal_name)
                    parser_used = f"pos_format_adapters.normalize_pos_universal ({named_fmt or 'generic -> core.normalize_pos'})"
                else:
                    n = core.normalize_pos(df, internal_name, forced)
                    parser_used = f"core.normalize_pos (forced={forced})"
            except Exception as e:
                failure_reason = f"{type(e).__name__}: {e}"
            if n is None or n.empty:
                audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": typ or named_fmt or "",
                                    "Rows Loaded": 0, "Parser": parser_used, "Status": "QUARANTINED",
                                    "Failure Reason": failure_reason or "Parser returned no usable rows for this sheet."})
                continue
            n = n.copy()
            n["Source File"] = display_name
            n["Source Key"] = internal_name
            parts.append(n)
            audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": typ or named_fmt or "GENERIC",
                                "Rows Loaded": len(n), "Parser": parser_used, "Status": "OK", "Failure Reason": ""})

    cols = ["merchant_id", "store_code", "provider", "reference", "auth_code",
            "pos_date", "pos_amount", "reversal_amount", "source_file", "source_key", "source_row"]
    audit = pd.DataFrame(audit_rows, columns=_AUDIT_COLS) if audit_rows else pd.DataFrame(columns=_AUDIT_COLS)
    if not parts:
        return pd.DataFrame(columns=cols), audit

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
        # Audit/reference only, mirrors the GL side's absolute-vs-signed
        # split: the row's own amount when a source marks it a return
        # (currently only NBK_MERCHANT_STATEMENT populates this via
        # pos_format_adapters.py), else 0.0. pos_amount itself is
        # unchanged -- returns already flow through the existing bucket
        # sums with whatever sign the source file gives them; this column
        # only makes a return visibly flagged, not a new total.
        "reversal_amount": (pd.to_numeric(pos["Reversal Amount"], errors="coerce").fillna(0.0)
                             if "Reversal Amount" in pos.columns else 0.0),
        "source_file": pos["Source File"],
        "source_key": pos["Source Key"],
    })
    out["source_row"] = range(2, len(out) + 2)
    return out, audit


def build_gl_dataset(gl_pairs):
    """gl_pairs: list of (filename, bytes). Returns (dataset, audit) --
    dataset has the internal matching schema (merchant_id, store_code,
    provider, reference, auth_code, gl_date, gl_amount [absolute, reference
    only], gl_signed_amount [used for bucket sums], main_account, voucher,
    journal, source_file, source_key, source_row); audit is the same Import
    Audit / Quarantine shape as build_pos_dataset() (V41 item 4)."""
    parts = []
    audit_rows = []
    for name, data in gl_pairs:
        sha8 = hashlib.sha256(data).hexdigest()[:8]
        try:
            sheets = _sheets_for(name, data)
        except Exception:
            sheets = {}
        if not sheets:
            audit_rows.append({"File": name, "Sheet": "", "Detected Type": "", "Rows Loaded": 0,
                                "Parser": "core.read_upload", "Status": "QUARANTINED",
                                "Failure Reason": "File could not be read at all (unsupported format, corrupt file, or no readable sheets)."})
            continue
        for sheet, df in sheets.items():
            # V41 item 3: same hash-qualified internal identity as POS.
            display_name = f"{name} [{sheet}]"
            internal_name = f"{name}#{sha8} [{sheet}]"
            if df is None or df.empty:
                audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": "", "Rows Loaded": 0,
                                    "Parser": "", "Status": "QUARANTINED",
                                    "Failure Reason": "Sheet is empty after header detection."})
                continue
            n = None
            failure_reason = ""
            try:
                n = core.normalize_d365_gl(df, internal_name)
            except Exception as e:
                failure_reason = f"{type(e).__name__}: {e}"
            if n is None or n.empty:
                audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": "D365 GL", "Rows Loaded": 0,
                                    "Parser": "core.normalize_d365_gl", "Status": "QUARANTINED",
                                    "Failure Reason": failure_reason or "Parser returned no usable rows for this sheet."})
                continue
            n = n.copy()
            n["Source File"] = display_name
            n["Source Key"] = internal_name
            parts.append(n)
            audit_rows.append({"File": name, "Sheet": sheet, "Detected Type": "D365 GL", "Rows Loaded": len(n),
                                "Parser": "core.normalize_d365_gl", "Status": "OK", "Failure Reason": ""})

    cols = ["merchant_id", "store_code", "provider", "reference", "auth_code",
            "gl_date", "gl_amount", "gl_signed_amount", "main_account", "voucher",
            "journal", "source_file", "source_key", "source_row"]
    audit = pd.DataFrame(audit_rows, columns=_AUDIT_COLS) if audit_rows else pd.DataFrame(columns=_AUDIT_COLS)
    if not parts:
        return pd.DataFrame(columns=cols), audit

    gl = pd.concat(parts, ignore_index=True)

    # Only clearing-account rows are ever comparable to a POS/provider
    # statement -- real D365 "General journal account entry" exports carry
    # Sales/COGS/Tax/Discount/Inventory postings under the same Store
    # dimension. This is the same filter core.trace_d365_source_to_gl() and
    # related functions already apply
    # (`actual_gl[actual_gl["Controlled Clearing Account"].fillna(False)]`).
    gl_all_parsed_count = len(gl)
    gl = gl[gl["Controlled Clearing Account"].fillna(False)].copy()
    # Rows dropped by this filter are legitimate D365 lines (Sales/COGS/Tax/
    # Discount/Inventory, etc.) that are correctly out of scope for clearing
    # reconciliation -- not a parser failure -- but V41 item 4 records the
    # drop in the audit for transparency rather than letting it vanish
    # silently.
    dropped = gl_all_parsed_count - len(gl)
    if dropped:
        audit_rows.append({"File": "(all GL files)", "Sheet": "", "Detected Type": "Non-clearing GL lines",
                            "Rows Loaded": 0, "Parser": "Controlled Clearing Account filter", "Status": "FILTERED",
                            "Failure Reason": f"{dropped} GL row(s) across all files are not on a controlled clearing account -- correctly excluded from POS/GL clearing reconciliation, not a parser failure."})
        audit = pd.DataFrame(audit_rows, columns=_AUDIT_COLS)
    if gl.empty:
        return pd.DataFrame(columns=cols), audit

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
        "source_key": gl["Source Key"],
    })
    out["source_row"] = range(2, len(out) + 2)
    return out, audit


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
# GL-side completeness control (V40 item 9) -- POS has had this preflight
# since PASS 4; GL never did, so a GL row that silently can't be bucketed
# (and is therefore just missing from every bucket's GL Total with no
# warning at all) had no dedicated control of its own.
# ---------------------------------------------------------------------------

def validate_gl_completeness(gl):
    """
    GL-side equivalent of validate_pos_completeness(): checks every
    normalized GL row for a usable Store Code, GL Date, Main Account and
    Signed Amount BEFORE bucketing. A row missing any of these can't be
    allocated to a Store+Date bucket (Store Code/GL Date) or would corrupt
    the bucket sum / coverage split (Main Account/Signed Amount) -- meant to
    be shown in the Validate step next to the POS completeness check, not
    discovered later as an unexplained gap in GL Total.
    """
    if gl is None or gl.empty:
        return {"total_rows": 0, "missing_store": 0, "missing_date": 0,
                "missing_account": 0, "missing_amount": 0, "clean_rows": 0, "sample": gl}
    missing_store = gl["store_code"] == ""
    missing_date = gl["gl_date"].isna()
    missing_account = gl["main_account"] == ""
    missing_amount = pd.to_numeric(gl["gl_signed_amount"], errors="coerce").isna()
    bad = missing_store | missing_date | missing_account | missing_amount
    sample = gl[bad].copy()
    sample["Missing Store Code"] = missing_store[bad]
    sample["Missing GL Date"] = missing_date[bad]
    sample["Missing Main Account"] = missing_account[bad]
    sample["Missing Signed Amount"] = missing_amount[bad]
    return {
        "total_rows": len(gl),
        "missing_store": int(missing_store.sum()),
        "missing_date": int(missing_date.sum()),
        "missing_account": int(missing_account.sum()),
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
# Dedicated UPLOAD COMPLETENESS control -- separate from accounting
# exceptions. A GL AMOUNT EXCEPTION caused by a forgotten POS provider file
# is an upload problem, not a real reconciliation break, and should not be
# presented to Finance as one.
# ---------------------------------------------------------------------------

def detect_incomplete_pos_provider_coverage(pos, gl, mapping_db_path=None):
    """
    For every Store Code appearing in GL, checks whether every D365
    clearing account posted for that store is "covered" by at least one
    POS provider seen anywhere in the POS upload for that store (using the
    same provider -> expected clearing account resolution
    reconcile_pos_to_gl_by_bucket() uses for its own per-bucket coverage
    split -- Admin-maintained overrides from provider_gl_mapping.py FIRST,
    falling back to core._gl_expected_account_for_tender() unchanged). A GL
    clearing account with zero matching POS provider coverage for that
    store is a strong, specific signal that a provider's POS file (e.g.
    TABBY, TAMARA, CASH) was never uploaded for that store -- not that the
    GL posting itself is wrong.

    This does NOT look at dates/amounts at all, deliberately: it is a
    coverage check (was this provider ever uploaded for this store?), run
    once up front, not a per-bucket accounting judgement.

    V42 item 6: `mapping_db_path` lets a caller point at a non-default
    provider_gl_mapping.py database (mainly for tests); the running app
    never needs to pass it.
    """
    if pos is None or pos.empty or gl is None or gl.empty:
        return []
    pos = pos[pos["store_code"] != ""].copy()
    gl = gl[gl["store_code"] != ""].copy()
    if pos.empty or gl.empty:
        return []

    _override_cache = provider_gl_mapping.load_override_map(mapping_db_path)
    covered_by_store = {}
    for store, grp in pos.groupby("store_code"):
        accounts = set()
        for prov in grp["provider"].dropna().unique():
            try:
                accts, _ = provider_gl_mapping.expected_accounts_for_provider(
                    prov, store, core_fn=core._gl_expected_account_for_tender,
                    _override_cache=_override_cache,
                )
                accounts |= accts
            except Exception:
                pass
        covered_by_store[store] = accounts

    warnings = []
    for store, grp in gl.groupby("store_code"):
        gl_accounts = set(grp["main_account"].unique()) & set(core.D365_CLEARING_ACCOUNT_MAP.keys())
        covered = covered_by_store.get(store, set())
        for acct in sorted(gl_accounts - covered):
            info = core.D365_CLEARING_ACCOUNT_MAP.get(acct, {})
            group = info.get("group", acct)
            warnings.append({
                "store_code": store, "missing_account": acct, "missing_provider_group": group,
                "message": (f"Store {store}: D365 GL posts to {info.get('account_name', acct)} ({acct}) "
                            f"but no matching POS {group} file was found anywhere in this upload for "
                            f"that store -- check for a missing/forgotten {group} POS file before "
                            f"treating this store's variance as a real reconciliation break."),
            })
    return warnings


# ---------------------------------------------------------------------------
# GL sign-direction preflight -- a control/warning, not an auto-correction.
# Which sign D365 uses for a clearing-account balance is a Finance
# configuration fact this code should never silently guess at.
# ---------------------------------------------------------------------------

def validate_gl_sign_convention(pos, gl):
    """
    Compares the sign of POS Amount (always a positive sale amount) against
    the sign of GL Signed Amount across Store+Date buckets that have real
    activity (> SAR 1) on both sides. If GL Signed Amount is negative in
    the large majority of those buckets, the GL export's sign convention is
    probably inverted relative to POS Amount -- every bucket difference in
    the run should then be treated as suspect until Finance confirms what a
    positive vs negative Signed Amount is meant to represent for this
    clearing account.
    """
    if pos is None or pos.empty or gl is None or gl.empty:
        return {"checked": False}
    p = pos[(pos["store_code"] != "") & pos["pos_date"].notna() & pos["pos_amount"].notna()].copy()
    g = gl[(gl["store_code"] != "") & gl["gl_date"].notna() & gl["gl_signed_amount"].notna()].copy()
    if p.empty or g.empty:
        return {"checked": False}
    p["d"] = pd.to_datetime(p["pos_date"], errors="coerce").dt.normalize()
    g["d"] = pd.to_datetime(g["gl_date"], errors="coerce").dt.normalize()
    pos_sum = p.groupby(["store_code", "d"])["pos_amount"].sum()
    gl_sum = g.groupby(["store_code", "d"])["gl_signed_amount"].sum()
    common = [k for k in pos_sum.index.intersection(gl_sum.index)
              if abs(pos_sum[k]) > 1 and abs(gl_sum[k]) > 1]
    if len(common) < 5:
        return {"checked": False}
    negative_gl = sum(1 for k in common if gl_sum[k] < 0)
    ratio = negative_gl / len(common)
    suspected_inverted = ratio >= 0.80
    return {
        "checked": True, "buckets_compared": len(common),
        "negative_gl_buckets": negative_gl, "gl_negative_ratio": ratio,
        "suspected_inverted": suspected_inverted,
        "message": (
            f"{negative_gl}/{len(common)} Store+Date buckets have a NEGATIVE GL Signed Amount total "
            f"while POS Amount is positive -- the D365 export's sign convention for this clearing "
            f"account may be inverted relative to POS. Confirm with Finance what a positive vs "
            f"negative Signed Amount represents before treating differences in this run as real "
            f"exceptions."
        ) if suspected_inverted else
        f"GL Signed Amount sign looks consistent with POS Amount across {len(common)} buckets checked.",
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
    Flags GL rows sharing Voucher + Journal + Main Account + Store + Date +
    Signed Amount (Voucher/Journal numbers are meant to be unique per real
    D365 posting, so a repeated combination is a strong duplicate-upload
    signal). Signed Amount was added in V40 (item 6) -- without it, two
    legitimate GL lines sharing the other five dimensions but posting
    different amounts could be wrongly treated as duplicates and one
    silently excluded from the GL total. File-level duplicate detection
    (exact/probable/possible, all warning-only) stays the primary control;
    this keeps row-level GL exclusion conservative on top of it.
    """
    gl = gl.copy()
    gl["_dup_amt"] = pd.to_numeric(gl["gl_signed_amount"], errors="coerce").round(2)
    eligible = (gl["voucher"] != "") & (gl["journal"] != "") & (gl["store_code"] != "") & gl["gl_date"].notna() & gl["_dup_amt"].notna()
    key_cols = ["voucher", "journal", "main_account", "store_code", "gl_date", "_dup_amt"]
    group_dup = pd.Series(False, index=gl.index)
    extra_dup = pd.Series(False, index=gl.index)
    if eligible.any():
        sub = gl[eligible]
        group_dup.loc[sub.index] = sub.duplicated(subset=key_cols, keep=False)
        extra_dup.loc[sub.index] = sub.duplicated(subset=key_cols, keep="first")
    gl["is_duplicate_gl"] = group_dup
    gl["is_duplicate_gl_extra"] = extra_dup
    return gl.drop(columns=["_dup_amt"])


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


def _severity(pos_total, gl_total, diff, extreme_ratio=5.0, extreme_abs=50000.0):
    """
    Materiality tag for a GL AMOUNT EXCEPTION bucket -- EXTREME/HIGH/NORMAL.
    Added after report 5's single largest exception (Store 644, 07-27: a
    43x ratio, SAR 472K difference) fell through every pattern-based reason
    into generic "needs manual review" and was just one row among 364 other
    exception buckets, with nothing marking it as the biggest dollar risk in
    the run. Ratio catches extreme-multiple cases (duplicate/missing-file
    territory but bigger than the ~2x heuristic tolerates); absolute SAR
    catches large-difference cases even at a modest ratio. Thresholds are
    deliberately simple/explicit rather than percentile-based, so they're
    predictable and don't shift run to run.
    """
    diff = abs(diff or 0)
    pos_total = abs(pos_total or 0)
    gl_total = abs(gl_total or 0)
    ratio = None
    if pos_total and gl_total:
        ratio = max(pos_total, gl_total) / max(min(pos_total, gl_total), 0.01)
    if diff >= extreme_abs or (ratio is not None and ratio >= extreme_ratio):
        return "EXTREME"
    if diff >= extreme_abs / 5:
        return "HIGH"
    return "NORMAL"


# ---------------------------------------------------------------------------
# Chronic-failure detection: a store failing on nearly every date in the
# period is a different, more serious signal than isolated exceptions --
# see PASS 7 change history (Store 613, 31/31 days, 23.6% of report 5's
# entire net difference).
# ---------------------------------------------------------------------------

def detect_chronic_exception_stores(bucket_summary, min_days=5, min_failure_rate=0.80, min_consecutive_days=5,
                                     dominant_cause_share=0.60):
    """
    bucket_summary: reconcile_pos_to_gl_by_bucket()'s "bucket_summary" output
    (one row per Store+Date bucket). Flags any store whose non-MATCHED share
    of its own bucket-days meets `min_failure_rate`, OR whose longest run of
    CONSECUTIVE CALENDAR DAYS all failing meets `min_consecutive_days`.
    `min_days` guards against flagging a store that only appears a handful
    of times in the whole run (not enough data to call it chronic).

    V41 (item 9): a chronic store's failing days are split into FOUR cause
    buckets, not two -- GL NOT POSTED and UNMATCHED GL are different control
    failures from an amount variance and from a coverage gap, and lumping
    them together as "not accounting variance, so must be upload-related"
    (V40's two-way split) hid that distinction:
      - Upload Incomplete: UPLOAD INCOMPLETE + PROVIDER MAPPING REQUIRED
        days (both are coverage-gap causes, just with different certainty
        about whether a file is genuinely missing vs unmappable).
      - Amount Variance: GL AMOUNT EXCEPTION days -- a real accounting
        difference in covered accounts.
      - GL Not Posted: POS activity exists but no matching GL was found.
      - Unmatched GL: GL activity exists but no matching POS was found.
    "Failure Pattern" reads CHRONIC <cause> when one cause accounts for
    >= `dominant_cause_share` of the store's failing days, or CHRONIC
    (MIXED CAUSES) with a per-cause day-count breakdown otherwise.

    Returns a dataframe sorted by total dollar exposure, empty if nothing
    crosses the threshold. Deliberately separate from the exceptions list --
    this is a summary-of-summaries finding, not another row to scroll past.
    """
    cols = ["Store Code", "Total Days", "Failing Days", "Failure Rate",
            "Max Consecutive Failing Days", "Total Abs Difference (SAR)",
            "Failure Pattern", "Flag"]
    if bucket_summary is None or bucket_summary.empty:
        return pd.DataFrame(columns=cols)

    UPLOAD_FAMILY = {"UPLOAD INCOMPLETE", "PROVIDER MAPPING REQUIRED"}

    bs = bucket_summary.copy()
    bs["Date"] = pd.to_datetime(bs["Date"], errors="coerce")
    rows = []
    for store, grp in bs.groupby("Store Code"):
        grp = grp.dropna(subset=["Date"]).sort_values("Date")
        total_days = len(grp)
        if total_days < min_days:
            continue
        is_fail = grp["Status"] != "GL MATCHED"
        failing_days = int(is_fail.sum())
        failure_rate = failing_days / total_days if total_days else 0.0

        max_streak = cur_streak = 0
        prev_date = None
        for d, f in zip(grp["Date"], is_fail):
            if f:
                cur_streak = cur_streak + 1 if (prev_date is not None and (d - prev_date).days == 1) else 1
                max_streak = max(max_streak, cur_streak)
            else:
                cur_streak = 0
            prev_date = d

        if failure_rate >= min_failure_rate or max_streak >= min_consecutive_days:
            total_abs_diff = float(grp.loc[is_fail, "Difference"].abs().sum())
            fail_statuses = grp.loc[is_fail, "Status"]
            cause_counts = {
                "Upload Incomplete": int(fail_statuses.isin(UPLOAD_FAMILY).sum()),
                "Amount Variance": int((fail_statuses == "GL AMOUNT EXCEPTION").sum()),
                "GL Not Posted": int((fail_statuses == "GL NOT POSTED").sum()),
                "Unmatched GL": int((fail_statuses == "UNMATCHED GL").sum()),
            }
            dominant_cause, dominant_n = max(cause_counts.items(), key=lambda kv: kv[1])
            dominant_share = dominant_n / failing_days if failing_days else 0.0
            if dominant_share >= dominant_cause_share:
                pattern = f"CHRONIC {dominant_cause.upper()}"
                flag = f"CHRONIC -- DOMINANT CAUSE IS {dominant_cause.upper()} ({dominant_n}/{failing_days} FAILING DAYS)"
            else:
                pattern = "CHRONIC (MIXED CAUSES)"
                breakdown = ", ".join(f"{k}: {v}" for k, v in cause_counts.items() if v)
                flag = f"CHRONIC -- MIXED CAUSES ({breakdown}); INVESTIGATE EACH SEPARATELY"
            rows.append({
                "Store Code": store, "Total Days": total_days, "Failing Days": failing_days,
                "Failure Rate": round(failure_rate, 3), "Max Consecutive Failing Days": max_streak,
                "Total Abs Difference (SAR)": round(total_abs_diff, 2),
                "Failure Pattern": pattern, "Flag": flag,
            })

    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        out = out.sort_values("Total Abs Difference (SAR)", ascending=False).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# Cross-store duplicate-date detection: rolls up the already-computed
# per-bucket "Duplicate POS Rows Excluded" counts by DATE across every
# store, so a whole day's POS export apparently uploaded twice reads as one
# flagged finding instead of something only visible by eyeballing hundreds
# of individual bucket rows (see PASS 7 change history, report 5's 07-04/
# 07-10 pattern).
# ---------------------------------------------------------------------------

def detect_duplicate_date_signature(bucket_summary, min_stores=6, min_share=0.30):
    """
    bucket_summary: reconcile_pos_to_gl_by_bucket()'s "bucket_summary"
    output. For each Date, counts how many distinct stores had any
    Duplicate POS Rows Excluded that day; flags the date if that count (or
    its share of all stores active that day) crosses either threshold.
    This does NOT look at file names or content -- it's a pure rollup of
    the row-level duplicate detection already computed per bucket, exposing
    a pattern only visible today by reading the whole bucket table by hand.
    """
    cols = ["Date", "Stores On This Date", "Stores With Duplicate POS Rows",
            "Share Of Stores Affected", "Total Duplicate POS Rows Excluded", "Flag"]
    if bucket_summary is None or bucket_summary.empty or "Duplicate POS Rows Excluded" not in bucket_summary.columns:
        return pd.DataFrame(columns=cols)

    bs = bucket_summary.copy()
    rows = []
    for date, grp in bs.groupby("Date"):
        total_stores = grp["Store Code"].nunique()
        if total_stores == 0:
            continue
        affected = grp[grp["Duplicate POS Rows Excluded"].fillna(0) > 0]
        n_affected = affected["Store Code"].nunique()
        share = n_affected / total_stores
        if n_affected >= min_stores or share >= min_share:
            rows.append({
                "Date": date, "Stores On This Date": total_stores,
                "Stores With Duplicate POS Rows": n_affected,
                "Share Of Stores Affected": round(share, 3),
                "Total Duplicate POS Rows Excluded": int(affected["Duplicate POS Rows Excluded"].sum()),
                "Flag": "POSSIBLE SYSTEM-WIDE DUPLICATE UPLOAD FOR THIS DATE",
            })

    out = pd.DataFrame(rows, columns=cols)
    if not out.empty:
        out = out.sort_values("Stores With Duplicate POS Rows", ascending=False).reset_index(drop=True)
    return out


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
                                   exclude_duplicate_pos=True, exclude_duplicate_gl=True,
                                   max_bucket_tolerance=25.00,
                                   run_id=None, run_signature=None, pos_file_count=None,
                                   gl_file_count=None, run_timestamp=None,
                                   provider_mapping_db_path=None):
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
        exceptions -- BUT is capped at `max_bucket_tolerance` (default
        SAR 25.00). Without a ceiling, a bucket with thousands of line
        items could accept a real difference of thousands of SAR as
        "GL MATCHED"; a hard ceiling caught here is a control decision,
        not something that should scale away silently.
      - GL side sums Signed Amount, not Absolute Amount, so reversal/
        correction pairs net out correctly.

    After bucketing:
      - Cross-store swap detection flags mirror-pair buckets.
      - Every exception gets a rule-based "Likely Cause".
      - Exceptions are sorted by ABS(Difference) descending (variance
        ranking) so the largest financial risk surfaces first.

    IMPORTANT on counts: "GL Matched"/"GL Amount Exceptions"/etc. in the
    returned `summary` are counted at the Store+Date BUCKET level (one
    Store+Date bucket = one count), not at the POS-transaction-row level.
    A bucket with 350 POS rows that matches counts as 1 match, not 350 --
    counting POS rows here was a real bug in the prior pass and produced a
    misleading dashboard. `detail` (POS-row grain, one row per POS
    transaction) is still provided for drill-down, with its bucket-level
    columns explicitly labeled "Bucket ..." so they read as a repeated
    reference figure, not a per-transaction match.

    V41 item 2: `run_id`/`run_signature`/`pos_file_count`/`gl_file_count`/
    `run_timestamp` are optional metadata about THIS specific call, stored
    verbatim in the returned `summary` (as "Run ID"/"Run Signature"/
    "POS Files"/"GL Files"/"Run Timestamp"). These exist so a caller (the
    page) can freeze "what was actually reconciled" at RUN time and always
    display those frozen figures next to this result, instead of
    recomputing "Files Loaded" from whatever is CURRENTLY in the uploader
    widgets -- which can silently drift from the stored result if the user
    changes an upload after running. All five default to None/omitted if
    the caller doesn't pass them, so this is fully backward compatible.

    V42 item 6: `provider_mapping_db_path` lets a caller point at a
    non-default provider_gl_mapping.py database (mainly for tests); the
    running app never needs to pass it. Provider -> GL account resolution
    below now checks the Admin-maintained override table first via
    provider_gl_mapping.expected_accounts_for_provider(), falling back to
    core._gl_expected_account_for_tender() exactly as before when no
    override exists -- a provider that already resolved correctly resolves
    identically after this change.
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
    merged["bucket_tolerance"] = (tolerance * merged[["pos_count", "gl_count"]].max(axis=1).clip(lower=1)).clip(upper=max_bucket_tolerance)

    # -----------------------------------------------------------------
    # V40 item 1: per-Store+Date GL provider coverage split. A GL clearing
    # account is only "covered" for THIS bucket if a POS provider mapping
    # to it was actually uploaded for this exact Store+Date (not "ever
    # uploaded anywhere for this store", which is all
    # detect_incomplete_pos_provider_coverage() checks). GL activity in an
    # uncovered account should not be allowed to inflate GL AMOUNT
    # EXCEPTION -- if removing it brings POS Total and the remaining
    # (covered) GL Total within tolerance, that's an upload-completeness
    # gap, not a real accounting break.
    # -----------------------------------------------------------------
    # V41 item 5: track, per bucket, any POS provider that WAS present but
    # that core._gl_expected_account_for_tender() couldn't map to a GL
    # account at all -- distinct from a provider simply never being
    # uploaded. A bucket with uncovered GL and an unmapped provider present
    # gets PROVIDER MAPPING REQUIRED instead of UPLOAD INCOMPLETE, so
    # Finance isn't sent looking for a missing file when the real issue is
    # a master-data mapping gap.
    # V42 item 6: load the Admin-maintained provider->GL override table ONCE
    # per call (not once per bucket/row) and pass it through every
    # resolution below -- expected_accounts_for_provider() checks this cache
    # first, falling back to core._gl_expected_account_for_tender() exactly
    # as before when no override exists for that (provider, store) pair.
    _mapping_override_cache = provider_gl_mapping.load_override_map(provider_mapping_db_path)

    provider_by_bucket = (pos_all[pos_all["provider"] != ""]
                           .groupby(["store_code", "bucket_gl_date"])["provider"]
                           .apply(lambda s: set(s)))
    covered_accounts_by_bucket = {}
    unmapped_provider_by_bucket = {}
    for key, providers in provider_by_bucket.items():
        accts = set()
        unmapped = set()
        for p in providers:
            try:
                mapped, _ = provider_gl_mapping.expected_accounts_for_provider(
                    p, key[0], core_fn=core._gl_expected_account_for_tender,
                    _override_cache=_mapping_override_cache,
                )
            except Exception:
                mapped = set()
            if mapped:
                accts |= mapped
            else:
                unmapped.add(p)
        covered_accounts_by_bucket[key] = accts
        unmapped_provider_by_bucket[key] = unmapped

    if not gl_sum_src.empty:
        gl_by_account = (gl_sum_src.groupby(["store_code", "gl_date_n", "main_account"])["gl_signed_amount"]
                          .sum().reset_index().rename(columns={"gl_date_n": "bucket_gl_date"}))
        gl_by_account["covered"] = gl_by_account.apply(
            lambda r: r["main_account"] in covered_accounts_by_bucket.get((r["store_code"], r["bucket_gl_date"]), set()),
            axis=1,
        )
        gl_covered = (gl_by_account[gl_by_account["covered"]]
                      .groupby(["store_code", "bucket_gl_date"])["gl_signed_amount"].sum())
        gl_uncovered = (gl_by_account[~gl_by_account["covered"]]
                        .groupby(["store_code", "bucket_gl_date"])["gl_signed_amount"].sum())
        gl_uncovered_accts = (gl_by_account[~gl_by_account["covered"]]
                              .groupby(["store_code", "bucket_gl_date"])["main_account"]
                              .apply(lambda s: sorted(set(s))))
    else:
        gl_covered = pd.Series(dtype=float)
        gl_uncovered = pd.Series(dtype=float)
        gl_uncovered_accts = pd.Series(dtype=object)

    # V41 item 5 (correctness fix): covered_diff must compare GL Total
    # (Covered By POS) against the POS total restricted to MAPPABLE
    # providers only -- not the bucket's full pos_total. An unmapped
    # provider's own POS amount can't be attributed to any covered account,
    # so including it in the "covered" comparison would make covered_diff
    # spuriously large by exactly that amount and PROVIDER MAPPING REQUIRED
    # would almost never actually fire. Cache mappability per (provider,
    # store) since core._gl_expected_account_for_tender() doesn't depend on
    # date.
    _mappable_cache = {}
    def _provider_mappable(provider, store):
        key = (provider, store)
        if key not in _mappable_cache:
            try:
                accts, _ = provider_gl_mapping.expected_accounts_for_provider(
                    provider, store, core_fn=core._gl_expected_account_for_tender,
                    _override_cache=_mapping_override_cache,
                )
                _mappable_cache[key] = bool(accts)
            except Exception:
                _mappable_cache[key] = False
        return _mappable_cache[key]

    if not pos_sum_src.empty:
        pms = pos_sum_src.copy()
        # A blank provider contributes nothing to covered_accounts_by_bucket
        # either (see provider_by_bucket above, filtered to provider != "");
        # treat it as "mappable" here too so it doesn't spuriously trigger
        # PROVIDER MAPPING REQUIRED -- it's simply unattributed, not an
        # unrecognized provider value. V42 item 5: that choice stays
        # unchanged here (avoids a false PROVIDER MAPPING REQUIRED), but a
        # blank provider's rows are no longer folded silently into "mappable"
        # with no visibility -- see pos_unattributed_sum below, which tracks
        # them as their own explicit per-bucket figure.
        pms["_mappable"] = pms.apply(
            lambda r: True if not r["provider"] else _provider_mappable(r["provider"], r["store_code"]), axis=1
        )
        pos_mapped_sum = (pms[pms["_mappable"]]
                          .groupby(["store_code", "bucket_gl_date"])["pos_amount"].sum())
        # V42 item 5: blank-provider POS activity, exposed as its own
        # visible count/amount per bucket rather than being invisible inside
        # "mappable". A bucket can be UPLOAD INCOMPLETE / GL MATCHED / etc.
        # while still carrying meaningful blank-provider POS rows that
        # nobody attributed to a specific provider -- Finance should be able
        # to see that volume even when it isn't currently causing a status
        # change.
        blank_src = pos_sum_src[pos_sum_src["provider"] == ""]
        if not blank_src.empty:
            pos_unattributed_rows = blank_src.groupby(["store_code", "bucket_gl_date"])["pos_amount"].size()
            pos_unattributed_sum = blank_src.groupby(["store_code", "bucket_gl_date"])["pos_amount"].sum()
        else:
            pos_unattributed_rows = pd.Series(dtype=int)
            pos_unattributed_sum = pd.Series(dtype=float)
    else:
        pos_mapped_sum = pd.Series(dtype=float)
        pos_unattributed_rows = pd.Series(dtype=int)
        pos_unattributed_sum = pd.Series(dtype=float)

    _bkt_key = list(zip(merged["store_code"], merged["bucket_gl_date"]))
    merged["gl_total_covered"] = [float(gl_covered.get(k, 0.0)) for k in _bkt_key]
    merged["gl_total_uncovered"] = [float(gl_uncovered.get(k, 0.0)) for k in _bkt_key]
    merged["gl_uncovered_accounts"] = [gl_uncovered_accts.get(k, []) for k in _bkt_key]
    merged["unmapped_providers"] = [sorted(unmapped_provider_by_bucket.get(k, set())) for k in _bkt_key]
    merged["pos_total_mapped"] = [float(pos_mapped_sum.get(k, 0.0)) for k in _bkt_key]
    merged["covered_diff"] = merged["pos_total_mapped"] - merged["gl_total_covered"]
    # V42 item 5: blank-provider POS activity, per bucket -- visible count
    # and amount, separate from (not folded into) the mappable-POS-total
    # figure above.
    merged["pos_unattributed_rows"] = [int(pos_unattributed_rows.get(k, 0)) for k in _bkt_key]
    merged["pos_unattributed_amount"] = [float(pos_unattributed_sum.get(k, 0.0)) for k in _bkt_key]

    def _status(r):
        if r["_merge"] == "left_only" or r["gl_count"] == 0:
            return "GL NOT POSTED"
        if r["_merge"] == "right_only" or r["pos_count"] == 0:
            return "UNMATCHED GL"
        if abs(r["bucket_diff"]) <= r["bucket_tolerance"]:
            return "GL MATCHED"
        if abs(r["gl_total_uncovered"]) > r["bucket_tolerance"] and abs(r["covered_diff"]) <= r["bucket_tolerance"]:
            return "PROVIDER MAPPING REQUIRED" if r["unmapped_providers"] else "UPLOAD INCOMPLETE"
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
        if r["bucket_status"] == "UPLOAD INCOMPLETE":
            accts = ", ".join(r["gl_uncovered_accounts"]) if r["gl_uncovered_accounts"] else "one or more GL clearing accounts"
            reason = (f"SAR {r['gl_total_uncovered']:,.2f} of this bucket's D365 GL activity is in {accts}, "
                      f"which has no matching POS/provider file uploaded for this exact Store+Date. Once that "
                      f"uncovered GL activity is set aside, POS Total matches the remaining GL Total within "
                      f"tolerance -- this looks like a missing POS provider upload for this date, not a real "
                      f"accounting break. Check for a missing {accts} POS/provider file for this date.")
            # V42 item 5: a bucket can look UPLOAD INCOMPLETE while ALSO
            # carrying meaningful blank-provider POS activity -- worth
            # flagging, since that POS activity isn't explained by "missing
            # provider file" either; it was uploaded but never attributed.
            if r.get("pos_unattributed_amount", 0.0) and abs(r["pos_unattributed_amount"]) > r["bucket_tolerance"]:
                reason += (f" Separately, SAR {r['pos_unattributed_amount']:,.2f} across "
                           f"{int(r['pos_unattributed_rows'])} POS row(s) in this bucket had a blank Provider "
                           f"value and could not be attributed to a specific clearing account.")
            return reason
        if r["bucket_status"] == "PROVIDER MAPPING REQUIRED":
            accts = ", ".join(r["gl_uncovered_accounts"]) if r["gl_uncovered_accounts"] else "one or more GL clearing accounts"
            provs = ", ".join(r["unmapped_providers"]) if r["unmapped_providers"] else "an unrecognized provider"
            # V42 item 6: this is now resolvable via the Admin "Provider ->
            # GL Mapping" screen (no code deployment needed) -- mentioned
            # first since it's the fast path; core.py remains the fallback
            # for anyone updating the built-in table directly.
            return (f"SAR {r['gl_total_uncovered']:,.2f} of this bucket's D365 GL activity is in {accts} with "
                    f"no covering POS provider evidence for this Store+Date -- but a POS/provider file WAS "
                    f"uploaded here, with a provider value ({provs}) this app doesn't know how to map to a GL "
                    f"clearing account. This may not be a missing file at all: add a mapping for {provs} on the "
                    f"Admin \"Provider -> GL Mapping\" screen (Validate step), or in "
                    f"core._gl_expected_account_for_tender(), before assuming the upload is incomplete.")
        base = _classify_exception(r, swap_map)
        if abs(r.get("gl_total_uncovered", 0.0)) > r["bucket_tolerance"]:
            accts = ", ".join(r["gl_uncovered_accounts"]) if r["gl_uncovered_accounts"] else "one or more accounts"
            base += (f" Note: SAR {r['gl_total_uncovered']:,.2f} of this bucket's GL activity is in {accts}, "
                     f"which has no matching POS/provider file for this exact date -- part of this variance "
                     f"may be an upload-coverage gap on top of a real difference, not solely an accounting "
                     f"break.")
        # V42 item 5: surface blank-provider POS activity as a note when it's
        # material, so an exception bucket that also carries unattributed POS
        # rows doesn't look like a clean covered-account residual when part
        # of its POS side was never traced to a specific provider.
        if r.get("pos_unattributed_amount", 0.0) and abs(r["pos_unattributed_amount"]) > r["bucket_tolerance"]:
            base += (f" Note: SAR {r['pos_unattributed_amount']:,.2f} across {int(r['pos_unattributed_rows'])} "
                     f"POS row(s) in this bucket had a blank Provider value and could not be attributed to a "
                     f"specific clearing account.")
        return base
    merged["bucket_reason"] = merged.apply(_reason, axis=1)
    merged["store_swap_with"] = merged.apply(lambda r: swap_map.get((r["store_code"], r["bucket_gl_date"]), ""), axis=1)

    # Materiality tag (PASS 7) -- only meaningful for GL AMOUNT EXCEPTION
    # buckets; everything else is blank. When the reason fell through to the
    # generic "needs obvious cause" fallback, prefix it so the single
    # biggest dollar risk in a run reads as urgent in the reason text itself,
    # not only in a separate column someone has to notice. This is the FULL
    # variance (pos_total vs gl_total, the whole bucket) -- V41 item 7 adds a
    # second tag below for the narrower accounting-only residual.
    merged["severity"] = merged.apply(
        lambda r: _severity(r["pos_total"], r["gl_total"], r["bucket_diff"])
        if r["bucket_status"] == "GL AMOUNT EXCEPTION" else "", axis=1
    )
    # V41 item 7: a bucket's FULL variance can look EXTREME purely because
    # most of it is uncovered (missing-provider) GL activity, even though
    # the actual covered-account accounting residual (pos_total vs
    # gl_total_covered, i.e. covered_diff) is small -- e.g. SAR 100,000 full
    # difference where SAR 90,000 is uncovered provider activity and only
    # SAR 10,000 is unexplained after that's set aside. Full Variance
    # Severity stays as the headline materiality tag (unchanged sort
    # behavior); Accounting Residual Severity narrows the same scale to
    # covered_diff alone, so a bucket that only LOOKS extreme because of an
    # upload gap doesn't read the same as one whose real accounting
    # difference is actually that large.
    merged["accounting_residual_severity"] = merged.apply(
        lambda r: _severity(r["pos_total"], r["gl_total_covered"], r["covered_diff"])
        if r["bucket_status"] == "GL AMOUNT EXCEPTION" else "", axis=1
    )
    merged.loc[
        (merged["severity"] == "EXTREME") & merged["bucket_reason"].str.startswith("Amount variance has no obvious cause"),
        "bucket_reason"
    ] = "EXTREME VARIANCE -- " + merged.loc[
        (merged["severity"] == "EXTREME") & merged["bucket_reason"].str.startswith("Amount variance has no obvious cause"),
        "bucket_reason"
    ]

    bkey = merged.set_index(["store_code", "bucket_gl_date"])

    rows = []
    for _, p in pos_all.iterrows():
        key = (p["store_code"], p["bucket_gl_date"])
        b = bkey.loc[key]
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
            "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
            "GL Row": "", "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": key[1],
            # NOTE: these three columns are the BUCKET's totals, repeated on
            # every POS row that falls in the bucket for reference/drill-down
            # -- they do NOT mean this individual POS row matched this
            # amount. See "Match Level".
            "Match Level": "STORE + DATE (BUCKET SUM)",
            "Bucket POS Total": float(b["pos_total"]), "Bucket GL Total": float(b["gl_total"]),
            "Bucket Difference": float(b["bucket_diff"]),
            "Status": b["bucket_status"], "Match Rule": "Store + Date (Bucket Sum)",
            "Reason": b["bucket_reason"], "GL Source File": "",
            "Bucket POS Rows": int(b["pos_count"]), "Bucket GL Rows": int(b["gl_count"]),
            "Bucket Tolerance": float(b["bucket_tolerance"]),
            "Is Duplicate POS Row": bool(p["is_duplicate_pos"]),
            "Store Swap Suspected With": b["store_swap_with"],
            "Severity": b["severity"],
        })
    for _, p in pos_bad.iterrows():
        reason = "POS Amount missing/non-numeric." if pd.isna(p["pos_amount"]) else "Store Code or Date missing; cannot allocate to a Store+Date GL bucket."
        status = "POS DATA INCOMPLETE" if pd.isna(p["pos_amount"]) else "IDENTIFIER MISMATCH"
        rows.append({
            "POS Row": p["source_row"], "Merchant ID": p["merchant_id"], "Store Code": p["store_code"],
            "Provider": p["provider"], "POS Reference": p["reference"], "POS Date": p["pos_date"], "POS Amount": p["pos_amount"],
            "GL Row": "", "GL Main Account": "", "GL Voucher": "", "GL Journal": "",
            "GL Date": pd.NaT, "Match Level": "", "Bucket POS Total": float("nan"),
            "Bucket GL Total": float("nan"), "Bucket Difference": float("nan"),
            "Status": status, "Match Rule": "", "Reason": reason, "GL Source File": "",
            "Bucket POS Rows": 0, "Bucket GL Rows": 0, "Bucket Tolerance": float("nan"),
            "Is Duplicate POS Row": bool(p.get("is_duplicate_pos", False)), "Store Swap Suspected With": "",
            "Severity": "",
        })

    d = pd.DataFrame(rows)
    # Matched/exception status here is at POS-row grain (useful for
    # drill-down and the Excel "GL Matched"/"Exceptions" tabs), but the
    # summary counts below are bucket-level -- see the docstring note on
    # counts.
    matched = d[d.Status == "GL MATCHED"].copy()
    exc = d[d.Status != "GL MATCHED"].copy()
    exc["_abs_diff"] = exc["Bucket Difference"].abs()
    exc = exc.sort_values("_abs_diff", ascending=False, na_position="last").drop(columns=["_abs_diff"])

    unmatched_gl_keys = set(merged[merged.bucket_status == "UNMATCHED GL"][["store_code", "bucket_gl_date"]].apply(tuple, axis=1))
    if unmatched_gl_keys:
        gl_all["_key"] = list(zip(gl_all["store_code"], gl_all["gl_date_n"]))
        unmatched_gl = gl_all[gl_all["_key"].isin(unmatched_gl_keys)].drop(columns=["_key"]).copy()
    else:
        unmatched_gl = gl_all.iloc[0:0].copy()

    merged["gl_uncovered_accounts_str"] = merged["gl_uncovered_accounts"].apply(lambda a: ", ".join(a) if a else "")
    merged["unmapped_providers_str"] = merged["unmapped_providers"].apply(lambda a: ", ".join(a) if a else "")
    bucket_summary = merged.rename(columns={
        "store_code": "Store Code", "bucket_gl_date": "Date",
        "pos_count": "POS Rows", "pos_total": "POS Total",
        "gl_count": "GL Rows", "gl_total": "GL Total",
        "bucket_diff": "Difference", "bucket_tolerance": "Bucket Tolerance",
        "bucket_status": "Status", "bucket_reason": "Reason",
        "pos_duplicate_rows": "Duplicate POS Rows Excluded", "gl_duplicate_rows": "Duplicate GL Rows Excluded",
        "store_swap_with": "Store Swap Suspected With",
        "severity": "Full Variance Severity", "accounting_residual_severity": "Accounting Residual Severity",
        "gl_total_covered": "GL Total (Covered By POS)", "gl_total_uncovered": "GL Total (No POS Provider This Date)",
        "gl_uncovered_accounts_str": "Uncovered GL Accounts", "unmapped_providers_str": "Unmapped Providers",
        # V42 item 5: blank-provider POS activity as its own visible columns
        # -- not a new bucket status, just a count/amount Finance can see
        # per bucket regardless of what Status ended up being.
        "pos_unattributed_rows": "POS Rows With Blank Provider",
        "pos_unattributed_amount": "POS Amount With Blank Provider (SAR)",
    })[["Store Code", "Date", "POS Rows", "POS Total", "GL Rows", "GL Total", "Difference",
        "Bucket Tolerance", "Duplicate POS Rows Excluded", "Duplicate GL Rows Excluded",
        "GL Total (Covered By POS)", "GL Total (No POS Provider This Date)", "Uncovered GL Accounts",
        "Unmapped Providers", "POS Rows With Blank Provider", "POS Amount With Blank Provider (SAR)",
        "Store Swap Suspected With", "Full Variance Severity",
        "Accounting Residual Severity", "Status", "Reason"]].copy()
    # Sort: Status groups first, then EXTREME/HIGH/NORMAL severity within a
    # group outranks plain dollar size -- a small-total store with an
    # extreme RATIO shouldn't hide below a merely-large-absolute-diff
    # ordinary exception (PASS 7).
    _sev_rank = {"EXTREME": 0, "HIGH": 1, "NORMAL": 2, "": 3}
    bucket_summary["_sev_rank"] = bucket_summary["Full Variance Severity"].map(_sev_rank).fillna(3)
    bucket_summary["_abs_diff"] = bucket_summary["Difference"].abs()
    bucket_summary = bucket_summary.sort_values(
        ["Status", "_sev_rank", "_abs_diff"], ascending=[True, True, False]
    ).drop(columns=["_sev_rank", "_abs_diff"])

    # V40 item 8: rank ALL non-matched bucket statuses together by absolute
    # dollar difference, not GL AMOUNT EXCEPTION only -- a large-dollar
    # UNMATCHED GL / GL NOT POSTED / UPLOAD INCOMPLETE bucket should not
    # disappear from the executive Top 20 just because its status isn't
    # GL AMOUNT EXCEPTION. Status/Reason are preserved so the kind of
    # problem stays visible in the ranked list.
    top_exceptions = (bucket_summary[bucket_summary["Status"] != "GL MATCHED"]
                       .assign(_ad=lambda x: x["Difference"].abs())
                       .sort_values("_ad", ascending=False).drop(columns=["_ad"]).head(20))

    total_pos_dup = int(pos_all["is_duplicate_pos_extra"].sum())
    total_gl_dup = int(gl_all["is_duplicate_gl_extra"].sum())

    # BUCKET-level counts (one Store+Date bucket = one count) -- fixed from
    # the prior pass, which counted POS-transaction rows here instead and
    # could show e.g. "Matched = 350" for a single matched bucket that
    # happened to contain 350 POS rows. "GL Matched"/"GL Amount Exceptions"
    # are kept under these names for dashboard/Excel compatibility, but now
    # both count buckets, matching "Store-Date Buckets" as the denominator.
    n_matched_buckets = int((merged.bucket_status == "GL MATCHED").sum())
    n_exception_buckets = int((merged.bucket_status == "GL AMOUNT EXCEPTION").sum())
    n_not_posted_buckets = int((merged.bucket_status == "GL NOT POSTED").sum())
    n_unmatched_gl_buckets = int((merged.bucket_status == "UNMATCHED GL").sum())
    n_upload_incomplete_buckets = int((merged.bucket_status == "UPLOAD INCOMPLETE").sum())
    n_provider_mapping_buckets = int((merged.bucket_status == "PROVIDER MAPPING REQUIRED").sum())
    n_extreme_buckets = int((merged["severity"] == "EXTREME").sum())
    n_identifier_mismatch = int((d.Status == "IDENTIFIER MISMATCH").sum())
    n_pos_incomplete = int((d.Status == "POS DATA INCOMPLETE").sum())

    # V40 item 5: Overall Status derived from bucket statuses directly, not
    # from the POS-row-grain `exc` dataframe -- a GL-only UNMATCHED GL
    # bucket produces zero POS detail rows, so the old `exc.empty` check
    # could read RECONCILED with real unmatched GL activity still
    # outstanding.
    all_buckets_matched = bool((merged["bucket_status"] == "GL MATCHED").all()) if len(merged) else True
    no_invalid_pos_rows = (n_identifier_mismatch == 0 and n_pos_incomplete == 0)
    overall_status = "RECONCILED" if (all_buckets_matched and no_invalid_pos_rows) else "EXCEPTIONS REQUIRE REVIEW"

    summary = pd.DataFrame([{
        "POS Transaction Rows": len(pos), "GL Line Rows": len(gl),
        "Store-Date Buckets": len(merged),
        "GL Matched": n_matched_buckets,
        "Matched Buckets": n_matched_buckets,
        "Exception Buckets": len(merged) - n_matched_buckets,
        "GL Amount Exceptions": n_exception_buckets,
        "Upload Incomplete Buckets": n_upload_incomplete_buckets,
        "Provider Mapping Required Buckets": n_provider_mapping_buckets,
        "Extreme Variance Buckets": n_extreme_buckets,
        "GL Not Posted": n_not_posted_buckets,
        "Unmatched GL Buckets": n_unmatched_gl_buckets,
        "Identifier Mismatch": n_identifier_mismatch,
        "POS Data Incomplete": n_pos_incomplete,
        "Duplicate POS Rows Excluded": total_pos_dup,
        "Duplicate GL Rows Excluded": total_gl_dup,
        "Unmatched GL Rows": len(unmatched_gl),
        "POS Total (SAR)": float(pos_sum_src["pos_amount"].sum()) if not pos_sum_src.empty else 0.0,
        "GL Total (SAR)": float(gl_sum_src["gl_signed_amount"].sum()) if not gl_sum_src.empty else 0.0,
        # V41 item 6: signed sum kept (positive/negative uncovered activity
        # across buckets can offset each other and understate exposure), plus
        # an absolute-exposure figure -- the better risk KPI.
        "Uncovered GL Activity (SAR)": float(merged["gl_total_uncovered"].sum()),
        "Uncovered GL Absolute Exposure (SAR)": float(merged["gl_total_uncovered"].abs().sum()),
        # V42 item 5: total blank-provider POS activity across every bucket
        # -- a run-level KPI for how much POS volume is currently
        # unattributed to any provider, separate from (and additive to,
        # not a cause of) Uncovered GL Absolute Exposure above.
        "POS Amount With Blank Provider (SAR)": float(merged["pos_unattributed_amount"].sum()),
        "POS Rows With Blank Provider": int(merged["pos_unattributed_rows"].sum()),
        "Tolerance SAR": tolerance,
        "Max Bucket Tolerance SAR": max_bucket_tolerance,
        "Settlement Lag Days": settlement_lag_days,
        "Overall Status": overall_status,
        "Match Granularity": "Store + Date bucket (sum of amounts); amount decides match/exception, not the key. Counts below are per bucket, not per POS row.",
        # V41 item 2: run metadata frozen into the result itself -- see the
        # docstring note on run_id/run_signature/pos_file_count/
        # gl_file_count/run_timestamp above.
        "Run ID": run_id or "",
        "Run Signature": run_signature or "",
        "POS Files": pos_file_count if pos_file_count is not None else "",
        "GL Files": gl_file_count if gl_file_count is not None else "",
        "Run Timestamp": run_timestamp or "",
    }])
    summary["Net Difference (SAR)"] = summary["POS Total (SAR)"] - summary["GL Total (SAR)"]
    # POS Rows / GL Rows kept as aliases for backward compatibility with
    # anything still reading the old field names.
    summary["POS Rows"] = summary["POS Transaction Rows"]
    summary["GL Rows"] = summary["GL Line Rows"]

    chronic_stores = detect_chronic_exception_stores(bucket_summary)
    duplicate_dates = detect_duplicate_date_signature(bucket_summary)

    return {"detail": d, "matched": matched, "exceptions": exc, "unmatched_gl": unmatched_gl,
            "bucket_summary": bucket_summary, "top_exceptions": top_exceptions, "summary": summary,
            "chronic_stores": chronic_stores, "duplicate_dates": duplicate_dates}

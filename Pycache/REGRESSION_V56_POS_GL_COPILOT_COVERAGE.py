"""
REGRESSION_V56_POS_GL_COPILOT_COVERAGE.py

You asked the AI Copilot to also be able to answer about your real POS-to-GL
reconciliation batch (the SAR 224K card variance investigation). That report
(pages/35_POS_GL_Reconciliation.py) is a completely separate pipeline from
the classic Store-Tender-based `result` dict this Copilot otherwise reads --
its output lives under a different session-state key (v53_pos_gl) that the
Copilot was never given at all before this change.

This adds a new "pos_gl_reconciliation" intent/answer function that reads
that data directly (passed in as the new `pos_gl_data` parameter to
answer_question(), wired from pages/29_AI_Finance_Copilot.py), plus phrase
triggers checked BEFORE gl_control's bare "gl" fallback and gl_config's
phrases (several of the new phrases contain "gl"/"bucket" and would
otherwise be swallowed by those existing, more general intents).

Covers: the new intent resolves for its own phrases (overall status, top
exceptions, chronic stores, upload-incomplete/coverage-gap rows), store-
scoped answers narrow correctly to just that store's buckets, it degrades
gracefully (never crashes) with no pos_gl_data, and every pre-existing
gl_control/gl_config phrase (including the exact one V53 fixed) is either
unaffected or -- where V56 gives it a genuinely better, more specific
destination -- correctly upgraded (see the V53 test file's own updated
comment for that one case).
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_v56_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

# Bucket-mode fixture shaped exactly like reconcile_pos_to_gl_by_bucket()'s
# real output columns (see logic/pos_gl_reconciliation.py).
bucket_summary = pd.DataFrame([
    {"Store Code":"637","Date":pd.Timestamp("2026-09-04"),"POS Total":29600.0,"GL Total":29599.85,"Status":"GL MATCHED"},
    {"Store Code":"637","Date":pd.Timestamp("2026-09-06"),"POS Total":0.0,"GL Total":36500.0,"Status":"UNMATCHED GL"},
    {"Store Code":"652","Date":pd.Timestamp("2026-09-03"),"POS Total":95757.0,"GL Total":2050.0,"Status":"GL AMOUNT EXCEPTION"},
    {"Store Code":"652","Date":pd.Timestamp("2026-09-04"),"POS Total":0.0,"GL Total":95557.0,"Status":"UNMATCHED GL"},
    {"Store Code":"601","Date":pd.Timestamp("2026-09-05"),"POS Total":12000.0,"GL Total":12000.0,"Status":"GL MATCHED"},
])
top_exceptions = bucket_summary[bucket_summary["Status"]!="GL MATCHED"].copy()
chronic_stores = pd.DataFrame([{"Store Code":"652","Failure Rate":1.0,"Failure Pattern":"CHRONIC (MIXED CAUSES)"}])
duplicate_dates = pd.DataFrame(columns=["Date","Stores On This Date","Stores With Duplicate POS Rows"])
exceptions = pd.DataFrame([
    {"Store Code":"614","Status":"UPLOAD INCOMPLETE","GL Total":18926.90},
    {"Store Code":"606","Status":"UPLOAD INCOMPLETE","GL Total":17194.06},
])

pos_gl_data = {
    "summary": pd.DataFrame([{
        "Overall Status":"EXCEPTIONS REQUIRE REVIEW",
        "POS Total (SAR)":1190437.09,"GL Total (SAR)":1762655.02,"Net Difference (SAR)":-572217.93,
        "Store-Date Buckets":len(bucket_summary),
        "Matched Buckets":int((bucket_summary["Status"]=="GL MATCHED").sum()),
        "Exception Buckets":int((bucket_summary["Status"]!="GL MATCHED").sum()),
    }]),
    "bucket_summary": bucket_summary,
    "top_exceptions": top_exceptions,
    "chronic_stores": chronic_stores,
    "duplicate_dates": duplicate_dates,
    "exceptions": exceptions,
}

result = {"tender":pd.DataFrame(),"matched":pd.DataFrame(),"unmatched_sales":pd.DataFrame(),"unmatched_pos":pd.DataFrame()}

# --- basic intent + overall status ---------------------------------------
r = ai.answer_question("pos to gl reconciliation status", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="pos_gl_reconciliation", f"got {r['intent']}")
_assert("EXCEPTIONS REQUIRE REVIEW" in r["text"], f"text: {r['text']}")
_assert(str(len(bucket_summary)) in r["text"], f"bucket count in text: {r['text']}")

# --- top exceptions ---------------------------------------------------------
r = ai.answer_question("top exceptions", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="pos_gl_reconciliation", f"got {r['intent']}")
_assert(not r["table"].empty, "top exceptions table not empty")

# --- chronic stores -----------------------------------------------------
r = ai.answer_question("chronic stores", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="pos_gl_reconciliation", f"got {r['intent']}")
_assert("1" in r["text"], f"text: {r['text']}")

# --- upload incomplete / coverage gap -------------------------------------
r = ai.answer_question("upload incomplete buckets", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="pos_gl_reconciliation", f"got {r['intent']}")
_assert("2" in r["text"], f"text: {r['text']}")

# --- store-scoped narrows correctly ----------------------------------------
r = ai.answer_question("store 637 pos to gl", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="pos_gl_reconciliation", f"got {r['intent']}")
_assert("637" in r["text"] and "66,099.85" in r["text"], f"text: {r['text']}")
r = ai.answer_question("store 601 pos to gl reconciliation", result, pos_gl_data=pos_gl_data)
_assert("601" in r["text"] and "1 matched" in r["text"], f"clean store shows matched, not exceptions: {r['text']}")

# --- graceful degrade with no pos_gl_data ----------------------------------
r = ai.answer_question("pos to gl reconciliation", result, pos_gl_data=None)
_assert(r["intent"]=="pos_gl_reconciliation", f"got {r['intent']}")
_assert("unavailable" in r["text"].lower(), f"text: {r['text']}")
r = ai.answer_question("bucket summary", result)  # pos_gl_data omitted entirely
_assert("unavailable" in r["text"].lower(), f"text: {r['text']}")

# --- existing gl_control / gl_config completely unaffected ------------------
r = ai.answer_question("jv to gl", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="gl_control", f"'jv to gl' still gl_control, got {r['intent']}")
r = ai.answer_question("gl configuration", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="gl_config", f"'gl configuration' still gl_config, got {r['intent']}")
r = ai.answer_question("gl status", result, pos_gl_data=pos_gl_data)
_assert(r["intent"]=="gl_control", f"'gl status' still gl_control, got {r['intent']}")

print("\nALL V56 POS-GL COPILOT TESTS PASS")

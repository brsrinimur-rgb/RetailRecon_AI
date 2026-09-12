"""
REGRESSION_V53_GL_CORRECTIONS_MAPPING_DETAILS_MISROUTE.py

Real reported bug (2026-09-12): "POS GL Recoolaiton details" (a typo'd "POS
GL Reconciliation details") returned a completely unrelated global sales
summary instead of any GL-control information. Same bug class as V51's
"bank details" and V52's "jv details" fixes: a bare topic mention with no
exact phrase already recognized fell through to the generic details/sales
catch-all instead of the topic-specific report.

Auditing every other intent for the same gap (any intent whose only
triggers are multi-word exact phrases, with no bare single-keyword
fallback) turned up two more likely to hit the same wall in real use:
"correction details" and "mapping details". Fixed all three the same way,
following the exact pattern already proven safe by the bank/jv fixes.

Covers:
  1. The exact reported repro for GL.
  2. "correction details" / "mapping details" resolve to their own intents.
  3. All pre-existing exact phrases for corrections/mapping/gl_control still
     work unchanged.
  4. gl_control's own "jv to gl"/"source to gl" phrases, and jv's own bare
     "jv" fallback (added in V52), remain correctly cross-exclusive --
     proving the two fixes still cooperate correctly.
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_v53_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

tender = pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","D365 Payment":"MADA","D365 Amount":100.0},
])
result = {"tender":tender,"matched":pd.DataFrame(),"unmatched_sales":pd.DataFrame(),"unmatched_pos":pd.DataFrame()}

# --- 1. exact reported repro (with the real typo) ------------------------
r1 = ai.answer_question("you can details tamara all stores", result, prior_context=None)
r2 = ai.answer_question("POS GL Recoolaiton details", result, prior_context=r1["context"])
_assert(r2["intent"]=="gl_control", f"'POS GL Recoolaiton details' now resolves to gl_control, got {r2['intent']}")
_assert(r2["text"]!=r1["text"], "the answer must actually change, not silently repeat the prior turn verbatim")

r3 = ai.answer_question("pos gl reconciliation details", result, prior_context=None)
_assert(r3["intent"]=="gl_control", f"correctly-spelled version also resolves to gl_control, got {r3['intent']}")

# --- 2. the other two audited gaps ---------------------------------------
intent,_ = ai.interpret_query("correction details", result, None)
_assert(intent=="corrections", f"'correction details' resolves to corrections, got {intent}")
intent,_ = ai.interpret_query("mapping details", result, None)
_assert(intent=="mapping", f"'mapping details' resolves to mapping, got {intent}")

# --- 3. pre-existing exact phrases unaffected ----------------------------
for q,expect in [
    ("gl status","gl_control"),("d365 gl","gl_control"),("gl exceptions","gl_control"),
    ("pending correction","corrections"),("corrections pending","corrections"),
    ("merchant mapping","mapping"),("terminal mapping","mapping"),("mapping required","mapping"),
]:
    intent,_ = ai.interpret_query(q, result, None)
    _assert(intent==expect, f"{q!r} still resolves to {expect}, got {intent}")

# --- 4. jv/gl cross-exclusivity (from V52) still correct -----------------
intent,_ = ai.interpret_query("jv to gl", result, None)
_assert(intent=="gl_control", f"'jv to gl' still resolves to gl_control, got {intent}")
intent,_ = ai.interpret_query("source to gl", result, None)
_assert(intent=="gl_control", f"'source to gl' still resolves to gl_control, got {intent}")
intent,_ = ai.interpret_query("jv status", result, None)
_assert(intent=="jv", f"'jv status' still resolves to jv, got {intent}")
intent,_ = ai.interpret_query("jv details", result, None)
_assert(intent=="jv", f"'jv details' still resolves to jv, got {intent}")

print("\nREGRESSION V53 GL/CORRECTIONS/MAPPING DETAILS MISROUTE PASS")

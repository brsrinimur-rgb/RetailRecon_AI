"""
REGRESSION_V51_BANK_DETAILS_MISROUTE.py

Real reported bug (2026-09-11): after asking about TAMARA sales across all
stores, the user typed "i need bank details" -- a clear, specific request
for bank/settlement information -- and got back the EXACT SAME TAMARA sales
summary answer as the previous turn, completely unchanged, as if the
question had never been read at all.

Root cause: "i need bank details" contains the bare substring "details",
which matched the Copilot's generic "show transactions/details" catch-all
BEFORE any bank-specific check ever got a chance to run, and because
neither the store, payment nor date scope changed either, the re-run
report came out byte-for-byte identical to the prior turn -- indistinguish-
able from the app simply ignoring the question.

Fix: a bare, otherwise-unmatched mention of "bank" (with no more specific
phrase already handled by unsettled/settlement_batch/settlement_intelligence
above it in the chain) now routes to the bank/settlement intelligence
report instead of falling through to the generic details catch-all.

Covers:
  1. The exact reported repro: "...tamara..." then "i need bank details"
     must change intent/answer, not silently repeat the prior turn.
  2. "bank details" as a fresh, first question (no prior turn) also
     resolves to settlement_intelligence.
  3. More specific, pre-existing bank phrases ("bank settled","bank
     missing","bank received batches") still resolve to their own,
     unaffected, more specific intents -- proving this fix only catches
     the previously-unhandled bare case.
  4. A completely unrelated "details" follow-up ("show details") that
     does NOT mention "bank" is unaffected and still uses the generic
     transactions/sales catch-all as before.
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_v51_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

tender = pd.DataFrame([
    {"Store Code":"601","Store Name":"Aigner Tahlia Mall","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","D365 Payment":"MADA","D365 Amount":100.0},
    {"Store Code":"603","Store Name":"Aigner Red Sea Mall","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"603A","Auth Code":"B1","D365 Payment":"TAMARA","D365 Amount":300.0},
])
matched = pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","Payment Type":"MADA","Sales Amount":100.0,"Commission":1.0,"VAT":0.15,"Net Amount":98.85,"Bank Settled":True},
    {"Store Code":"603","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"603A","Auth Code":"B1","Payment Type":"TAMARA","Sales Amount":300.0,"Commission":3.0,"VAT":0.45,"Net Amount":296.55,"Bank Settled":False},
])
result = {"tender":tender,"matched":matched,"unmatched_sales":pd.DataFrame(),"unmatched_pos":pd.DataFrame()}

# --- 1. exact reported repro -------------------------------------------
r1 = ai.answer_question("you can details tamara all stores", result, prior_context=None)
r2 = ai.answer_question("i need bank details", result, prior_context=r1["context"])
_assert(r2["intent"]=="settlement_intelligence", f"'i need bank details' now resolves to settlement_intelligence, got {r2['intent']}")
_assert(r2["text"]!=r1["text"], "the answer must actually change, not silently repeat the prior TAMARA sales summary verbatim")
_assert("bank" in r2["text"].lower() or "settl" in r2["text"].lower(), f"answer must actually be about bank/settlement, got: {r2['text']}")

# --- 2. fresh, first question -------------------------------------------
r3 = ai.answer_question("bank details", result, prior_context=None)
_assert(r3["intent"]=="settlement_intelligence", f"'bank details' as a first question resolves to settlement_intelligence, got {r3['intent']}")

# --- 3. more specific existing bank phrases stay unaffected -------------
intent,_ = ai.interpret_query("bank settled amount", result, None)
_assert(intent=="settlement_intelligence", f"'bank settled amount' unaffected, got {intent}")
intent,_ = ai.interpret_query("bank missing today", result, None)
_assert(intent=="unsettled", f"'bank missing today' still resolves to unsettled, got {intent}")
intent,_ = ai.interpret_query("bank received batches", result, None)
_assert(intent=="settlement_batch", f"'bank received batches' still resolves to settlement_batch, got {intent}")

# --- 4. unrelated "details" follow-up unaffected ------------------------
r4 = ai.answer_question("show details", result, prior_context=r1["context"])
_assert(r4["intent"] in {"transactions","sales"}, f"'show details' (no 'bank') still uses the generic catch-all, got {r4['intent']}")

print("\nREGRESSION V51 BANK DETAILS MISROUTE PASS")

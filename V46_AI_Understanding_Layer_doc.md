# V46 — Real AI Understanding for the AI Finance Copilot (Optional)

**Date:** 2026-09-11
**Files changed:** `ai_copilot.py` (also includes the earlier "601 sales" sticky-payment fix from earlier today, so this one file replaces your repo's copy cleanly either way), `requirements.txt`
**New file:** `logic/ai_llm_router.py`
**Scope:** understanding the question only. It does not compute, store, or state a single number itself.

## What you asked for

"I need like you — chat, ask anything, it gives the correct answer."

Worth being upfront about what the Copilot actually was, since it explains why this needed real work rather than one more patch: it was never a chat AI. Every previous fix I made to it (the CASH sticky-scope issue, the "601 sales" issue) was me editing a list of exact phrases and patterns it checks your question against — that's why it could only ever handle wording I'd specifically coded for.

## The approach — and why I built it this specific way

You confirmed you want the best, most professional version of this for a real business tool. For a reconciliation/accounting app, that isn't "let the AI write whatever answer it feels like" — a model can misread a question and confidently state a number that's slightly wrong, and there's no room for that in your financial records. So this is built the safer, industry-standard way:

**The AI's only job is to understand what you're asking. It never touches the actual numbers.**

Concretely: your question goes to Claude (Anthropic's AI) with a strict instruction — pick which one of the report types this app already knows how to build, and note which store/payment it's about. The AI hands back a small structured answer (not prose), and that gets fed into the exact same calculation code that's always powered this app (`_sales_answer`, `_cash_report`, `_risk_answer`, etc.) — the same functions, the same math, unchanged. The AI decides *which* report to run and *for what scope*; your existing, tested code still does 100% of the counting.

This means: far more natural phrasing works ("how much did store 601 bring in for the day" now correctly routes to a sales report, even though it contains none of the trigger words the old system needed), but every number you see is still produced exactly the way it always was.

## What you need to do to turn it on

1. Get an API key at **console.anthropic.com** (sign up, add a payment method — pricing is pay-as-you-go and this uses a small, cheap model since it's only classifying your question, not writing the answer).
2. Add it as **`ANTHROPIC_API_KEY`** — either as an environment variable on wherever this app runs, or (if you're on Streamlit Cloud) under your app's **Settings → Secrets** as:
   ```
   ANTHROPIC_API_KEY = "sk-ant-your-key-here"
   ```
3. Install the one new dependency: `anthropic` (already added to `requirements.txt` — if your host installs from that file automatically, nothing else to do).

That's it — no other setting to flip. The Copilot checks for the key itself every time it's asked a question.

## If you don't do this (or aren't ready yet)

**Nothing changes.** I tested this explicitly: with no key set, the app is byte-for-byte identical in behavior to before this update — same code path, same 12 regression suites passing. You can upload this file today and decide about the API key later with zero risk either way.

## What happens if something goes wrong once it's on

If the API call fails for any reason — no internet from your host, a typo'd key, Anthropic's service being briefly down, a slow response — that one question silently falls back to the original pattern-matching system instead of erroring out. You'd just get an answer via the "old" method for that one question rather than a crash. I tested this failure path directly (simulated a network error) and confirmed the app keeps answering normally.

## What did NOT change

- No calculation function was touched. `_sales_answer`, `_cash_report`, `_risk_answer`, and every other report-builder run exactly as before.
- The store/date/payment scope-persistence behavior from earlier fixes (V44, V45) is completely unaffected — I re-ran and passed all of those tests again.
- Nothing about JV creation, GL, settlement, or any other page in the app was touched.

## One thing I found and left alone (worth knowing)

While testing, I found a small pre-existing quirk in the *old* pattern-matching payment detector: a typo-tolerance feature meant to catch things like "mastercart" or "amx" can occasionally misfire on an unrelated common word (I hit one example: the word "came" was close enough to "amex" to trigger a false match). This isn't something I introduced — it's been there in `_find_payment()`'s fuzzy matching from earlier in the project — and it's a separate, narrow issue from what you asked me to fix today. I didn't touch it since it's out of scope here, but flagging it in case you want it looked at separately; it likely affects only a handful of specific words.

## Verification

- New test `REGRESSION_V46_LLM_ROUTER_INTEGRATION.py` (10 assertions, no API key required — the AI response is simulated): confirms the zero-config path is provably unchanged, a confident AI classification correctly bypasses the old pattern list for a phrasing it could never have handled, an "unsure" AI response correctly falls back to the pattern list, a simulated network failure degrades cleanly with no crash, a regex-found store is never dropped just because the AI didn't also report it, and — the most important one — the exact same scope produces byte-for-byte identical answer text whether the AI layer is involved in routing or not.
- All 11 previously-existing AI Copilot regression suites re-run and pass unchanged, including the two from earlier today (`REGRESSION_V45_COPILOT_PAYMENT_SCOPE_RESET`, and the full `REGRESSION_V13_COPILOT_STICKY_SCOPE`).
- `py_compile` clean on both files.
- Diff against your live repo is attached — additive throughout except the mechanical re-indentation needed to wrap the existing keyword classifier inside "only run this if the AI didn't confidently decide."

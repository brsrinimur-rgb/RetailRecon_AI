# V56 — AI Copilot Now Covers the Real POS-to-GL Reconciliation Batch

**Date:** 2026-09-13
**Files changed:** `ai_copilot.py`, `logic/ai_llm_router.py`, `pages/29_AI_Finance_Copilot.py`

## What you asked

After we found the SAR ~224K card variance in your real POS-to-GL batch (Store 637, the SO6- postings, the 633/615 pairing), you asked me to update the AI chat so it can answer this kind of question directly.

## What's new

The **POS → D365 GL Reconciliation** page (page 35 — your daily bulk POS-vs-GL-journal upload, not the classic Store Tender sales page) previously had **zero** Copilot coverage. Its result lives in a different part of the app's memory than everything else the Copilot reads, so this needed two things: a new question type in `ai_copilot.py`, and a small wiring change in the Copilot page itself to hand that data across.

You can now ask things like:

| Question | What it answers |
|---|---|
| "pos to gl reconciliation status" | Overall status, POS vs GL totals, net difference, matched vs exception bucket counts |
| "store 637 pos to gl" | The same, narrowed to just that store |
| "top exceptions" | The worst exceptions ranked by SAR exposure |
| "chronic stores" | Stores failing on nearly every date, not just one-off |
| "upload incomplete" / "coverage gap" | GL activity with no matching POS file — a missing-file problem, not an accounting error |
| "duplicate dates" | Dates that look like they were uploaded twice |

It always answers from the real numbers behind the page you already ran — it never estimates or invents a figure. Asking about it before you've run that page just says so plainly, instead of crashing or guessing.

## Verification

- New test `REGRESSION_V56_POS_GL_COPILOT_COVERAGE.py`: confirms the new question type resolves correctly, store-scoping narrows the answer correctly, it degrades gracefully with no data loaded, and every existing GL-related question is unaffected.
- One older test's expectation was updated on purpose: `REGRESSION_V53_GL_CORRECTIONS_MAPPING_DETAILS_MISROUTE.py` used to expect "pos gl reconciliation details" to fall back to the general GL report, because there was nothing more specific to send it to. Now that this exact report exists, that question correctly goes there instead — a genuine improvement, not a break (the comment in that file explains it).
- All 21 Copilot regression suites (10 original + V45–V56) re-run in a fresh isolated copy of the real repo — all pass.
- `py_compile` clean on all three changed files.

## How to upload

Replace three files in your repo (same paths):
- `ai_copilot.py` (repo root)
- `logic/ai_llm_router.py` (in the `logic` folder)
- `pages/29_AI_Finance_Copilot.py` (in the `pages` folder) — this one is new to this delivery; it's a small, one-line-of-substance change (passing the POS-to-GL data through to the Copilot), not a rewrite.

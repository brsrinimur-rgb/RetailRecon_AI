# RetailRecon AI — V34: Carry Forward of Unsettled Bank Settlement Items to Next Month

Requirement captured 2026-08-13, from user instruction. **Design only below — not built.** Read §5 for exactly why, before assuming this is a gap in effort rather than a deliberate stop.

## 1. What's being asked

Batches that are **not yet Bank Settled** at the point a new month's reconciliation is run — i.e. still `BANK REVIEW REQUIRED` or `BANK RECEIPT PENDING` from the prior month — should **carry forward into the next month's run** rather than being left behind as orphaned prior-period data. The intent: an unsettled July batch shouldn't disappear once August's `RUN RECONCILIATION` executes; it should still be visible and resolvable in August (and beyond, until the bank credit actually lands or it's otherwise resolved).

## 2. Important: this may already partially exist — needs confirming, not assuming

V28's Reconciliation Run History spec already lists **"Carry Forward"** as one of the named datasets saved per run inside `st.session_state.ct_result`, alongside Matched, Unmatched D365, Settlement Batches, etc. That means:

- Either a "Carry Forward" concept already exists in `core.py`/the reconciliation engine for some purpose (possibly unmatched D365/POS rows rolling forward, not necessarily unsettled *bank* items specifically — the V28 spec doesn't define what populates it), and this request extends or repurposes that existing mechanism.
- Or "Carry Forward" is currently an empty/placeholder dataset shape that nothing populates yet, and this request would be the first real logic to fill it.

**This is exactly the kind of thing that must not be guessed.** Building new carry-forward logic without knowing what the existing "Carry Forward" dataset already does risks two bad outcomes: duplicating a mechanism that already exists (confusing, possibly double-counting), or silently overwriting/conflicting with whatever currently populates it. Both are worse than not building it yet.

## 3. Design, to the extent specifiable without the source

**What should carry forward:**
- Card/AMEX settlement batches still `BANK REVIEW REQUIRED` or `BANK RECEIPT PENDING` at month-end.
- Provider (TABBY/Tamara/TAP) batches in the same unresolved states.
- Each carried item retains its **original period** (the month it was actually transacted/batched in) as a field, distinct from the period it's now appearing in — so August's report can show "3 items carried forward from July" without those items being mistaken for August transactions. This mirrors the same traceability discipline used everywhere else in this project (cited source rows, batch reference visibility, etc.).

**What must not happen:**
- **No JV creation change.** Carry-forward is a visibility/queue mechanism, not a settlement or accounting decision — the JV gate (proven settlement evidence required) is completely unaffected. An unsettled item stays unsettled whether it's shown in July's queue or carried into August's; carrying it forward doesn't change its Settlement Status.
- **No silent duplication.** If a carried-forward July item finally settles while looking at the August run, it must resolve in exactly one place — not show as pending in both July's saved run (V28) and August's live queue simultaneously. Needs a clear rule (likely: settled status updates wherever the live item now lives, and V28's *historical* July snapshot stays exactly as it was at the time — read-only, per V28's own design — rather than being retroactively edited).
- **No re-triggering of matching logic that shouldn't re-run.** Carrying an item forward should not cause it to be re-evaluated against a different (e.g. wider, staler) bank pool than the matching engine's existing rules intend, unless that's explicitly the point (worth deciding: does a carried-forward July batch get re-checked against August's bank statement too, in case the bank simply posted it very late? That seems likely to be exactly the point of this request — but it's a real design decision, not a given.)

**Likely useful UI surface:** a "Carried Forward from Prior Period(s)" section on the main reconciliation output and/or the V28 Run History page, showing origin period + current status, separate from the current period's own new batches — so nothing gets missed, but nothing gets double-reported either.

## 4. Open questions that need answers from the real source before this can be built correctly

1. What does the existing `"Carry Forward"` dataset in `ct_result` (referenced in V28) actually contain today? Is it populated by any current logic, or is it currently empty/unused?
2. Should a carried-forward item be **re-matched** against the new month's bank statement (the likely real intent — "maybe the bank finally posted it"), or purely carried as a **display-only** rollover with matching only ever run manually via Settlement Batch Engine?
3. How does this interact with V28's Run History snapshots — does a settled carried-forward item get reflected back into its *original* month's historical run record, or does settlement only ever show in whichever run/period the settlement was actually confirmed in?
4. Is there a cutoff — do items carry forward indefinitely until settled, or is there a business rule (e.g. escalate/write off/flag after N months unsettled)? Nothing in any prior spec in this project defines one; needs a decision, not an assumption.
5. Does this apply only to bank *settlement* status (Review Required/Pending), or should it also cover items still sitting in Unmatched D365/Unmatched POS from V25's underlying reconciliation — i.e. is the ask scoped narrowly to bank settlement, or broader to any unresolved reconciliation item? (Read literally, the ask is bank-settlement-specific — this spec is scoped that way — but worth confirming since "Carry Forward" as a dataset name in V28 doesn't specify its scope either.)

## 5. Why this isn't built yet

Every prior release in this project — V27's classifier fix, V27's Tabby linking, V30's settlement lag, V31's AMEX bundling — was built by reading and testing against **real source code and real data**, specifically to avoid the failure mode of confidently shipping logic that turns out to conflict with something already there. This request sits directly on top of an already-referenced-but-never-defined dataset (`Carry Forward`), inside `core.py`/`bank_settlement_extension.py`/the run-history module, none of which have been shared as actual files in this engagement. Writing carry-forward logic now would mean guessing what "Carry Forward" already means in the real system and possibly building something that collides with it the moment it runs against real data — exactly the risk this project has consistently refused to take on JV-adjacent logic.

**What's needed to move this from spec to build:** `core.py` (current version), `logic/bank_settlement_extension.py` (current version), and `logic/run_history.py` (V28), so the existing `Carry Forward` dataset's actual definition can be read before anything is added to it.

## 6. Status of related open items (unaffected by this spec)

- V32 (AI Settlement Explainer) — being built now, separately, since it's genuinely self-contained.
- V33 (provider-split JV + editable GL 1010) — still blocked on JV creation source + `db.py`.
- All items in the "Missing Logic" inventory from earlier today — unchanged by this addition.

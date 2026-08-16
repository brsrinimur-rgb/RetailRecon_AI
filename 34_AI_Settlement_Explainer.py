"""
pages/34_AI_Settlement_Explainer.py
V32 — read-only page. Explains Review Required / Receipt Pending batches
using logic.ai_settlement_explainer. Never writes Settlement Status, Bank
Settled, Underlying IDs, or a JV. See that module's docstring for the
verification-status caveat before trusting this against production numbers.

NOTE ON INTEGRATION: this page assumes st.session_state.ct_result exists
with the dataset names documented across V25-V28 ("Settlement Batches",
"Settlement Bank Unmatched", "Provider Payout Batches"). It also assumes
`auth`, `theme`, `core` modules exist per every other page in this
codebase, matching the import pattern already confirmed in the V25/V26
reviews. These have not been independently re-confirmed against a live
app in this engagement -- adjust imports/column names against the real
app before relying on this.
"""

import json
import streamlit as st
import pandas as pd

from logic import ai_settlement_explainer as explainer

try:
    import auth, theme, core  # noqa: F401  (pattern matches every other page per V25/V26 reviews)
except ImportError:
    auth = theme = core = None  # allows this file to be inspected/tested standalone


st.set_page_config(page_title="AI Settlement Explainer", layout="wide")

st.warning(
    "This page does not change settlement status, bank-settled flags, or create JVs. "
    "It only explains what the existing matching engine already found (or didn't find) "
    "for batches still in Review Required / Receipt Pending. Approve/settle actions "
    "happen through the existing reconciliation workflow, not here."
)

st.title("AI Settlement Explainer — Review Required / Receipt Pending")

ct_result = st.session_state.get("ct_result")
if not ct_result:
    st.info("No reconciliation result in session. Run reconciliation first, or load a prior "
            "run from the Reconciliation Run History page.")
    st.stop()

settlement_batches = ct_result.get("Settlement Batches")
settlement_bank_unmatched = ct_result.get("Settlement Bank Unmatched")
provider_payout_batches = ct_result.get("Provider Payout Batches")

if settlement_batches is None or (hasattr(settlement_batches, "empty") and settlement_batches.empty):
    st.info("No Settlement Batches found in the current session result.")
    st.stop()

settlement_lag_days = st.number_input(
    "Settlement lag (days) — should match the value configured on the main "
    "reconciliation / Settlement Batch Engine page (V30)",
    min_value=0, max_value=10, value=1, step=1,
)

sb_rows = settlement_batches.to_dict("records") if hasattr(settlement_batches, "to_dict") else settlement_batches
bank_rows = (
    settlement_bank_unmatched.to_dict("records")
    if settlement_bank_unmatched is not None and hasattr(settlement_bank_unmatched, "to_dict")
    else (settlement_bank_unmatched or [])
)
payout_rows = (
    provider_payout_batches.to_dict("records")
    if provider_payout_batches is not None and hasattr(provider_payout_batches, "to_dict")
    else (provider_payout_batches or [])
)

requests = explainer.build_candidates(
    settlement_batches_rows=sb_rows,
    settlement_bank_unmatched_rows=bank_rows,
    provider_payout_rows=payout_rows,
    settlement_lag_days=int(settlement_lag_days),
)

if not requests:
    st.success("No batches currently sit in BANK REVIEW REQUIRED or BANK RECEIPT PENDING.")
    st.stop()

st.write(f"**{len(requests)} batch(es)** in Review Required / Receipt Pending.")

verdict_filter = st.multiselect(
    "Filter by verdict (after explaining)",
    options=list(explainer.ALLOWED_VERDICTS),
    default=list(explainer.ALLOWED_VERDICTS),
)

if "explainer_results" not in st.session_state:
    st.session_state["explainer_results"] = {}  # batch_id -> ExplainerResult dict, this-session only

col1, col2 = st.columns([1, 3])
with col1:
    explain_all = st.button("Explain all visible batches")

overview_rows = []
for req in requests:
    overview_rows.append({
        "Batch ID": req.batch_id,
        "Provider": req.provider,
        "Terminal": req.terminal_id,
        "Date": req.source_date,
        "Gross Amount": req.gross_pos_amount,
        "# Candidates found": len(req.candidates),
        "Explained?": "Yes" if req.batch_id in st.session_state["explainer_results"] else "No",
    })
st.dataframe(pd.DataFrame(overview_rows), use_container_width=True)


def call_model_stub(prompt: str) -> str:
    """
    Placeholder for the actual model call. This page does not itself decide
    which API/model to use -- wire this to the same completion endpoint
    pattern already documented for in-app AI features (see the Anthropic
    API artifact pattern) or to whatever internal LLM access this codebase
    already uses elsewhere. Left as an explicit stub rather than guessing
    at credentials/endpoints that would silently fail or, worse, silently
    call something unintended.
    """
    raise NotImplementedError(
        "Wire call_model_stub() to your actual model endpoint before using this page. "
        "See logic/ai_settlement_explainer.build_prompt() for the exact prompt to send."
    )


def explain_batch(req):
    prompt = explainer.build_prompt(req)
    try:
        raw = call_model_stub(prompt)
    except NotImplementedError as e:
        st.session_state["explainer_results"][req.batch_id] = explainer.ExplainerResult(
            batch_id=req.batch_id,
            verdict="No Plausible Candidate",
            confidence="Low",
            gross_pos_amount=req.gross_pos_amount,
            candidate_bank_amount=None,
            fee_amount=req.fee_amount,
            vat_amount=req.vat_amount,
            computed_net=None,
            narration_decode="",
            explanation=f"Model not wired up yet: {e}",
            cited_rows=[],
        ).to_dict()
        return
    result = explainer.parse_and_validate(req.batch_id, req.gross_pos_amount, raw)
    st.session_state["explainer_results"][req.batch_id] = result.to_dict()


if explain_all:
    for req in requests:
        explain_batch(req)

st.divider()

for req in requests:
    result_dict = st.session_state["explainer_results"].get(req.batch_id)
    if result_dict and result_dict["verdict"] not in verdict_filter:
        continue

    with st.expander(f"Batch {req.batch_id} — {req.provider} — {req.terminal_id} — {req.source_date}"):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Gross POS amount:** {req.gross_pos_amount}")
            st.write(f"**Scheme:** {req.scheme}")
            st.write(f"**Fee / VAT (if known):** {req.fee_amount} / {req.vat_amount}")
        with c2:
            if st.button(f"Explain this batch", key=f"explain_{req.batch_id}"):
                explain_batch(req)
                result_dict = st.session_state["explainer_results"].get(req.batch_id)

        st.write("**Shortlisted bank candidates (from the deterministic engine, not re-searched here):**")
        if req.candidates:
            st.dataframe(pd.DataFrame([c.__dict__ for c in req.candidates]), use_container_width=True)
        else:
            st.write("_None shortlisted._")

        if result_dict:
            st.markdown(f"### Verdict: {result_dict['verdict']}  (confidence: {result_dict['confidence']})")
            st.write(result_dict["explanation"])
            if result_dict["narration_decode"]:
                st.write(f"**Narration decode:** {result_dict['narration_decode']}")
            st.write(f"**Cited rows (spot-check these directly):** {result_dict['cited_rows']}")
        else:
            st.caption("Not yet explained.")

"""
pages/35_JV_Creation_Eligibility.py
V33 — JV Creation Eligibility & Proposal page.

Implements, end to end, everything specified and confirmed in this
conversation for JV creation:

  §1a — JV creation is HELD if bank settlement evidence is missing.
  §1b — pass condition = amount actually received in the bank
        (BANK RECEIVED / transaction-level Bank Settled=True).
  §1c — "received" means landed in OUR OWN bank account (a real bank
        statement row), never a provider's own payout confirmation alone.
  §1  — provider-split option: combined JV vs. one JV per provider
        (TABBY / Tamara / TAP), each gated independently.
  §3a — GL codes (1010 for Al Rajhi bank leg, confirmed) are editable at
        runtime and persisted, never hardcoded.

WHAT THIS PAGE DOES NOT DO, STATED PLAINLY:
  - It does not post a JV. There is no db.py write path anywhere in this
    file or in logic/jv_eligibility_gate.py. "Create JV" below stages a
    JVProposal for a human to review; wiring that proposal into an actual
    posted, maker-checker-approved JV requires the real JV creation
    source and db.py, which have never been provided in this engagement.
  - It does not decide clearing_gl codes for TABBY/Tamara/TAP — those are
    still TBD-* placeholders (see logic/jv_eligibility_gate.py
    DEFAULT_GL_CONFIG) pending chart-of-accounts confirmation.
  - It assumes the hold/pass grain is per-transaction for TABBY specifically
    (V33 spec §1a open question) — confirm against real JV code before
    relying on this for TABBY's partial-batch cases.

INTEGRATION CAVEAT (same as page 34): assumes st.session_state.ct_result
and the auth/theme/core import pattern already used by every other page
in this codebase (per the V25/V26 reviews). Column names are read via
COLUMN_ALIASES in logic/jv_eligibility_gate.py — confirm against the real
core.py output before trusting this against production data.
"""

import streamlit as st
import pandas as pd

from logic import jv_eligibility_gate as gate

try:
    import auth, theme, core  # noqa: F401  (pattern matches every other page)
except ImportError:
    auth = theme = core = None


st.set_page_config(page_title="JV Creation Eligibility", layout="wide")

st.warning(
    "This page proposes JVs based on confirmed bank settlement evidence only. "
    "It does not post JVs. Nothing here changes Settlement Status, Bank Settled, "
    "or writes to any JV/ledger table — that step requires the actual JV creation "
    "workflow, which this page stages input for."
)

st.title("JV Creation — Eligibility & Provider-Split Proposal")

ct_result = st.session_state.get("ct_result")
if not ct_result:
    st.info("No reconciliation result in session. Run reconciliation first, or load a prior "
            "run from the Reconciliation Run History page.")
    st.stop()

settlement_batches = ct_result.get("Settlement Batches")
if settlement_batches is None or (hasattr(settlement_batches, "empty") and settlement_batches.empty):
    st.info("No Settlement Batches found in the current session result.")
    st.stop()

rows = settlement_batches.to_dict("records") if hasattr(settlement_batches, "to_dict") else settlement_batches

# ---------------------------------------------------------------------
# §1a/§1b/§1c — evaluate every batch/transaction for JV eligibility
# ---------------------------------------------------------------------
decisions = gate.evaluate_batches(rows)

eligible_count = sum(1 for d in decisions if d.eligible)
held_count = len(decisions) - eligible_count

c1, c2, c3 = st.columns(3)
c1.metric("Total items", len(decisions))
c2.metric("Eligible for JV (bank-confirmed)", eligible_count)
c3.metric("Held (no bank settlement evidence)", held_count)

st.divider()

# ---------------------------------------------------------------------
# §3a — editable GL codes
# ---------------------------------------------------------------------
st.subheader("GL Code Configuration (editable)")
st.caption(
    "Al Rajhi bank-leg GL code (1010) applies to TABBY / Tamara / TAP, confirmed. "
    "Clearing-leg codes below are placeholders pending chart-of-accounts confirmation — "
    "edit them here before relying on any proposal's GL mapping."
)

gl_config = gate.GLConfig(path=st.session_state.get("gl_config_path", "gl_config.json"))

providers_present = sorted({d.provider for d in decisions})
gl_edit_rows = []
for provider in providers_present:
    current = gl_config.get(provider)
    gl_edit_rows.append({"Provider": provider, "Bank GL": current["bank_gl"], "Clearing GL": current["clearing_gl"]})

edited = st.data_editor(
    pd.DataFrame(gl_edit_rows),
    use_container_width=True,
    num_rows="fixed",
    key="gl_editor",
)

if st.button("Save GL code changes"):
    for _, r in edited.iterrows():
        gl_config.set_bank_gl(r["Provider"], str(r["Bank GL"]), persist=False)
        gl_config.set_clearing_gl(r["Provider"], str(r["Clearing GL"]), persist=False)
    gl_config.save()
    st.success("GL codes saved. They will apply to proposals generated below from now on.")

st.divider()

# ---------------------------------------------------------------------
# §1 — provider-split option
# ---------------------------------------------------------------------
st.subheader("JV Proposal")

mode_label = st.radio(
    "JV creation mode",
    options=["One JV per provider (recommended)", "One combined JV across all providers"],
    index=0,
)
mode = "per_provider" if mode_label.startswith("One JV per provider") else "combined"

proposals = gate.group_for_jv(decisions, gl_config, mode=mode)

for p in proposals:
    with st.container(border=True):
        header = f"Provider: {p.provider}" if p.mode == "per_provider" else "Combined (all providers)"
        st.markdown(f"### {header}")

        col1, col2, col3 = st.columns(3)
        col1.metric("Amount eligible", f"{p.total_amount:,.2f}")
        col2.metric("Lines eligible", p.line_count)
        col3.metric("Held (excluded)", p.held_count)

        st.write(f"**Bank GL (Al Rajhi leg):** {p.bank_gl}" +
                 (" ⚠️ needs manual split — mixed GL codes in this group" if p.bank_gl == "MIXED-GL-NEEDS-SPLIT" else ""))
        st.write(f"**Clearing GL:** {p.clearing_gl}")

        if p.batch_ids:
            st.write("**Eligible batch/transaction IDs (will be included if this JV is created):**")
            st.code(", ".join(p.batch_ids))
        else:
            st.caption("No eligible items for this group — nothing would be posted.")

        if p.held_batch_ids:
            with st.expander(f"Held items excluded from this JV ({p.held_count}) — held reasons"):
                held_detail = [
                    {"Batch ID": d.batch_id, "Status": d.settlement_status, "Reason": d.reason}
                    for d in decisions if d.batch_id in p.held_batch_ids
                ]
                st.dataframe(pd.DataFrame(held_detail), use_container_width=True)

        stage_disabled = p.line_count == 0
        if st.button(
            f"Stage JV proposal — {header}",
            key=f"stage_{p.mode}_{p.provider}",
            disabled=stage_disabled,
        ):
            st.session_state.setdefault("staged_jv_proposals", []).append(p.to_dict())
            st.success(
                f"Staged. This proposal is NOT posted — actual JV creation still requires "
                f"the real JV workflow, which is not wired up in this page."
            )

st.divider()

if st.session_state.get("staged_jv_proposals"):
    st.subheader("Staged proposals this session (not posted)")
    st.dataframe(pd.DataFrame(st.session_state["staged_jv_proposals"]), use_container_width=True)
    st.caption(
        "These are held in this page's own session state only. Nothing here has been written "
        "to Settlement Status, Bank Settled, Underlying IDs, or any JV/ledger table."
    )

st.divider()
st.subheader("All items — eligibility detail")
detail_df = pd.DataFrame([d.to_dict() for d in decisions])
status_filter = st.multiselect(
    "Filter by eligibility",
    options=["Eligible", "Held"],
    default=["Eligible", "Held"],
)
mask = pd.Series(True, index=detail_df.index)
if "Eligible" not in status_filter:
    mask &= ~detail_df["eligible"]
if "Held" not in status_filter:
    mask &= detail_df["eligible"]
st.dataframe(detail_df[mask], use_container_width=True)

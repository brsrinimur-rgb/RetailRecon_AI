from __future__ import annotations

import pandas as pd
import streamlit as st

import auth, theme, db
from ai_copilot import answer_question, CopilotContext

st.set_page_config(page_title="AI Finance Copilot",layout="wide",page_icon="🤖")
auth.require_login({"Admin","Finance Manager","Finance Maker","Finance Checker","Store User"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","AI Finance Copilot"),unsafe_allow_html=True)

st.title("🤖 AI Finance Copilot")
st.caption(
    "Ask naturally about the active RetailRecon data. The Copilot is read-only: it can analyze, "
    "calculate, explain and recommend, but it cannot approve corrections, close periods or post JVs."
)

result=st.session_state.get("ct_result")
if not result:
    st.warning("No active reconciliation is loaded. Run POS Reconciliation first, then return here.")
    st.page_link("pages/1_POS_Reconciliation.py",label="Open POS Reconciliation",icon="🧾")
    st.stop()

def _maybe_chart(table):
    """
    Render a chart alongside the table when the shape is obviously visual:
    a daily trend (Date + Net Cash, more than one date) or a per-store
    comparison/ranking (Store Code + a total column, more than one store).
    Silently does nothing for shapes that don't fit - the table is always
    shown regardless, this is additive only.
    """
    if not isinstance(table,pd.DataFrame) or table.empty:
        return
    cols=set(table.columns)
    try:
        if {"Date","Net Cash"}.issubset(cols) and table["Date"].nunique()>1:
            if "Store Code" in cols and table["Store Code"].nunique()>1:
                chart_df=table.pivot_table(index="Date",columns="Store Code",values="Net Cash",aggfunc="sum")
            else:
                chart_df=table.set_index("Date")[["Net Cash"]]
            st.line_chart(chart_df)
        elif {"Store Code","Net Cash"}.issubset(cols) and len(table)>1:
            st.bar_chart(table.set_index("Store Code")["Net Cash"])
        elif {"Store Code","Sales/Tender Total"}.issubset(cols) and len(table)>1:
            st.bar_chart(table.set_index("Store Code")["Sales/Tender Total"])
    except Exception:
        pass  # chart is a bonus, never block the actual answer

if "copilot_context" not in st.session_state:
    st.session_state.copilot_context=CopilotContext()
if "copilot_messages" not in st.session_state:
    st.session_state.copilot_messages=[]

# V-fix (2026-09-11): removed the always-visible "Daily Finance Briefing"
# expander at the user's request. It used to auto-run a fixed "finance
# summary" question and render it above the chat every time this page
# loaded. This only removed the box that always appeared, unasked, at the
# top of the page -- the same summary is still reachable by simply typing
# a question for it in the chat box below.
#
# V-fix (2026-09-11, same day): also removed the entire "Try asking"
# quick-question button grid (16 buttons across 4 rows) at the user's
# explicit request ("remove the details from AI Ask"). `quick` is gone
# along with it -- the chat input below (`prompt=st.chat_input(...)`) is
# completely unaffected and is still the only way to ask a question, exactly
# as it already was for anything not covered by one of these buttons.

for msg in st.session_state.copilot_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        table=msg.get("table")
        if isinstance(table,pd.DataFrame) and not table.empty:
            st.dataframe(table,use_container_width=True,hide_index=True)
            _maybe_chart(table)

prompt=st.chat_input(
    "Ask RetailRecon AI… e.g. '601 sales as of 9 Aug 2026', 'only MADA', 'which are unsettled?', 'show transactions'"
)

if prompt:
    st.session_state.copilot_messages.append({"role":"user","text":prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    payload=answer_question(
        prompt,
        result,
        db_module=db,
        prior_context=st.session_state.copilot_context,
        user_context=st.session_state.get("user"),
    )
    st.session_state.copilot_context=payload["context"]

    with st.chat_message("assistant"):
        st.markdown(payload["text"])
        table=payload.get("table")
        if isinstance(table,pd.DataFrame) and not table.empty:
            st.dataframe(table,use_container_width=True,hide_index=True)
            _maybe_chart(table)

    st.session_state.copilot_messages.append({
        "role":"assistant",
        "text":payload["text"],
        "table":payload.get("table",pd.DataFrame()),
    })

with st.sidebar:
    st.divider()
    st.subheader("Copilot Context")
    ctx=st.session_state.copilot_context
    _u=st.session_state.get("user") or {}
    if _u.get("store_codes"):
        st.caption(f"Logged in as Store User — scoped to store(s) {', '.join(_u['store_codes'])}")
    st.write("Store:",", ".join(ctx.store_codes) if ctx.store_codes else "All")
    st.write("Payment:",ctx.payment or "All")
    if ctx.date_from is not None or ctx.date_to is not None:
        st.write("From:",ctx.date_from.strftime("%d-%b-%Y") if ctx.date_from is not None else "Start")
        st.write("To:",ctx.date_to.strftime("%d-%b-%Y") if ctx.date_to is not None else "Latest")
    else:
        st.write("Date: Active loaded period")

    if st.button("Clear conversation/context",use_container_width=True):
        st.session_state.copilot_context=CopilotContext()
        st.session_state.copilot_messages=[]
        st.rerun()

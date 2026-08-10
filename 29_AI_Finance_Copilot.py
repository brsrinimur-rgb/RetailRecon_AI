from __future__ import annotations

import pandas as pd
import streamlit as st

import auth, theme, db
from ai_copilot import answer_question, CopilotContext

st.set_page_config(page_title="AI Finance Copilot",layout="wide",page_icon="🤖")
auth.require_login({"Admin","Finance Manager","Finance Maker","Finance Checker"})
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

if "copilot_context" not in st.session_state:
    st.session_state.copilot_context=CopilotContext()
if "copilot_messages" not in st.session_state:
    st.session_state.copilot_messages=[]

# Daily finance briefing
with st.expander("☀️ Daily Finance Briefing",expanded=True):
    briefing=answer_question("give me a finance summary",result,db,st.session_state.copilot_context)
    st.markdown(briefing["text"])
    if isinstance(briefing.get("table"),pd.DataFrame) and not briefing["table"].empty:
        st.dataframe(briefing["table"],use_container_width=True,hide_index=True)

st.markdown("#### Try asking")
q1,q2,q3,q4=st.columns(4)
quick=None
if q1.button("601 sales as of 9 Aug 2026",use_container_width=True):
    quick="601 sales as of 9 Aug 2026"
if q2.button("Which transactions are not settled?",use_container_width=True):
    quick="which transactions are not settled?"
if q3.button("Show pending corrections",use_container_width=True):
    quick="show pending corrections"
if q4.button("Which mappings are missing?",use_container_width=True):
    quick="which mappings are missing?"

for msg in st.session_state.copilot_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        table=msg.get("table")
        if isinstance(table,pd.DataFrame) and not table.empty:
            st.dataframe(table,use_container_width=True,hide_index=True)

prompt=st.chat_input(
    "Ask RetailRecon AI… e.g. '601 sales as of 9 Aug 2026', 'only MADA', 'which are unsettled?', 'show transactions'"
)
if quick:
    prompt=quick

if prompt:
    st.session_state.copilot_messages.append({"role":"user","text":prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    payload=answer_question(
        prompt,
        result,
        db_module=db,
        prior_context=st.session_state.copilot_context,
    )
    st.session_state.copilot_context=payload["context"]

    with st.chat_message("assistant"):
        st.markdown(payload["text"])
        table=payload.get("table")
        if isinstance(table,pd.DataFrame) and not table.empty:
            st.dataframe(table,use_container_width=True,hide_index=True)

    st.session_state.copilot_messages.append({
        "role":"assistant",
        "text":payload["text"],
        "table":payload.get("table",pd.DataFrame()),
    })

with st.sidebar:
    st.divider()
    st.subheader("Copilot Context")
    ctx=st.session_state.copilot_context
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

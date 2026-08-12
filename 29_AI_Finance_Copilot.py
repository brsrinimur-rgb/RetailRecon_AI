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

# Daily finance briefing.
# Deliberately NOT passed the sticky chat context: this is a fixed, always-neutral
# overview, not a conversational turn. Reusing st.session_state.copilot_context here
# previously leaked whatever the user was drilling into in chat (e.g. after asking a
# cash question, this box kept re-rendering the old CASH-scoped tender-total line on
# every rerun instead of a true overall summary).
with st.expander("☀️ Daily Finance Briefing",expanded=True):
    briefing=answer_question("give me a finance summary",result,db,None,user_context=st.session_state.get("user"))
    st.markdown(briefing["text"])
    if isinstance(briefing.get("table"),pd.DataFrame) and not briefing["table"].empty:
        st.dataframe(briefing["table"],use_container_width=True,hide_index=True)

st.markdown("#### Try asking")
q1,q2,q3,q4=st.columns(4)
quick=None
if q1.button("All store cash sales",use_container_width=True):
    quick="need all store cash sales"
if q2.button("601 sales as of 9 Aug 2026",use_container_width=True):
    quick="601 sales as of 9 Aug 2026"
if q3.button("Which transactions are not settled?",use_container_width=True):
    quick="which transactions are not settled?"
if q4.button("Show pending corrections",use_container_width=True):
    quick="show pending corrections"

r1,r2,r3,r4=st.columns(4)
if r1.button("What needs attention?",use_container_width=True):
    quick="what needs attention?"
if r2.button("Store performance",use_container_width=True):
    quick="show store performance"
if r3.button("Provider performance",use_container_width=True):
    quick="show provider performance"
if r4.button("Top 10 risks",use_container_width=True):
    quick="show top 10 risks"

g1,g2,g3,g4=st.columns(4)
if g1.button("D365 GL status",use_container_width=True):
    quick="show d365 gl status"
if g2.button("GL exceptions",use_container_width=True):
    quick="show gl exceptions"
if g3.button("Clearing movement",use_container_width=True):
    quick="show clearing movement"
if g4.button("Unexplained GL",use_container_width=True):
    quick="show unexplained gl"

s1,s2,s3,s4=st.columns(4)
if s1.button("Finance briefing",use_container_width=True):
    quick="give me a finance briefing"
if s2.button("Settlement status",use_container_width=True):
    quick="show settlement status"
if s3.button("Data quality",use_container_width=True):
    quick="check data quality"
if s4.button("Close readiness",use_container_width=True):
    quick="can I close the period?"

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

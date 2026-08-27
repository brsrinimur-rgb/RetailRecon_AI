import streamlit as st
import auth, theme

st.set_page_config(page_title="Retail Control Tower", layout="wide", page_icon="🏬")
auth.require_login()
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER",
                             "POS Reconciliation → POS-to-GL Control Center"),
            unsafe_allow_html=True)

st.title("Finance Control Tower")
st.caption("Reconcile → Validate → Settle → Correct → Close → Configure GL → Create JV → Approve → Post to D365 → Verify.")

c1, c2, c3 = st.columns(3)
c1.metric("Control Model", "POS → Bank → GL")
c2.metric("Tolerance", "SAR 1.00")
c3.metric("Posting", "Maker-Checker")

def card(col, title, description, page, icon):
    with col:
        st.markdown(f"### {icon} {title}")
        st.caption(description)
        st.page_link(page, label=f"Open {title}", icon="➡️")

st.subheader("1. Reconciliation & Treasury Controls")
a,b,c = st.columns(3)
card(a,"POS Reconciliation","Main POS and settlement reconciliation control.",
     "pages/1_POS_Reconciliation.py","🧾")
card(b,"Commission Validation","Validate provider commission and VAT.",
     "pages/10_Commission_Validation.py","🧾")
card(c,"Bank Settlement Audit","Match settlement batches to bank credits.",
     "pages/11_Bank_Settlement_Audit.py","🏦")

a,b,c = st.columns(3)
card(a,"Refund Reconciliation","Control refunds and reversals.",
     "pages/12_Refund_Reconciliation.py","↩️")
card(b,"POS Auto Mapper","Map new POS/provider layouts.",
     "pages/13_POS_Auto_Mapper.py","🧩")
card(c,"Store Mapping Master","Maintain provider store to D365 store mappings.",
     "pages/14_Store_Mapping_Master.py","🏬")

a,b,c = st.columns(3)
card(a,"Bank Claim Follow Up","Track missing and delayed settlements.",
     "pages/15_Bank_Claim_Follow_Up.py","📨")
card(b,"POS Terminal Master","Maintain Terminal ID to Store Code mappings.",
     "pages/16_POS_Terminal_Master.py","🖥️")
card(c,"Merchant ID Master","Maintain Merchant ID to Store Code mappings.",
     "pages/17_Merchant_ID_Master.py","🏷️")

st.subheader("2. Close, Configuration & Exception Control")
a,b,c = st.columns(3)
card(a,"Settlement Batch Engine","Settlement batch processing and controls.",
     "pages/18_Settlement_Batch_Engine.py","⚙️")
card(b,"Month End Close Calendar","Finance close ownership and status.",
     "pages/21_Month_End_Close_Calendar.py","🗓️")
card(c,"GL Configuration","Maintain GL and accounting mappings.",
     "pages/22_GL_Configuration.py","⚙️")

a,b,c = st.columns(3)
card(a,"Exception Correction Center","Investigate and control reconciliation exceptions.",
     "pages/23_Exception_Correction_Center.py","🛠️")
card(b,"D365 GL Reconciliation","D365 GL verification and reconciliation.",
     "pages/30_D365_GL_Reconciliation.py","📊")
card(c,"Database Health","Check database and schema health.",
     "pages/31_Database_Health.py","🗄️")

st.subheader("3. JV, D365 Posting & Verification")
a,b,c = st.columns(3)
card(a,"JV Creation","Create controlled journal vouchers.",
     "pages/24_JV_Creation.py","🧾")
card(b,"JV Approval Center","Maker-checker approval before posting.",
     "pages/25_JV_Approval_Center.py","✅")
card(c,"D365 Posting Center","Controlled D365 posting queue.",
     "pages/26_D365_Posting_Center.py","🚀")

a,b,c = st.columns(3)
card(a,"D365 Posting Verification","Verify successful D365 posting.",
     "pages/27_D365_Posting_Verification.py","🔎")
card(b,"Late Transaction Adjustment JV","Controlled late transaction adjustments.",
     "pages/28_Late_Transaction_Adjustment_JV.py","🔁")
card(c,"AI Finance Copilot","Finance control and reconciliation assistant.",
     "pages/29_AI_Finance_Copilot.py","🤖")

st.subheader("4. POS → GL Control")
a,b,c = st.columns(3)
card(a,"POS → D365 GL Reconciliation",
     "Match POS Statement to D365 GL Amount. Multiple POS and GL files are supported.",
     "pages/35_POS_GL_Reconciliation.py","🔗")
card(b,"AI Settlement Explainer",
     "Explain settlement exceptions and reconciliation results.",
     "pages/34_AI_Settlement_Explainer.py","🧠")
card(c,"Reconciliation Run History",
     "View reconciliation runs and audit history.",
     "pages/36_Reconciliation_Run_History.py","📜")

st.subheader("5. System Health")
a,b = st.columns(2)
card(a,"System Logic Health","Check application logic and module health.",
     "pages/32_System_Logic_Health.py","🩺")
card(b,"Settlement Carry Forward","Manage settlement carry-forward.",
     "pages/33_Settlement_Carry_Forward.py","↪️")


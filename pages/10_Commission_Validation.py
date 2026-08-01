from __future__ import annotations
import io
import numpy as np
import pandas as pd
import streamlit as st

import auth, theme, db

st.set_page_config(page_title="Commission Validation",layout="wide",page_icon="💳")
auth.require_login({"Admin","Finance Manager","Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(
    theme.top_banner("RETAIL CONTROL TOWER","Commission Audit & Contract Validation"),
    unsafe_allow_html=True
)

st.title("Commission Validation")
st.caption(
    "Validate provider commission by payment type. Contract rates are maintained in the "
    "Commission Rate Master and can be changed without modifying Python code."
)

# --------------------------------------------------------------- rate master
with st.expander("⚙️ Commission Rate Master", expanded=True):
    master=db.load_commission_rate_master()

    st.info(
        "Confirmed rates: MADA 0.55%, VISA 1.55%, MASTERCARD 1.55%, "
        "GCC NET 1.50%, AMEX 3.00%. TABBY/TAMARA/TAP currently use provider actual fee "
        "until an approved contract rate is entered."
    )

    editable=master.drop(columns=["Updated At"],errors="ignore").copy()

    edited=st.data_editor(
        editable,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Payment Type": st.column_config.TextColumn("Payment Type",required=True),
            "Commission Rate %": st.column_config.NumberColumn(
                "Commission Rate %",min_value=0.0,max_value=20.0,step=0.01,format="%.2f"
            ),
            "VAT Rate %": st.column_config.NumberColumn(
                "VAT Rate %",min_value=0.0,max_value=100.0,step=0.01,format="%.2f"
            ),
            "Validation Method": st.column_config.SelectboxColumn(
                "Validation Method",
                options=["CONTRACT_RATE","PROVIDER_ACTUAL"],
                required=True,
            ),
            "Active": st.column_config.SelectboxColumn(
                "Active",options=["Yes","No"],required=True
            ),
        }
    )

    c1,c2=st.columns(2)
    if c1.button("SAVE COMMISSION RATE MASTER",type="primary",use_container_width=True):
        db.save_commission_rate_master(edited,"replace")
        st.success("Commission Rate Master saved.")
        st.rerun()

    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as w:
        edited.to_excel(w,index=False,sheet_name="COMMISSION_RATE_MASTER")
    c2.download_button(
        "DOWNLOAD COMMISSION RATE MASTER",
        data=out.getvalue(),
        file_name="RetailRecon_AI_Commission_Rate_Master.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.divider()

# --------------------------------------------------------------- reconciliation
r=st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

m=r.get("matched",pd.DataFrame()).copy()
if m.empty:
    st.info("No matched transactions are available for commission validation.")
    st.stop()

master=db.load_commission_rate_master().copy()
master["Payment Type"]=master["Payment Type"].astype(str).str.strip().str.upper()
master["Active"]=master["Active"].astype(str).str.strip().str.upper()
master=master[master["Active"].isin(["YES","Y","TRUE","1"])].copy()

# Normalize tender naming.
def norm_payment(v):
    p=str(v or "").strip().upper()
    aliases={
        "MASTER":"MASTERCARD",
        "MC":"MASTERCARD",
        "VC":"VISA",
        "P":"MADA",
        "P1":"MADA",
        "AX":"AMEX",
        "GCCNET":"GCC NET",
        "GCC_NET":"GCC NET",
        "GCC-NET":"GCC NET",
    }
    return aliases.get(p,p)

m["Payment Type"]=m["Payment Type"].apply(norm_payment)

rate_map=master.set_index("Payment Type")["Commission Rate %"].to_dict()
vat_map=master.set_index("Payment Type")["VAT Rate %"].to_dict()
method_map=master.set_index("Payment Type")["Validation Method"].to_dict()

m["Contract Rate %"]=m["Payment Type"].map(rate_map)
m["VAT Rate %"]=m["Payment Type"].map(vat_map).fillna(15.0)
m["Validation Method"]=m["Payment Type"].map(method_map).fillna("RATE_NOT_CONFIGURED")

m["Actual Commission"]=pd.to_numeric(m["Commission"],errors="coerce").fillna(0.0).round(2)
m["Actual VAT"]=pd.to_numeric(m["VAT"],errors="coerce").fillna(0.0).round(2)

def expected_commission(row):
    method=str(row["Validation Method"]).upper()
    rate=row["Contract Rate %"]

    if method=="CONTRACT_RATE" and pd.notna(rate):
        return round(abs(float(row["POS Amount"])) * float(rate) / 100.0, 2)

    # Provider actual mode: contract not yet configured.
    if method=="PROVIDER_ACTUAL":
        return np.nan

    return np.nan

m["Expected Commission"]=m.apply(expected_commission,axis=1)
m["Expected VAT"]=(m["Expected Commission"] * m["VAT Rate %"] / 100.0).round(2)

m["Commission Variance"]=(m["Actual Commission"]-m["Expected Commission"]).round(2)
m["VAT Variance"]=(m["Actual VAT"]-m["Expected VAT"]).round(2)

def commission_status(row):
    method=str(row["Validation Method"]).upper()

    if method=="PROVIDER_ACTUAL":
        return "CONTRACT RATE PENDING"

    if pd.isna(row["Expected Commission"]):
        return "RATE NOT CONFIGURED"

    variance=float(row["Commission Variance"])
    if abs(variance)<=0.05:
        return "OK"
    if variance>0:
        return "OVERCHARGED"
    return "UNDERCHARGED"

m["Commission Status"]=m.apply(commission_status,axis=1)

# Expected net is only calculated where a contract rate exists.
m["Expected Net Amount"]=(
    pd.to_numeric(m["POS Amount"],errors="coerce").abs()
    - m["Expected Commission"].fillna(0)
    - m["Expected VAT"].fillna(0)
).round(2)
m.loc[m["Expected Commission"].isna(),"Expected Net Amount"]=np.nan

# --------------------------------------------------------------- KPI
ok=(m["Commission Status"]=="OK").sum()
over=(m["Commission Status"]=="OVERCHARGED").sum()
under=(m["Commission Status"]=="UNDERCHARGED").sum()
pending=m["Commission Status"].isin(["CONTRACT RATE PENDING","RATE NOT CONFIGURED"]).sum()

k1,k2,k3,k4=st.columns(4)
k1.metric("Commission OK",int(ok))
k2.metric("Overcharged",int(over))
k3.metric("Undercharged",int(under))
k4.metric("Rate Pending / Missing",int(pending))

# --------------------------------------------------------------- display
cols=[
    "Store Code","Date","Auth Code","Payment Type","POS Amount",
    "Contract Rate %","Validation Method",
    "Actual Commission","Expected Commission","Commission Variance",
    "VAT Rate %","Actual VAT","Expected VAT","VAT Variance",
    "Net Amount","Expected Net Amount","Commission Status","Source File"
]
cols=[c for c in cols if c in m.columns]

st.markdown("### Transaction-Level Commission Validation")
st.dataframe(m[cols],use_container_width=True,hide_index=True)

exceptions=m[m["Commission Status"]!="OK"].copy()
st.markdown("### Commission Exceptions")
if exceptions.empty:
    st.success("No commission exceptions found for configured contract rates.")
else:
    st.dataframe(exceptions[cols],use_container_width=True,hide_index=True)

# --------------------------------------------------------------- export
b=io.BytesIO()
with pd.ExcelWriter(b,engine="openpyxl") as w:
    m[cols].to_excel(w,index=False,sheet_name="Commission Validation")
    master.to_excel(w,index=False,sheet_name="Rate Master")

st.download_button(
    "DOWNLOAD COMMISSION VALIDATION",
    data=b.getvalue(),
    file_name="RetailRecon_AI_Commission_Validation.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

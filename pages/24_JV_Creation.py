import streamlit as st
import pandas as pd
import auth, theme, core, db

st.set_page_config(page_title="JV Creation", layout="wide")
auth.require_login({"Admin", "Finance Manager", "Finance Maker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "JV Creation"), unsafe_allow_html=True)

st.title("JV Creation — All Locations by Date Range")

st.info(
    "Confirmed Finance grouping: CC = MADA + VISA + MASTERCARD. "
    "AMEX, TABBY, TAMARA and TAP remain separate JVs. "
    "The selected From/To dates are applied to the Matched report for ALL locations."
)

r=st.session_state.get("ct_result")
if not r:
    st.info("Run POS Reconciliation first.")
    st.stop()

matched=r.get("matched",pd.DataFrame())
if matched is None or matched.empty:
    st.warning("The current reconciliation has no Matched transactions.")
    st.stop()

dates=pd.to_datetime(matched.get("Date"),errors="coerce").dropna()
if dates.empty:
    st.error("Matched report does not contain usable transaction dates.")
    st.stop()

min_date=dates.min().date()
max_date=dates.max().date()

st.markdown("### 1. Select JV Source Period")
c1,c2=st.columns(2)
from_date=c1.date_input("From Date",value=min_date,min_value=min_date,max_value=max_date)
to_date=c2.date_input("To Date",value=max_date,min_value=min_date,max_value=max_date)

if from_date>to_date:
    st.error("From Date cannot be later than To Date.")
    st.stop()

# Preview uses the same hard eligibility gates as core.create_jv().
preview=matched.copy()
preview["_Date"]=pd.to_datetime(preview["Date"],errors="coerce").dt.date
preview=preview[
    (preview["Status"]=="Matched")
    & (pd.to_numeric(preview["Difference"],errors="coerce").abs()<=1.0)
    & (preview["Bank Settled"]==True)
    & (preview["_Date"]>=from_date)
    & (preview["_Date"]<=to_date)
].copy()

if not preview.empty:
    preview["Payment Type"]=preview["Payment Type"].apply(core._norm_payment)
    preview["JV Group"]=preview["Payment Type"].apply(core.jv_group)
    preview["_Amount"]=pd.to_numeric(preview["D365 Amount"],errors="coerce").fillna(0.0)
    summary=(
        preview.groupby(["Store Code","JV Group"],dropna=False)
        .agg(
            Transactions=("D365 Amount","size"),
            Gross_Amount=("_Amount","sum"),
            First_Transaction_Date=("_Date","min"),
            Last_Transaction_Date=("_Date","max"),
        )
        .reset_index()
        .sort_values(["Store Code","JV Group"])
    )
    summary["Gross Amount"]=summary["Gross_Amount"].map(lambda x:f"SAR {x:,.2f}")
    summary=summary.drop(columns=["Gross_Amount"])
else:
    summary=pd.DataFrame()

m1,m2,m3,m4=st.columns(4)
m1.metric("Selected Period",f"{from_date:%d-%b-%Y} → {to_date:%d-%b-%Y}")
m2.metric("Eligible Matched Transactions",f"{len(preview):,}")
m3.metric("Locations",f"{preview['Store Code'].nunique() if not preview.empty else 0:,}")
m4.metric("JV Batches to Create",f"{len(summary):,}")

st.markdown("### 2. All-Location JV Preview")
st.caption(
    "One batch is created for each Store + JV Group. "
    "MADA, VISA and MASTERCARD are combined into CC before batch creation."
)
if summary.empty:
    st.warning("No bank-settled Matched transactions are eligible in the selected date range.")
else:
    st.dataframe(summary,use_container_width=True,hide_index=True)

st.markdown("### 3. D365 Accounting Date")
period_ctrl=db.load_accounting_period_control("ULC")
p1,p2,p3=st.columns(3)
p1.metric("Closed Through",period_ctrl.get("Closed Through Date") or "Not set")
p2.metric("Next Open Date",period_ctrl.get("Next Open Date") or "Not set")
p3.metric("Status",period_ctrl.get("Status") or "OPEN")

default_acc=pd.to_datetime(period_ctrl.get("Next Open Date",""),errors="coerce")
if pd.isna(default_acc):
    default_acc=pd.Timestamp.today().normalize()

accounting_date=st.date_input(
    "JV Accounting Date",
    value=default_acc.date(),
    help="D365 posting date. It does not change the selected source transaction From/To dates."
)
acc_open,acc_msg=db.is_accounting_date_open(accounting_date,"ULC")
if acc_open:
    st.success(f"Accounting Date {pd.Timestamp(accounting_date):%d-%b-%Y} is OPEN.")
else:
    st.error("Posting period blocked: "+acc_msg)

create_disabled=summary.empty or not acc_open
if st.button(
    f"CREATE ALL READY JVs — {from_date:%d-%b-%Y} TO {to_date:%d-%b-%Y}",
    type="primary",
    use_container_width=True,
    disabled=create_disabled
):
    gl_config=db.load_gl_config()
    j=core.create_jv(
        matched,
        gl_config,
        db.load_commission_rate_master(),
        accounting_date=accounting_date,
        period_control=period_ctrl,
        from_date=from_date,
        to_date=to_date,
    )
    j=core.validate_jv(j,gl_config)
    db.replace_jv(j)

    n_batches=j["Journal Batch"].nunique() if not j.empty else 0
    n_stores=j["Store Code"].nunique() if not j.empty else 0
    n_failed=j.loc[~j["Validation Passed"],"Journal Batch"].nunique() if not j.empty else 0

    if n_failed:
        st.error(
            f"Created {n_batches} batches across {n_stores} locations, but "
            f"{n_failed} failed D365 validation and are BLOCKED."
        )
    else:
        st.success(
            f"Created {n_batches} JV batches across {n_stores} locations for "
            f"{from_date:%d-%b-%Y} to {to_date:%d-%b-%Y}. All passed D365 validation."
        )

j=db.load_jv()
if not j.empty:
    st.markdown("### Created JV Batches")
    preferred=[
        "Valid","Company accounts","Journal batch number","RecId","Line number","Date",
        "Store Code","Store Name","Group","JV From Date","JV To Date","JV Source Period",
        "Account type","Main Account","Ledger Dimension","Default Dimension","Location",
        "Source Date","Source Period","JV Accounting Date","Accounting Period",
        "Carry Forward From Closed Period","Currency","Debit","Credit","Description",
        "Difference","Balanced","Validation Passed","Validation Date","Mapping Version",
        "Validated By/System","Validation Errors","Approval Status","D365 Status","Voucher"
    ]
    show=[c for c in preferred if c in j.columns]
    st.dataframe(j[show] if show else j,use_container_width=True,hide_index=True)

    if "Balanced" in j.columns and (~j["Balanced"].astype(bool)).any():
        st.error("Unbalanced JV detected. Posting is blocked.")
    if "Validation Passed" in j.columns and (~j["Validation Passed"].astype(bool)).any():
        failed=j.loc[~j["Validation Passed"].astype(bool),["Journal Batch","Validation Errors"]].drop_duplicates()
        st.error("These batches failed D365 validation and are BLOCKED:")
        st.dataframe(failed,use_container_width=True,hide_index=True)
else:
    st.info("No JV batches created yet.")

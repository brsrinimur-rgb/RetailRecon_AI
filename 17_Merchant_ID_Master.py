import io
import pandas as pd, streamlit as st
import auth,theme,db
st.set_page_config(page_title="Merchant ID Master",layout="wide")
auth.require_login({"Admin","Finance Manager"});auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Merchant ID Master"),unsafe_allow_html=True)
st.title("Merchant ID Master")
st.caption(
    "Upload or change Merchant ID → Store Code mappings at any time. No Python change is required. "
    "Used for provider files (e.g. TAP settlement) that carry a merchant_id but no Terminal ID and no "
    "usable store name. Store resolution priority: Terminal ID → Merchant ID → Provider Store Name → "
    "Store Mapping Required. Uploads with blank IDs, blank Store Codes, or duplicate Merchant IDs are "
    "rejected outright. Every change is recorded below with who made it and what changed."
)
user=st.session_state.user["username"]
u=st.file_uploader("Upload Merchant ID Master",type=["xlsx","xls","csv"])
mode=st.radio("Action",["Merge / Update","Replace Complete Master"],horizontal=True)
if u:
    d=pd.read_csv(u,dtype=str) if u.name.lower().endswith(".csv") else pd.read_excel(u,dtype=str)
    st.dataframe(d.head(100),use_container_width=True,hide_index=True)
    if st.button("SAVE UPLOADED MASTER",type="primary"):
        try:
            result=db.save_merchant_master(d,"replace" if mode.startswith("Replace") else "merge",user=user)
            st.success(f"Saved. Added {len(result['added'])}, updated {len(result['updated'])}, removed {len(result['removed'])}.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
st.divider()
cur=db.load_merchant_master()
edit=st.data_editor(cur.drop(columns=["Updated At"],errors="ignore"),num_rows="dynamic",use_container_width=True,hide_index=True)
if st.button("SAVE MANUAL CHANGES"):
    try:
        result=db.save_merchant_master(edit,"replace",user=user)
        st.success(f"Changes saved. Added {len(result['added'])}, updated {len(result['updated'])}, removed {len(result['removed'])}.")
        st.rerun()
    except ValueError as e:
        st.error(str(e))
if not cur.empty:
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine="openpyxl") as w:cur.to_excel(w,index=False,sheet_name="MERCHANT_MASTER")
    st.download_button("DOWNLOAD CURRENT MASTER",b.getvalue(),"Merchant_ID_Master.xlsx")

with st.expander("Change history (audit trail)"):
    st.dataframe(db.load_master_audit_log("merchant_master"),use_container_width=True,hide_index=True)

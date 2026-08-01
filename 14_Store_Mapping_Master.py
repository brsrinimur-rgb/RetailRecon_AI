from __future__ import annotations
import io
import pandas as pd
import streamlit as st
import auth,theme,db

st.set_page_config(page_title="Store Mapping Master",layout="wide",page_icon="🏬")
auth.require_login({"Admin","Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","Store Mapping Master"),unsafe_allow_html=True)

st.title("Store Mapping Master")
st.caption(
    "Maintain Provider/Branch/Store Name → D365 Store Code mappings without changing Python code. "
    "Uploads with blank names, blank Store Codes, or duplicate names are rejected outright. "
    "Every change is recorded below with who made it and what changed."
)
user=st.session_state.user["username"]

u=st.file_uploader("Upload Store Mapping Master",type=["xlsx","xls","csv"])
mode=st.radio("Upload action",["Merge / Update","Replace Complete Master"],horizontal=True)

if u:
    d=pd.read_csv(u,dtype=str) if u.name.lower().endswith(".csv") else pd.read_excel(u,dtype=str)
    st.dataframe(d.head(100),use_container_width=True,hide_index=True)
    if st.button("SAVE UPLOADED STORE MASTER",type="primary",use_container_width=True):
        try:
            result=db.save_store_mapping_master(d,"replace" if mode.startswith("Replace") else "merge",user=user)
            st.success(f"Saved. Added {len(result['added'])}, updated {len(result['updated'])}, removed {len(result['removed'])}.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

st.divider()
cur=db.load_store_mapping_master()
edit=st.data_editor(
    cur.drop(columns=["Updated At"],errors="ignore"),
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
)
if st.button("SAVE MANUAL CHANGES",use_container_width=True):
    try:
        result=db.save_store_mapping_master(edit,"replace",user=user)
        st.success(f"Store mapping changes saved. Added {len(result['added'])}, updated {len(result['updated'])}, removed {len(result['removed'])}.")
        st.rerun()
    except ValueError as e:
        st.error(str(e))

if not cur.empty:
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine="openpyxl") as w:
        cur.to_excel(w,index=False,sheet_name="STORE_MAPPING_MASTER")
    st.download_button("DOWNLOAD CURRENT STORE MASTER",b.getvalue(),"RetailRecon_AI_Store_Mapping_Master.xlsx")

with st.expander("Change history (audit trail)"):
    st.dataframe(db.load_master_audit_log("store_mapping_master"),use_container_width=True,hide_index=True)

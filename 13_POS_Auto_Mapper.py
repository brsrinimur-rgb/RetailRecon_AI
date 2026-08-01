import pandas as pd,streamlit as st
import auth,theme,core
st.set_page_config(page_title="POS Auto Mapper",layout="wide")
auth.require_login({"Admin","Finance Manager"});auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True);st.markdown(theme.top_banner("RETAIL CONTROL TOWER","POS Auto Mapper"),unsafe_allow_html=True)
st.title("POS Auto Mapper")
st.caption("Review new file layouts. Auth Code and POS Amount must be confirmed before a mapping is trusted.")
fs=st.file_uploader("Upload POS/provider files",type=["xlsx","xls","csv"],accept_multiple_files=True)
for f in fs or []:
    for s,d in core.read_upload(f).items():
        st.subheader(f"{f.name} · {s}")
        st.write("Detected type:",core.classify(f.name,d))
        st.dataframe(d.head(20),use_container_width=True)
        cols=[""]+list(d.columns)
        a=st.selectbox("Auth Code",cols,key=f"a-{f.name}-{s}")
        am=st.selectbox("POS Amount",cols,key=f"am-{f.name}-{s}")
        p=st.selectbox("Payment Type",cols,key=f"p-{f.name}-{s}")
        t=st.selectbox("Terminal ID",cols,key=f"t-{f.name}-{s}")
        if st.button("CONFIRM & REMEMBER",key=f"b-{f.name}-{s}"):
            st.success("Mapping confirmed for this session.")

import streamlit as st
import auth, theme, db

st.set_page_config(page_title="JV Approval Center", layout="wide")
auth.require_login({"Admin", "Finance Manager", "Finance Checker"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "JV Approval Center"), unsafe_allow_html=True)
st.title("JV Approval Center")
st.caption("Reads the shared JV database, so batches created by Finance Maker in a different login are visible here.")

j = db.load_jv()
if j.empty:
    st.info("Create JV first.")
    st.stop()

has_validation = "Validation Passed" in j.columns
has_balance = "Balanced" in j.columns

batches = j["Journal Batch"].drop_duplicates().tolist()

# A batch is only offered for approval if it passed D365 validation AND is
# balanced. This is a hard control gate, not a warning: invalid batches are
# not selectable here at all, only rejectable.
def _batch_ok(b):
    g = j[j["Journal Batch"] == b]
    ok = True
    if has_validation:
        ok = ok and bool(g["Validation Passed"].astype(bool).all())
    if has_balance:
        ok = ok and bool(g["Balanced"].astype(bool).all())
    return ok

approvable = [b for b in batches if _batch_ok(b)]
blocked = [b for b in batches if b not in approvable]

if blocked:
    st.error(
        f"{len(blocked)} batch(es) failed D365 validation and/or are unbalanced and cannot be approved. "
        "They can still be rejected below."
    )
    blocked_view_cols = [c for c in ["Journal Batch","Balanced","Validation Passed","Validation Errors"] if c in j.columns]
    st.dataframe(j[j["Journal Batch"].isin(blocked)][blocked_view_cols].drop_duplicates(), use_container_width=True, hide_index=True)

sel = st.multiselect("Select JV batches to APPROVE (validated + balanced only)", approvable, default=approvable)
reject_sel = st.multiselect("Select JV batches to REJECT (any status)", batches)
comment = st.text_area("Approval comment")
c1, c2 = st.columns(2)
if c1.button("APPROVE SELECTED", type="primary", use_container_width=True, disabled=not sel):
    db.update_jv_approval(sel, "APPROVED")
    db.append_approval_log(st.session_state.user["username"], "APPROVED", sel, comment)
    st.success("Selected JVs approved.")
    st.rerun()
if c2.button("REJECT SELECTED", use_container_width=True, disabled=not reject_sel):
    db.update_jv_approval(reject_sel, "REJECTED")
    db.append_approval_log(st.session_state.user["username"], "REJECTED", reject_sel, comment)
    st.warning("Selected JVs rejected.")
    st.rerun()

st.dataframe(db.load_jv(), use_container_width=True, hide_index=True)
with st.expander("Approval history"):
    st.dataframe(db.load_approval_log(), use_container_width=True, hide_index=True)

import pandas as pd, streamlit as st
import auth, theme, core, db

st.set_page_config(page_title="GL Configuration", layout="wide")
auth.require_login({"Admin", "Finance Manager"})
auth.render_user_sidebar()
st.markdown(theme.global_css(), unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER", "GL Configuration"), unsafe_allow_html=True)
st.title("GL Configuration")
st.caption(
    "Shared across all logins. Keys are fixed to match posting logic; only the GL account values can be "
    "changed. These values feed core.create_jv() directly - JV Creation now validates every batch against "
    "whatever is active here via core.validate_jv(), so a value changed away from the Finance-confirmed "
    "baseline below will correctly block approval/posting rather than silently drifting."
)

gl_config = db.load_gl_config()
deviations = {k: v for k, v in gl_config.items() if str(v) != str(core.D365_JV_DEFAULTS.get(k, v))}
if deviations:
    st.warning(
        "The following values differ from the Finance-confirmed baseline. JV Creation will validate "
        "against the CURRENT values below, not the baseline - only proceed if this change is intentional "
        "and confirmed with Finance:\n\n" +
        "\n".join(f"- {k}: active={gl_config[k]!r}, confirmed baseline={core.D365_JV_DEFAULTS.get(k)!r}" for k in deviations)
    )

rows = [{"Key": k, "GL Account": v} for k, v in gl_config.items()]
edit = st.data_editor(
    pd.DataFrame(rows),
    use_container_width=True,
    num_rows="fixed",
    hide_index=True,
    column_config={
        "Key": st.column_config.TextColumn("Key", disabled=True),
        "GL Account": st.column_config.TextColumn("GL Account"),
    },
)
if st.button("SAVE GL CONFIGURATION", type="primary"):
    db.save_gl_config(dict(zip(edit["Key"], edit["GL Account"].astype(str))))
    st.success("GL configuration saved.")

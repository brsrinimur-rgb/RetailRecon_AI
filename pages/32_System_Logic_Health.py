import streamlit as st
import pandas as pd
import sys
from pathlib import Path

# Streamlit executes page files independently. Add the application root
# explicitly so top-level additive packages such as `logic` resolve reliably
# on Streamlit Cloud and local deployments.
APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0,str(APP_ROOT))

import auth,theme
from logic.release_guard import run_release_health
from logic.database_logic import health as db_health

st.set_page_config(page_title="System Logic Health",layout="wide",page_icon="🧩")
auth.require_login({"Admin"})
auth.render_user_sidebar()
st.markdown(theme.global_css(),unsafe_allow_html=True)
st.markdown(theme.top_banner("RETAIL CONTROL TOWER","System Logic Health"),unsafe_allow_html=True)

st.title("🧩 System Logic Health")
st.caption(
    "Additive architecture control: existing proven logic is preserved and new capabilities are layered through separate logic modules."
)

r=run_release_health()
d=db_health()

c1,c2,c3=st.columns(3)
c1.metric("Application Logic","HEALTHY ✅" if r["Healthy"] else "REVIEW REQUIRED")
c2.metric("Database Schema","HEALTHY ✅" if d["Healthy"] else "REVIEW REQUIRED")
c3.metric("Schema Version",f"{d['Schema Version']} / {d['Required Version']}")

st.markdown("### Preserved Legacy Files")
st.dataframe(pd.DataFrame(r["Files"]),use_container_width=True,hide_index=True)

st.markdown("### Additive Logic Modules")
mods=[]
for x in r["Modules"]:
    row={
        "Module":x.get("module",""),
        "Legacy Preserved":x.get("legacy_preserved",False),
        "Extension Mode":x.get("extension_mode",x.get("migration_mode","")),
        "Healthy":x.get("Healthy",False),
    }
    mods.append(row)
st.dataframe(pd.DataFrame(mods),use_container_width=True,hide_index=True)

st.markdown("### Development Rule")
st.success("PRESERVE → EXTEND → MIGRATE → REGRESSION TEST → RELEASE")
st.markdown(
    """
    - Existing working code is not deleted for a new feature.
    - New rules are introduced through separate logic modules/wrappers where practical.
    - Database changes use migrations; production data is not reset.
    - Legacy behavior remains available unless Finance explicitly changes the requirement.
    - Every release runs current and legacy regression tests before packaging.
    """
)

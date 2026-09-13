
from __future__ import annotations

import io
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Store Email Master", page_icon="📧", layout="wide")

MASTER_PATH = Path("data/store_email_master.csv")
REQUIRED_COLS = ["Store Code", "Store Name", "To Email", "CC Email"]


def _empty_master():
    return pd.DataFrame(columns=REQUIRED_COLS)


def load_master():
    if MASTER_PATH.exists():
        try:
            df = pd.read_csv(MASTER_PATH, dtype=str).fillna("")
            for c in REQUIRED_COLS:
                if c not in df.columns:
                    df[c] = ""
            return df[REQUIRED_COLS]
        except Exception:
            return _empty_master()
    return _empty_master()


def normalize_master(df):
    if df is None:
        return _empty_master()
    out = df.copy()
    for c in REQUIRED_COLS:
        if c not in out.columns:
            out[c] = ""
    out = out[REQUIRED_COLS].fillna("")
    out["Store Code"] = out["Store Code"].astype(str).str.strip()
    out["Store Name"] = out["Store Name"].astype(str).str.strip()
    out["To Email"] = out["To Email"].astype(str).str.strip()
    out["CC Email"] = out["CC Email"].astype(str).str.strip()
    out = out[out["Store Code"].ne("")]
    out = out.drop_duplicates(subset=["Store Code"], keep="last")
    return out.reset_index(drop=True)


def save_master(df):
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalize_master(df).to_csv(MASTER_PATH, index=False)


st.title("📧 Store Email Master")
st.caption(
    "Maintain one email record per store. This page does not change POS reconciliation or matching logic."
)

master = load_master()

uploaded = st.file_uploader(
    "Upload Store Email Master",
    type=["csv", "xlsx", "xls"],
    help="Required columns: Store Code, Store Name, To Email, CC Email",
)

if uploaded is not None:
    try:
        if uploaded.name.lower().endswith(".csv"):
            incoming = pd.read_csv(uploaded, dtype=str).fillna("")
        else:
            incoming = pd.read_excel(uploaded, dtype=str).fillna("")
        incoming = normalize_master(incoming)
        if incoming.empty:
            st.warning("No valid Store Code rows found in the uploaded file.")
        else:
            master = incoming
            st.success(f"Loaded {len(master)} store email records.")
    except Exception as e:
        st.error(f"Could not read the uploaded file: {e}")

edited = st.data_editor(
    master,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "Store Code": st.column_config.TextColumn(required=True),
        "Store Name": st.column_config.TextColumn(),
        "To Email": st.column_config.TextColumn(),
        "CC Email": st.column_config.TextColumn(),
    },
    key="store_email_master_editor",
)

c1, c2, c3 = st.columns(3)

with c1:
    if st.button("💾 SAVE EMAIL MASTER", use_container_width=True):
        cleaned = normalize_master(edited)
        save_master(cleaned)
        st.success(f"Saved {len(cleaned)} store email records.")

with c2:
    cleaned = normalize_master(edited)
    st.download_button(
        "⬇️ DOWNLOAD EMAIL MASTER CSV",
        cleaned.to_csv(index=False).encode("utf-8-sig"),
        "Store_Email_Master.csv",
        mime="text/csv",
        use_container_width=True,
    )

with c3:
    missing_to = int(normalize_master(edited)["To Email"].eq("").sum()) if len(edited) else 0
    st.metric("Stores Missing To Email", missing_to)

if len(edited):
    check = normalize_master(edited)
    missing = check[check["To Email"].eq("")]
    if not missing.empty:
        st.warning("The following stores do not yet have a To Email address:")
        st.dataframe(missing[["Store Code", "Store Name"]], use_container_width=True, hide_index=True)

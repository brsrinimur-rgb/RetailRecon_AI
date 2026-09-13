
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Store Email Master", page_icon="📧", layout="wide")

MASTER_PATH = Path("data/store_email_master.csv")
MASTER_COLS = ["Store Code", "Store Name", "To Email", "CC Email"]


def _clean_code(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _empty_master() -> pd.DataFrame:
    return pd.DataFrame(columns=MASTER_COLS)


def _normalize_master(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_master()

    out = df.copy()
    for c in MASTER_COLS:
        if c not in out.columns:
            out[c] = ""

    out = out[MASTER_COLS].fillna("")
    out["Store Code"] = out["Store Code"].map(_clean_code)
    for c in ["Store Name", "To Email", "CC Email"]:
        out[c] = out[c].astype(str).str.strip()

    out = out[out["Store Code"].ne("")]
    out = out.drop_duplicates(subset=["Store Code"], keep="last")
    return out.sort_values("Store Code").reset_index(drop=True)


def _load_master() -> pd.DataFrame:
    if not MASTER_PATH.exists():
        return _empty_master()
    try:
        return _normalize_master(pd.read_csv(MASTER_PATH, dtype=str).fillna(""))
    except Exception:
        return _empty_master()


def _save_master(df: pd.DataFrame) -> None:
    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _normalize_master(df).to_csv(MASTER_PATH, index=False)


def _find_report_header_row(uploaded, sheet_name: str = "Exceptions") -> int:
    uploaded.seek(0)
    preview = pd.read_excel(uploaded, sheet_name=sheet_name, header=None, nrows=12)
    for i, row in preview.iterrows():
        vals = {str(v).strip() for v in row.tolist() if pd.notna(v)}
        if "Store Code" in vals and "Status" in vals:
            return int(i)
    raise ValueError(
        "Could not find the Exceptions header row. Expected columns include Store Code and Status."
    )


def _stores_from_reconciliation_report(uploaded) -> pd.DataFrame:
    uploaded.seek(0)
    xls = pd.ExcelFile(uploaded)
    if "Exceptions" not in xls.sheet_names:
        raise ValueError("The workbook does not contain an Exceptions sheet.")

    header_row = _find_report_header_row(uploaded, "Exceptions")
    uploaded.seek(0)
    exc = pd.read_excel(uploaded, sheet_name="Exceptions", header=header_row)

    if "Status" not in exc.columns or "Store Code" not in exc.columns:
        raise ValueError("The Exceptions sheet does not contain Store Code / Status columns.")

    exc["Status"] = exc["Status"].astype(str).str.strip()
    exc = exc[
        exc["Status"].str.fullmatch("Missing D365", case=False, na=False)
    ].copy()

    if exc.empty:
        return _empty_master()

    stores = pd.DataFrame()
    stores["Store Code"] = exc["Store Code"].map(_clean_code)
    stores["Store Name"] = (
        exc["Store Name"].fillna("").astype(str).str.strip()
        if "Store Name" in exc.columns
        else ""
    )
    stores["To Email"] = ""
    stores["CC Email"] = ""

    stores = stores[stores["Store Code"].ne("")]
    return _normalize_master(stores)


st.title("📧 Store Email Master")
st.caption(
    "Maintain recipient email IDs by Store Code. "
    "This page does not change POS reconciliation or matching."
)

master = _load_master()

with st.expander("1. Load stores automatically from a RetailRecon report", expanded=master.empty):
    st.write(
        "Upload the reconciliation report and this page will pull only the stores "
        "that currently have **Missing D365** transactions. You then enter the To/CC emails once."
    )
    report_upload = st.file_uploader(
        "RetailRecon Reconciliation Report",
        type=["xlsx"],
        key="email_master_report",
    )

    if report_upload is not None:
        try:
            report_stores = _stores_from_reconciliation_report(report_upload)
            if report_stores.empty:
                st.warning("No Missing D365 stores were found in this report.")
            else:
                existing = master.set_index("Store Code") if not master.empty else pd.DataFrame()
                for idx, row in report_stores.iterrows():
                    code = row["Store Code"]
                    if not master.empty and code in existing.index:
                        report_stores.at[idx, "To Email"] = str(existing.loc[code, "To Email"] or "")
                        report_stores.at[idx, "CC Email"] = str(existing.loc[code, "CC Email"] or "")
                        if not str(report_stores.at[idx, "Store Name"]).strip():
                            report_stores.at[idx, "Store Name"] = str(existing.loc[code, "Store Name"] or "")

                # Keep existing master rows and add new stores from report.
                master = _normalize_master(pd.concat([master, report_stores], ignore_index=True))
                st.success(
                    f"Loaded Missing D365 stores from the report. "
                    f"Email Master now has {len(master)} store record(s)."
                )
        except Exception as e:
            st.error(f"Could not read the reconciliation report: {e}")

with st.expander("2. Or upload an existing Store Email Master", expanded=False):
    master_upload = st.file_uploader(
        "Upload Store Email Master",
        type=["csv", "xlsx", "xls"],
        key="email_master_file",
        help="Columns: Store Code, Store Name, To Email, CC Email",
    )
    if master_upload is not None:
        try:
            if master_upload.name.lower().endswith(".csv"):
                incoming = pd.read_csv(master_upload, dtype=str).fillna("")
            else:
                incoming = pd.read_excel(master_upload, dtype=str).fillna("")
            incoming = _normalize_master(incoming)
            if incoming.empty:
                st.warning("No valid Store Code rows were found.")
            else:
                master = incoming
                st.success(f"Loaded {len(master)} store email record(s).")
        except Exception as e:
            st.error(f"Could not read the Store Email Master: {e}")

st.subheader("Store Email Master")

edited = st.data_editor(
    master,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "Store Code": st.column_config.TextColumn("Store Code", required=True),
        "Store Name": st.column_config.TextColumn("Store Name"),
        "To Email": st.column_config.TextColumn("To Email"),
        "CC Email": st.column_config.TextColumn("CC Email"),
    },
    key="store_email_master_editor_v2",
)

cleaned = _normalize_master(edited)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("💾 SAVE EMAIL MASTER", use_container_width=True):
        _save_master(cleaned)
        st.success(
            f"Saved {len(cleaned)} store record(s) to {MASTER_PATH.as_posix()}."
        )

with c2:
    st.download_button(
        "⬇️ DOWNLOAD EMAIL MASTER CSV",
        cleaned.to_csv(index=False).encode("utf-8-sig"),
        "Store_Email_Master.csv",
        mime="text/csv",
        use_container_width=True,
    )

with c3:
    missing_count = (
        int(cleaned["To Email"].astype(str).str.strip().eq("").sum())
        if not cleaned.empty else 0
    )
    st.metric("Stores Missing To Email", missing_count)

if cleaned.empty:
    st.info(
        "No store email records yet. Upload a RetailRecon report above to create the store list automatically."
    )
else:
    missing = cleaned[cleaned["To Email"].astype(str).str.strip().eq("")]
    if not missing.empty:
        st.warning("Please add a To Email for these stores:")
        st.dataframe(
            missing[["Store Code", "Store Name"]],
            use_container_width=True,
            hide_index=True,
        )

st.caption(
    "For permanent deployment, keep data/store_email_master.csv in your repository "
    "or upload/download the master when needed."
)

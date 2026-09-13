
from __future__ import annotations

import re
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Missing D365 Follow-Up", page_icon="📨", layout="wide")

MASTER_PATH = Path("data/store_email_master.csv")


def _mask_pan(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if "X" in s.upper() or "*" in s:
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 12:
        return digits[:6] + ("X" * max(0, len(digits)-10)) + digits[-4:]
    return s


def _num(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        return float(str(v).replace(",", "").replace("SAR", "").strip())
    except Exception:
        return 0.0


def _clean_id(v):
    """Str-ify an ID-like value without leaving a spurious '.0' on it.

    Excel/pandas reads a whole-numbers-only column (Store Code, Terminal
    ID, ...) as float64, so a naive str(v) turns 615 into "615.0". Left
    alone, that breaks the Store Code merge against the Store Email
    Master below (whose Store Code column is plain string "615") -- every
    row would silently fail to match and come out with no email address,
    even after the header-row bug is fixed.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        return s[:-2]
    return s


def _read_report_sheet_with_real_header(file, sheet, required_col="Store Code", max_scan_rows=10):
    """
    RetailRecon's exported reports (see report_export.py's `startrow=`
    on each sheet's to_excel call) write a title row and a
    "Generated ... | N row(s)" row before the real header -- not row 0.
    Reading naively with pd.read_excel(file, sheet_name=sheet) (default
    header=0) silently produces a dataframe whose real column names never
    appear (they show up as "Unnamed: N" instead, with the actual header
    text buried as a data value a couple of rows down). That doesn't
    raise -- every column lookup below just returns blank/zero for every
    row instead, which is exactly the all-blank CSV this page was
    producing.

    This scans the first few rows for the real header (identified by
    `required_col`) instead of assuming a fixed row number, so it keeps
    working even if report_export.py's row layout changes.
    """
    raw = pd.read_excel(file, sheet_name=sheet, header=None)
    header_row = None
    for i in range(min(max_scan_rows, len(raw))):
        if required_col in raw.iloc[i].astype(str).str.strip().tolist():
            header_row = i
            break
    if header_row is None:
        return pd.DataFrame()
    df = raw.iloc[header_row + 1:].copy()
    df.columns = raw.iloc[header_row].tolist()
    return df.reset_index(drop=True)


def _report_date(v):
    """POS Date in the exported Exceptions sheet comes through as a raw
    Excel serial number (e.g. 46266.0), not a real date. Handing that
    straight to pd.to_datetime() downstream (build_email() below) is
    silently misread as a Unix timestamp in nanoseconds -- it produces a
    garbage 1970-something date, not the real 2026 date, with no error to
    flag it. Interpret it against Excel's actual epoch instead.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    try:
        return pd.to_datetime(float(v), unit="D", origin="1899-12-30")
    except (TypeError, ValueError):
        return pd.to_datetime(v, errors="coerce")


def load_master():
    if not MASTER_PATH.exists():
        return pd.DataFrame(columns=["Store Code", "Store Name", "To Email", "CC Email"])
    try:
        df = pd.read_csv(MASTER_PATH, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=["Store Code", "Store Name", "To Email", "CC Email"])
    for c in ["Store Code", "Store Name", "To Email", "CC Email"]:
        if c not in df.columns:
            df[c] = ""
    df["Store Code"] = df["Store Code"].astype(str).str.strip()
    return df[["Store Code", "Store Name", "To Email", "CC Email"]]


def build_queue_from_unmatched_pos(up):
    if up is None or len(up) == 0:
        return pd.DataFrame()

    d = up.copy()

    # This page is ONLY for final Missing D365 transactions.
    status_col = None
    for c in ["Exception Status", "Status", "Reason"]:
        if c in d.columns:
            status_col = c
            if d[c].astype(str).str.contains("Missing D365", case=False, na=False).any():
                break

    if status_col:
        mask = d[status_col].astype(str).str.fullmatch("Missing D365", case=False, na=False)
        d = d[mask].copy()

    if d.empty:
        return pd.DataFrame()

    def g(row, *cols):
        for c in cols:
            if c in row.index:
                v = row.get(c)
                if not (v is None or (isinstance(v, float) and pd.isna(v))):
                    return v
        return ""

    rows = []
    for _, r in d.iterrows():
        rows.append({
            "Store Code": str(g(r, "POS Store", "Store Code")).strip(),
            "Store Name": str(g(r, "Store Name", "POS Store Name")).strip(),
            "Payment Type": str(g(r, "POS Payment", "Payment Type")).strip(),
            "Transaction Date": g(r, "POS Date", "Transaction Date"),
            "Transaction Time": str(g(r, "Transaction Time")).strip(),
            "Value of Sales": _num(g(r, "POS Amount", "Value of Sales")),
            "Card Number": _mask_pan(g(r, "Card Number")),
            "Authorization Code": str(g(r, "Auth Code", "Provider Reference")).strip(),
            "Terminal ID": str(g(r, "Terminal ID")).strip(),
            "Source": str(g(r, "Source File", "Source")).strip(),
            "Follow-Up Status": "Open - D365 Entry Not Posted",
        })
    return pd.DataFrame(rows)


def load_queue_from_report(file):
    if file is None:
        return pd.DataFrame()
    try:
        xl = pd.ExcelFile(file)
        sheet = "Exceptions" if "Exceptions" in xl.sheet_names else xl.sheet_names[0]
        df = _read_report_sheet_with_real_header(file, sheet)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # Direct exported-report fallback.
    if "Status" in df.columns:
        df = df[df["Status"].astype(str).str.fullmatch("Missing D365", case=False, na=False)].copy()
    if df.empty:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "Store Code": _clean_id(r.get("Store Code", "")),
            "Store Name": str(r.get("Store Name", "") or "").strip(),
            "Payment Type": str(r.get("POS Tender", "") or "").strip(),
            "Transaction Date": _report_date(r.get("POS Date", "")),
            "Transaction Time": str(r.get("Transaction Time", "") or "").strip(),
            "Value of Sales": _num(r.get("POS Total", 0)),
            "Card Number": _mask_pan(r.get("Card Number", "")),
            "Authorization Code": str(r.get("Auth Code", "") or "").strip(),
            "Terminal ID": _clean_id(r.get("Terminal ID", "")),
            "Source": str(r.get("Source", "") or "").strip(),
            "Follow-Up Status": "Open - D365 Entry Not Posted",
        })
    return pd.DataFrame(rows)


def build_email(group):
    store = str(group.iloc[0]["Store Code"])
    name = str(group.iloc[0].get("Store Name", "") or "").strip()
    label = f"{store} - {name}" if name else store
    subject = f"Follow-Up: Amount Received but Entry Not Posted ({label})"

    lines = [
        "Dear Team,",
        "",
        "Kindly find the transaction details below for your reference.",
        "",
        "We have received the amount; however, the corresponding entry has not yet been posted in the system.",
        "",
        "Please check and ensure that the entry is updated by end of day today.",
        "",
    ]
    for _, r in group.iterrows():
        dt = pd.to_datetime(r.get("Transaction Date"), errors="coerce")
        date_txt = dt.strftime("%d-%b-%Y") if pd.notna(dt) else str(r.get("Transaction Date", "") or "")
        lines.append(
            f"{r.get('Payment Type','')} | {date_txt} {r.get('Transaction Time','')} | "
            f"SAR {float(r.get('Value of Sales',0) or 0):,.2f} | "
            f"Card {r.get('Card Number','')} | Auth {r.get('Authorization Code','')}"
        )
    lines += [
        "",
        f"Total SAR: {group['Value of Sales'].fillna(0).astype(float).sum():,.2f}",
        "",
        "Thank you for your prompt attention.",
        "",
        "Kind regards,",
        "Srinivasa Ramappa",
    ]
    return subject, "\n".join(lines)


st.title("📨 Missing D365 Follow-Up")
st.caption(
    "Follow-up control for Missing D365 transactions only. "
    "This page does not modify the reconciliation engine."
)

queue = pd.DataFrame()

# Preferred source: same-session POS reconciliation output.
if "unmatched_pos" in st.session_state:
    queue = build_queue_from_unmatched_pos(st.session_state.get("unmatched_pos"))

if queue.empty:
    st.info(
        "No Missing D365 data is currently available in this session. "
        "Run POS Reconciliation first, or upload a reconciliation report below."
    )
    report = st.file_uploader(
        "Upload RetailRecon Reconciliation Report",
        type=["xlsx"],
        key="missing_d365_report_upload",
    )
    if report is not None:
        queue = load_queue_from_report(report)

if queue.empty:
    st.stop()

master = load_master()
if not master.empty:
    queue["Store Code"] = queue["Store Code"].astype(str).str.strip()
    queue = queue.merge(
        master,
        how="left",
        on="Store Code",
        suffixes=("", "_EmailMaster"),
    )
    if "Store Name_EmailMaster" in queue.columns:
        queue["Store Name"] = queue["Store Name"].where(
            queue["Store Name"].astype(str).str.strip().ne(""),
            queue["Store Name_EmailMaster"].fillna("")
        )
        queue = queue.drop(columns=["Store Name_EmailMaster"])
else:
    queue["To Email"] = ""
    queue["CC Email"] = ""

for c in ["To Email", "CC Email"]:
    if c not in queue.columns:
        queue[c] = ""

c1, c2, c3, c4 = st.columns(4)
c1.metric("Missing D365 Transactions", len(queue))
c2.metric("Total Value", f"SAR {queue['Value of Sales'].fillna(0).astype(float).sum():,.2f}")
c3.metric("Stores", queue["Store Code"].astype(str).nunique())
c4.metric("Missing Email IDs", int(queue["To Email"].fillna("").astype(str).str.strip().eq("").sum()))

st.dataframe(
    queue[
        [
            "Store Code", "Store Name", "Payment Type",
            "Transaction Date", "Transaction Time", "Value of Sales",
            "Card Number", "Authorization Code", "Terminal ID",
            "To Email", "CC Email", "Follow-Up Status", "Source"
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

missing_mail = queue[queue["To Email"].fillna("").astype(str).str.strip().eq("")]
if not missing_mail.empty:
    st.warning(
        "Some Missing D365 transactions do not have a recipient email. "
        "Add the store email on the Store Email Master page."
    )

st.divider()
st.subheader("Prepare Follow-Up Email")

store_options = sorted(queue["Store Code"].astype(str).unique())
selected_store = st.selectbox("Select Store", store_options)

store_rows = queue[queue["Store Code"].astype(str).eq(str(selected_store))].copy()

to_email = str(store_rows.iloc[0].get("To Email", "") or "")
cc_email = str(store_rows.iloc[0].get("CC Email", "") or "")

subject, body = build_email(store_rows)

st.text_input("To", value=to_email, key="missing_d365_to")
st.text_input("CC", value=cc_email, key="missing_d365_cc")
st.text_input("Subject", value=subject, key="missing_d365_subject")
st.text_area("Email Body", value=body, height=350, key="missing_d365_body")

st.download_button(
    "⬇️ DOWNLOAD MISSING D365 FOLLOW-UP CSV",
    queue.to_csv(index=False).encode("utf-8-sig"),
    "Missing_D365_Follow_Up.csv",
    mime="text/csv",
    use_container_width=True,
)

st.caption(
    "Email sending is intentionally not enabled yet. First validate the Store Email Master "
    "and prepared recipients. Sending can then be added as a separate controlled feature."
)

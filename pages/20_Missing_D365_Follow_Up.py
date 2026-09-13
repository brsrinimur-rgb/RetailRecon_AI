
from __future__ import annotations

import csv
import io
import re
import json
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Missing D365 Follow-Up", page_icon="📨", layout="wide")

MASTER_PATH = Path("data/store_email_master.csv")


def _clean_code(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _report_date(v):
    """POS Date in the exported Exceptions sheet comes through as a raw
    Excel serial number (e.g. 46266.0), not a real date. Handing that
    straight to pd.to_datetime() downstream (_build_email() below) is
    silently misread as a Unix timestamp in nanoseconds -- it produces a
    garbage 1970-something date, not the real 2026 date, with no error
    raised to flag it. Interpret it against Excel's actual epoch instead.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    try:
        return pd.to_datetime(float(v), unit="D", origin="1899-12-30")
    except (TypeError, ValueError):
        return pd.to_datetime(v, errors="coerce")


def _norm_ref(v) -> str:
    """
    Normalize authorization/reference values for comparison only.

    Important:
    - Pure numeric auth codes are compared after removing leading zeros.
      Example: 016934 == 16934.
    - Alphanumeric references keep their letters/digits, only punctuation/spaces are removed.
      Example: ASA-26090700001792 == ASA26090700001792.
    - Original values are never overwritten in the displayed/exported data.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""

    s = str(v).strip().upper()

    # Excel often converts numeric codes to strings like "16934.0".
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]

    s = re.sub(r"[^A-Z0-9]", "", s)

    if s.isdigit():
        # Strip leading zeros for comparison only; keep "0" if all zeros.
        s = s.lstrip("0") or "0"

    return s


def _num(v) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        s = str(v).replace(",", "").replace("SAR", "").strip()
        s = re.sub(r"[^\d\.\-\(\)]", "", s)
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return float(s)
    except Exception:
        return 0.0



def _format_transaction_time(v) -> str:
    """
    Format POS transaction time for display only.

    Handles:
    - numeric HHMMSS values from Excel/POS, e.g. 222914.0 -> 22:29:14
    - shorter numeric values with leading-zero padding, e.g. 91503 -> 09:15:03
    - Excel time fractions, e.g. 0.5 -> 12:00:00
    - datetime/time-like strings already containing colons

    This function does not participate in reconciliation matching.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""

    if hasattr(v, "strftime"):
        try:
            return v.strftime("%H:%M:%S")
        except Exception:
            pass

    s = str(v).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return ""

    if ":" in s:
        m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2))
            ss = int(m.group(3) or 0)
            if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                return f"{hh:02d}:{mm:02d}:{ss:02d}"
        return s

    try:
        fv = float(s)
        if 0 <= fv < 1 and "." in s:
            total_seconds = int(round(fv * 24 * 60 * 60)) % (24 * 60 * 60)
            hh = total_seconds // 3600
            mm = (total_seconds % 3600) // 60
            ss = total_seconds % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
    except Exception:
        pass

    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]

    digits = re.sub(r"\D", "", s)
    if 1 <= len(digits) <= 6:
        digits = digits.zfill(6)
        hh, mm, ss = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"

    return s


def _mask_pan(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if "X" in s.upper() or "*" in s:
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 12:
        return digits[:6] + ("X" * max(0, len(digits) - 10)) + digits[-4:]
    return s


def _find_col(df: pd.DataFrame, aliases: list[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    lookup = {
        re.sub(r"[^A-Z0-9]", "", str(c).upper()): c
        for c in df.columns
    }
    for a in aliases:
        k = re.sub(r"[^A-Z0-9]", "", a.upper())
        if k in lookup:
            return lookup[k]
    return None


def _find_report_header_row(uploaded, sheet_name: str = "Exceptions") -> int:
    uploaded.seek(0)
    preview = pd.read_excel(uploaded, sheet_name=sheet_name, header=None, nrows=12)
    for i, row in preview.iterrows():
        vals = {str(v).strip() for v in row.tolist() if pd.notna(v)}
        if "Store Code" in vals and "Status" in vals and "POS Total" in vals:
            return int(i)
    raise ValueError(
        "Could not find the real Exceptions header row. "
        "Expected Store Code, POS Total and Status."
    )


def _load_missing_d365_from_report(uploaded) -> pd.DataFrame:
    uploaded.seek(0)
    xls = pd.ExcelFile(uploaded)
    if "Exceptions" not in xls.sheet_names:
        raise ValueError("The workbook does not contain an Exceptions sheet.")

    header_row = _find_report_header_row(uploaded, "Exceptions")
    uploaded.seek(0)
    exc = pd.read_excel(uploaded, sheet_name="Exceptions", header=header_row)

    required = ["Store Code", "Auth Code", "POS Total", "POS Tender", "Status"]
    missing = [c for c in required if c not in exc.columns]
    if missing:
        raise ValueError(f"Exceptions sheet is missing required columns: {missing}")

    exc["Status"] = exc["Status"].astype(str).str.strip()
    exc = exc[
        exc["Status"].str.fullmatch("Missing D365", case=False, na=False)
    ].copy()

    if exc.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "Store Code": exc["Store Code"].map(_clean_code),
        "Store Name": (
            exc["Store Name"].fillna("").astype(str).str.strip()
            if "Store Name" in exc.columns else ""
        ),
        "Payment Type": exc["POS Tender"].fillna("").astype(str).str.strip(),
        "Transaction Date": (
            exc["POS Date"].map(_report_date) if "POS Date" in exc.columns else ""
        ),
        "Transaction Time": (
            exc["Transaction Time"].map(_format_transaction_time)
            if "Transaction Time" in exc.columns else ""
        ),
        "Value of Sales": exc["POS Total"].map(_num),
        "Card Number": (
            exc["Card Number"].map(_mask_pan)
            if "Card Number" in exc.columns else ""
        ),
        "Authorization Code": exc["Auth Code"].fillna("").astype(str).str.strip(),
        "Terminal ID": (
            exc["Terminal ID"].map(_clean_code)
            if "Terminal ID" in exc.columns else ""
        ),
        "Source": (
            exc["Source"].fillna("").astype(str).str.strip()
            if "Source" in exc.columns else ""
        ),
        "Follow-Up Status": "Open - D365 Entry Not Posted",
    })

    out = out[out["Store Code"].ne("")].reset_index(drop=True)
    return out


def _read_csv_with_sniffer(uploaded) -> pd.DataFrame:
    uploaded.seek(0)
    raw = uploaded.read()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = str(raw)

    sample = text[:50000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return pd.DataFrame()

    # Find the most likely header row.
    best_i = 0
    best_score = -1
    keywords = {
        "AUTH", "AUTHCODE", "AUTHORIZATIONCODE", "AMOUNT", "TRANSACTIONAMOUNT",
        "CARDNUMBER", "PAN", "MASKEDPAN", "TRANSACTIONTIME", "TXNTIME",
        "TERMINALID", "TID"
    }

    for i, row in enumerate(rows[:25]):
        norm = {
            re.sub(r"[^A-Z0-9]", "", str(v).upper())
            for v in row if str(v).strip()
        }
        score = len(norm.intersection(keywords))
        if score > best_score:
            best_score = score
            best_i = i

    header = rows[best_i]
    data = rows[best_i + 1:]
    width = len(header)
    clean_rows = [(r + [""] * width)[:width] for r in data]
    return pd.DataFrame(clean_rows, columns=header)


def _read_raw_provider(uploaded) -> pd.DataFrame:
    """
    Read original POS/provider files for follow-up enrichment only.

    UNITED_LUXURY transaction reports are multi-sheet workbooks
    (typically Details_mada and Details_CC). The previous implementation
    read only the workbook's first/default sheet, which could miss the real
    transaction rows and leave Card Number / Transaction Time blank.

    This scans every Excel sheet, detects the transaction header separately,
    and combines all usable sheets. It does not alter reconciliation logic.
    """
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return _read_csv_with_sniffer(uploaded)

    uploaded.seek(0)
    xls = pd.ExcelFile(uploaded)

    aliases = {
        "AUTH", "AUTHCODE", "AUTHORIZATIONCODE", "TRANSAPPROVALCD",
        "AMOUNT", "TRANSACTIONAMOUNT", "GROSSAMOUNT", "VALUEOFSALES",
        "CARDNUMBER", "PAN", "MASKEDPAN", "TRANSACTIONTIME", "TXNTIME",
        "TERMINALID", "TID"
    }

    frames = []

    for sheet_name in xls.sheet_names:
        try:
            raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        except Exception:
            continue

        if raw.empty:
            continue

        best_i = 0
        best_score = -1

        for i in range(min(25, len(raw))):
            norm = {
                re.sub(r"[^A-Z0-9]", "", str(v).upper())
                for v in raw.iloc[i].tolist() if pd.notna(v)
            }
            score = len(norm.intersection(aliases))
            if score > best_score:
                best_score = score
                best_i = i

        # Avoid cover/summary sheets that do not contain transaction fields.
        if best_score < 2:
            continue

        try:
            part = pd.read_excel(xls, sheet_name=sheet_name, header=best_i)
        except Exception:
            continue

        if part.empty:
            continue

        part["_RAW_SHEET"] = sheet_name
        frames.append(part)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True, sort=False)


def _enrich_card_and_time(queue: pd.DataFrame, raw_files) -> tuple[pd.DataFrame, int]:
    if queue.empty or not raw_files:
        return queue, 0

    frames = []
    for f in raw_files:
        try:
            df = _read_raw_provider(f)
            if not df.empty:
                df["_RAW_SOURCE"] = f.name
                frames.append(df)
        except Exception:
            continue

    if not frames:
        return queue, 0

    q = queue.copy()
    enriched_count = 0

    auth_aliases = [
        "Auth Code", "Authorization Code", "Auth", "Trans Approval Cd",
        "Reference", "RRN", "reference_order", "reference_transaction",
        "Order Number", "Payment ID", "tr_arf"
    ]
    amount_aliases = [
        "Amount", "Transaction Amount", "Gross Amount", "Value of Sales",
        "Captured Amount", "Settlement Amount", "POS Amount", "Total Amount"
    ]
    terminal_aliases = ["Terminal ID", "TID", "Terminal"]
    card_aliases = ["Card Number", "Masked Card Number", "PAN", "Masked PAN", "Card No", "CardNumber"]
    time_aliases = ["Transaction Time", "Txn Time", "Trans Time", "Time", "TransactionTime"]

    for idx, qr in q.iterrows():
        q_auth = _norm_ref(qr.get("Authorization Code"))
        q_amt = round(_num(qr.get("Value of Sales")), 2)
        q_terminal = str(qr.get("Terminal ID", "") or "").strip()
        q_source = str(qr.get("Source", "") or "").strip()

        all_candidates = []

        for raw in frames:
            auth_col = _find_col(raw, auth_aliases)
            amt_col = _find_col(raw, amount_aliases)
            if not auth_col or not amt_col:
                continue

            terminal_col = _find_col(raw, terminal_aliases)
            card_col = _find_col(raw, card_aliases)
            time_col = _find_col(raw, time_aliases)

            work = raw.copy()
            auth_series = work[auth_col].map(_norm_ref)
            amt_series = work[amt_col].map(lambda x: round(_num(x), 2))
            cand = work[auth_series.eq(q_auth) & amt_series.eq(q_amt)].copy()

            # Prefer the exact source filename if report Source is available.
            if not cand.empty and q_source:
                source_name = str(raw["_RAW_SOURCE"].iloc[0])
                if source_name == q_source:
                    cand["_SOURCE_PRIORITY"] = 0
                else:
                    cand["_SOURCE_PRIORITY"] = 1
            else:
                cand["_SOURCE_PRIORITY"] = 1

            # Terminal is a supporting discriminator only.
            if not cand.empty and q_terminal and terminal_col:
                exact_term = cand[
                    cand[terminal_col].astype(str).str.strip().eq(q_terminal)
                ]
                if len(exact_term) == 1:
                    cand = exact_term

            if len(cand) == 1:
                row = cand.iloc[0]
                all_candidates.append({
                    "priority": int(row.get("_SOURCE_PRIORITY", 1)),
                    "card": _mask_pan(row.get(card_col)) if card_col else "",
                    "time": _format_transaction_time(row.get(time_col)) if time_col else "",
                })

        if not all_candidates:
            continue

        best_priority = min(x["priority"] for x in all_candidates)
        best = [x for x in all_candidates if x["priority"] == best_priority]

        # Do not guess when multiple candidate files disagree.
        unique_pairs = {(x["card"], x["time"]) for x in best}
        if len(unique_pairs) != 1:
            continue

        card, txn_time = next(iter(unique_pairs))
        if card:
            q.at[idx, "Card Number"] = card
        if txn_time:
            q.at[idx, "Transaction Time"] = txn_time
        if card or txn_time:
            enriched_count += 1

    return q, enriched_count


def _load_master() -> pd.DataFrame:
    if not MASTER_PATH.exists():
        return pd.DataFrame(columns=["Store Code", "Store Name", "To Email", "CC Email"])
    try:
        m = pd.read_csv(MASTER_PATH, dtype=str).fillna("")
    except Exception:
        return pd.DataFrame(columns=["Store Code", "Store Name", "To Email", "CC Email"])

    for c in ["Store Code", "Store Name", "To Email", "CC Email"]:
        if c not in m.columns:
            m[c] = ""
    m["Store Code"] = m["Store Code"].map(_clean_code)
    return m[["Store Code", "Store Name", "To Email", "CC Email"]]


def _build_email(group: pd.DataFrame) -> tuple[str, str]:
    store = str(group.iloc[0]["Store Code"])
    store_name = str(group.iloc[0].get("Store Name", "") or "").strip()
    label = f"{store} - {store_name}" if store_name else store
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
        date_text = dt.strftime("%d-%b-%Y") if pd.notna(dt) else str(r.get("Transaction Date", "") or "")
        lines.append(
            f"{r.get('Payment Type','')} | {date_text} {_format_transaction_time(r.get('Transaction Time',''))} | "
            f"SAR {float(r.get('Value of Sales',0) or 0):,.2f} | "
            f"Card {r.get('Card Number','')} | Auth {r.get('Authorization Code','')}"
        )

    lines.extend([
        "",
        f"Total SAR: {group['Value of Sales'].fillna(0).astype(float).sum():,.2f}",
        "",
        "Thank you for your prompt attention.",
        "",
        "Kind regards,",
        "Srinivasa Ramappa",
    ])
    return subject, "\n".join(lines)



def _clean_api_key(value: str) -> str:
    """
    Normalize a Resend API key loaded from Streamlit Secrets.

    Handles accidental leading/trailing spaces, embedded line breaks,
    and a second layer of quotes copied into the secret value.
    The cleaned key is never displayed.
    """
    if value is None:
        return ""
    key = str(value).strip()

    # If a user accidentally saved literal wrapping quotes as part of the value.
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {'"', "'"}:
        key = key[1:-1].strip()

    # API keys must not contain whitespace.
    key = re.sub(r"\s+", "", key)
    return key


def _key_diagnostics(key: str) -> dict:
    """Return safe diagnostics without exposing the secret."""
    cleaned = _clean_api_key(key)
    return {
        "loaded": bool(cleaned),
        "starts_re": cleaned.startswith("re_"),
        "length": len(cleaned),
        "fingerprint": hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:10] if cleaned else "",
    }


def _split_emails(value: str) -> list[str]:
    """Split semicolon/comma-separated recipient lists and remove blanks/duplicates."""
    if not value:
        return []
    parts = re.split(r"[;,]", str(value))
    out = []
    seen = set()
    for part in parts:
        email = part.strip()
        if not email:
            continue
        key = email.lower()
        if key not in seen:
            seen.add(key)
            out.append(email)
    return out


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(value).strip()))


def _send_resend_email(
    api_key: str,
    from_name: str,
    from_email: str,
    to_emails: list[str],
    cc_emails: list[str],
    subject: str,
    body: str,
) -> dict:
    """
    Send one selected-store follow-up email through Resend.
    Uses Python standard library only, so requirements.txt does not need a new package.
    """
    payload = {
        "from": f"{from_name} <{from_email}>",
        "to": to_emails,
        "subject": subject,
        "text": body,
    }
    if cc_emails:
        payload["cc"] = cc_emails

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_clean_api_key(api_key)}",
            "Content-Type": "application/json",
            "User-Agent": "RetailRecon-AI/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend rejected the email (HTTP {e.code}): {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not connect to Resend: {e.reason}") from e


st.title("📨 Missing D365 Follow-Up")
st.caption(
    "This page reads only final **Missing D365** exceptions from the RetailRecon report. "
    "It does not change matching, mappings, or reconciliation totals."
)

st.subheader("1. Load RetailRecon reconciliation report")
report_upload = st.file_uploader(
    "RetailRecon Reconciliation Report",
    type=["xlsx"],
    key="missing_d365_report_v3",
)

if report_upload is None:
    st.info(
        "Upload the latest RetailRecon reconciliation report. "
        "The page will read the real Exceptions header automatically."
    )
    st.stop()

try:
    queue = _load_missing_d365_from_report(report_upload)
except Exception as e:
    st.error(f"Could not read the reconciliation report: {e}")
    st.stop()

if queue.empty:
    st.success("No Missing D365 transactions were found in this report.")
    st.stop()

st.success(f"Loaded {len(queue)} Missing D365 transaction(s) from the report.")

st.subheader("2. Card Number / Transaction Time")
st.caption(
    "The reconciliation report contains the Missing D365 transaction, but it does not carry "
    "Card Number or Transaction Time. Upload the ORIGINAL POS transaction reports listed in the "
    "Source column. This page will enrich Card Number / Transaction Time using Source + "
    "Authorization Code + exact Amount (+ Terminal ID when available). "
    "Numeric auth codes are compared ignoring leading zeros, e.g. 016934 = 16934. "
    "This is follow-up data only; it is never used for reconciliation matching."
)

raw_uploads = st.file_uploader(
    "Original POS / Provider Files (optional, multiple files)",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    key="missing_d365_raw_provider_v3",
)

if raw_uploads:
    queue, enriched_count = _enrich_card_and_time(queue, raw_uploads)
    if enriched_count:
        st.success(
            f"Card Number / Transaction Time enriched for {enriched_count} Missing D365 transaction(s)."
        )
    else:
        st.warning(
            "No unique Card Number / Transaction Time matches were found in the uploaded raw files. "
            "The Missing D365 queue remains unchanged."
        )

master = _load_master()

if not master.empty:
    queue = queue.merge(
        master,
        how="left",
        on="Store Code",
        suffixes=("", "_Master"),
    )
    if "Store Name_Master" in queue.columns:
        queue["Store Name"] = queue["Store Name"].where(
            queue["Store Name"].astype(str).str.strip().ne(""),
            queue["Store Name_Master"].fillna("")
        )
        queue = queue.drop(columns=["Store Name_Master"])
else:
    queue["To Email"] = ""
    queue["CC Email"] = ""

for c in ["To Email", "CC Email"]:
    if c not in queue.columns:
        queue[c] = ""
    queue[c] = queue[c].fillna("").astype(str).str.strip()

st.subheader("3. Missing D365 Follow-Up Queue")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Missing D365 Transactions", len(queue))
c2.metric("Total Value", f"SAR {queue['Value of Sales'].fillna(0).astype(float).sum():,.2f}")
c3.metric("Stores", queue["Store Code"].nunique())
c4.metric(
    "Transactions Missing Recipient",
    int(queue["To Email"].eq("").sum()),
)

display_cols = [
    "Store Code", "Store Name", "Payment Type",
    "Transaction Date", "Transaction Time", "Value of Sales",
    "Card Number", "Authorization Code", "Terminal ID",
    "To Email", "CC Email", "Follow-Up Status", "Source"
]
st.dataframe(
    queue[display_cols],
    use_container_width=True,
    hide_index=True,
)

missing_recipient = queue[queue["To Email"].eq("")]
if not missing_recipient.empty:
    stores_missing = sorted(missing_recipient["Store Code"].astype(str).unique())
    st.warning(
        "Recipient email is missing for Store Code(s): "
        + ", ".join(stores_missing)
        + ". Add them on the Store Email Master page."
    )

st.subheader("4. Prepare Follow-Up Email")

store_options = sorted(queue["Store Code"].astype(str).unique())
selected_store = st.selectbox(
    "Select Store",
    store_options,
    key="missing_d365_selected_store_v4",
)

store_rows = queue[queue["Store Code"].astype(str).eq(str(selected_store))].copy()
to_email = str(store_rows.iloc[0].get("To Email", "") or "")
cc_email = str(store_rows.iloc[0].get("CC Email", "") or "")
subject, body = _build_email(store_rows)

# IMPORTANT:
# Use store-specific widget keys. Streamlit preserves widget state by key;
# the old fixed keys caused Store 601's subject/body to remain visible after
# selecting Store 615. These keys force the prepared email to follow the
# currently selected store while still allowing the user to edit the fields.
store_key = re.sub(r"[^A-Za-z0-9_-]", "_", str(selected_store))

email_to = st.text_input(
    "To",
    value=to_email,
    key=f"missing_d365_to_{store_key}",
)
email_cc = st.text_input(
    "CC",
    value=cc_email,
    key=f"missing_d365_cc_{store_key}",
)
email_subject = st.text_input(
    "Subject",
    value=subject,
    key=f"missing_d365_subject_{store_key}",
)
email_body = st.text_area(
    "Email Body",
    value=body,
    height=360,
    key=f"missing_d365_body_{store_key}",
)

# Final safety validation before any future Send Email action is enabled.
# The current page remains PREPARE-ONLY until an email provider/API is connected.
card_missing = store_rows["Card Number"].fillna("").astype(str).str.strip().eq("").any()
time_missing = store_rows["Transaction Time"].fillna("").astype(str).str.strip().eq("").any()
recipient_missing = not email_to.strip()

if recipient_missing:
    st.warning("Send Email blocked: To Email is missing for the selected store.")
elif card_missing or time_missing:
    missing_fields = []
    if card_missing:
        missing_fields.append("Card Number")
    if time_missing:
        missing_fields.append("Transaction Time")
    st.warning(
        "Send Email blocked: " + " and ".join(missing_fields)
        + " is missing for one or more selected-store transactions."
    )
else:
    st.success(
        "Email validation PASS: selected store, recipient, Card Number, "
        "Transaction Time, Subject and Email Body are ready."
    )

st.download_button(
    "⬇️ DOWNLOAD MISSING D365 FOLLOW-UP CSV",
    queue.to_csv(index=False).encode("utf-8-sig"),
    "Missing_D365_Follow_Up.csv",
    mime="text/csv",
    use_container_width=True,
)


st.subheader("5. Send Follow-Up Email")

# Secrets are kept outside GitHub/source code.
try:
    resend_api_key = _clean_api_key(st.secrets.get("RESEND_API_KEY", ""))
    resend_from_email = str(
        st.secrets.get("RESEND_FROM_EMAIL", "reconciliation@mail.ahenqor.com")
    ).strip()
    resend_from_name = str(
        st.secrets.get("RESEND_FROM_NAME", "RetailRecon AI")
    ).strip()
except Exception:
    resend_api_key = ""
    resend_from_email = "reconciliation@mail.ahenqor.com"
    resend_from_name = "RetailRecon AI"

diag = _key_diagnostics(resend_api_key)

with st.expander("🔐 Resend connection diagnostic", expanded=True):
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("API key loaded", "YES" if diag["loaded"] else "NO")
    d2.metric("Starts with re_", "YES" if diag["starts_re"] else "NO")
    d3.metric("Key length", diag["length"])
    d4.metric("Key fingerprint", diag["fingerprint"] or "—")
    st.caption(
        "The fingerprint is a one-way SHA-256 identifier, not the API key. "
        "It is safe to share if troubleshooting is needed."
    )

to_list = _split_emails(email_to)
cc_list = _split_emails(email_cc)

invalid_to = [x for x in to_list if not _valid_email(x)]
invalid_cc = [x for x in cc_list if not _valid_email(x)]

send_block_reasons = []
if not resend_api_key:
    send_block_reasons.append("RESEND_API_KEY is not configured in Streamlit Secrets")
if not resend_from_email or not _valid_email(resend_from_email):
    send_block_reasons.append("RESEND_FROM_EMAIL is missing or invalid")
if not to_list:
    send_block_reasons.append("To Email is missing")
if invalid_to:
    send_block_reasons.append("Invalid To Email: " + ", ".join(invalid_to))
if invalid_cc:
    send_block_reasons.append("Invalid CC Email: " + ", ".join(invalid_cc))
if card_missing:
    send_block_reasons.append("Card Number is missing")
if time_missing:
    send_block_reasons.append("Transaction Time is missing")
if not email_subject.strip():
    send_block_reasons.append("Subject is missing")
if not email_body.strip():
    send_block_reasons.append("Email Body is missing")

if send_block_reasons:
    st.warning("Email sending is blocked until these checks are fixed:\n- " + "\n- ".join(send_block_reasons))
else:
    st.success(
        f"Ready to send from {resend_from_name} <{resend_from_email}> "
        f"to {', '.join(to_list)}."
    )

    confirm_send = st.checkbox(
        f"I confirm the selected store is {selected_store} and the To/CC recipients are correct.",
        key=f"missing_d365_send_confirm_{store_key}",
    )

    if st.button(
        "📧 SEND EMAIL",
        type="primary",
        use_container_width=True,
        disabled=not confirm_send,
        key=f"missing_d365_send_button_{store_key}",
    ):
        try:
            with st.spinner("Sending email through Resend..."):
                result = _send_resend_email(
                    api_key=resend_api_key,
                    from_name=resend_from_name,
                    from_email=resend_from_email,
                    to_emails=to_list,
                    cc_emails=cc_list,
                    subject=email_subject.strip(),
                    body=email_body,
                )

            resend_id = str(result.get("id", "") or "")
            st.success(
                "Email sent successfully."
                + (f" Resend ID: {resend_id}" if resend_id else "")
            )
            st.session_state[f"missing_d365_last_send_{store_key}"] = {
                "store": str(selected_store),
                "to": to_list,
                "cc": cc_list,
                "subject": email_subject.strip(),
                "resend_id": resend_id,
                "status": "Sent",
            }
        except Exception as e:
            msg = str(e)
            st.error(f"Email was NOT sent. {msg}")
            if "HTTP 401" in msg or "API key is invalid" in msg:
                st.error(
                    "Resend authentication failed. The app is reaching Resend, but the key "
                    "loaded by Streamlit is not accepted. Check the diagnostic above. "
                    "If API key loaded = YES and Starts with re_ = YES, revoke that key in "
                    "Resend, create a brand-new Sending Access key, paste it into Streamlit "
                    "Secrets, Save changes, then REBOOT the Streamlit app before retrying."
                )

last_send = st.session_state.get(f"missing_d365_last_send_{store_key}")
if last_send:
    st.info(
        f"Last send status for Store {last_send['store']}: "
        f"{last_send['status']} | To: {', '.join(last_send['to'])}"
        + (f" | Resend ID: {last_send['resend_id']}" if last_send.get("resend_id") else "")
    )

st.caption(
    "Only the currently selected store is sent. Reconciliation, matching, Card Number "
    "enrichment and Missing D365 logic are unchanged."
)

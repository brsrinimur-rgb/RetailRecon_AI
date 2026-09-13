"""
REGRESSION_V65_MISSING_D365_FOLLOWUP_BULK_SEND.py

Context: after V64 added real email sending, you said you were sending
store by store and wanted to send to all stores in one go instead of
selecting and clicking Send for each one manually.

Added _bulk_send_all(queue, send_fn=_send_email_smtp): loops every distinct
Store Code in the queue, groups that store's Missing D365 rows into one
email (same grouping _build_email() already uses for the single-store
preview), and sends it. A store with no recipient email is recorded as
Skipped rather than treated as an error that stops the batch; a send that
raises (bad credentials, an SMTP rejection, etc.) is recorded as Failed
with the real error message, and the loop continues to the next store
rather than aborting -- one bad store must never block every other
store's email from going out. `send_fn` is swappable purely so this can be
tested against a fake sender instead of opening a real SMTP connection;
the live page always calls it with the real _send_email_smtp.

A new "6. Bulk Send: All Stores" section on the page shows a results table
(Store Code / Status / Detail) after sending, plus a one-line summary
count of sent/skipped/failed. It sits behind the same email-sending gate
as the single-store send (Secrets must be configured) plus its own
separate confirmation checkbox, since a bulk send is a more consequential
action than sending one email at a time.

This test verifies the loop's control flow against a fake sender (three
stores: one with a recipient that sends fine, one with no recipient at
all, one with a recipient whose send is made to fail) and re-confirms
every check from V64 (message construction, _parse_addrs, _smtp_configured
gating) plus the underlying report-parsing fixes from V59-V63 still hold.
"""
import re
import io
import csv
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
import pandas as pd


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")


class _FakeSecrets(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class _FakeSt:
    def __init__(self):
        self.secrets = _FakeSecrets()


st = _FakeSt()

src = open("20_Missing_D365_Follow_Up.py").read()
start = src.index("MASTER_PATH = Path(")
cut = src.index('st.title("📨 Missing D365 Follow-Up")')
ns = {
    "re": re, "io": io, "csv": csv, "Path": Path, "pd": pd, "Optional": Optional,
    "smtplib": smtplib, "EmailMessage": EmailMessage, "st": st,
}
exec(compile(src[start:cut], "page20_v65_logic", "exec"), ns)

_parse_addrs = ns["_parse_addrs"]
_smtp_configured = ns["_smtp_configured"]
_send_email_smtp = ns["_send_email_smtp"]
_bulk_send_all = ns["_bulk_send_all"]
_load_missing_d365_from_report = ns["_load_missing_d365_from_report"]


def _make_report_bytes(exceptions_df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        exceptions_df.to_excel(w, sheet_name="Exceptions", index=False, startrow=3)
        ws = w.sheets["Exceptions"]
        ws["A1"] = "Exceptions"
        ws["A2"] = f"Generated 13-Sep-2026 20:23 | {len(exceptions_df)} exception row(s)"
    buf.seek(0)
    buf.name = "report.xlsx"
    return buf


# --- 1. _bulk_send_all: sends, skips, and failures all handled correctly ---
queue = pd.DataFrame([
    {"Store Code": "615", "Store Name": "Tag Heuer", "Payment Type": "MADA",
     "Transaction Date": pd.Timestamp("2026-09-01"), "Transaction Time": "13:19:11",
     "Value of Sales": 12665.00, "Card Number": "506968XXXXXX5680",
     "Authorization Code": "016934", "To Email": "storeA@x.com;", "CC Email": ""},
    {"Store Code": "640", "Store Name": "", "Payment Type": "MADA",
     "Transaction Date": pd.Timestamp("2026-09-01"), "Transaction Time": "21:25:22",
     "Value of Sales": 2490.00, "Card Number": "506968XXXXXX9769",
     "Authorization Code": "012140", "To Email": "", "CC Email": ""},  # no recipient
    {"Store Code": "601", "Store Name": "", "Payment Type": "MADA",
     "Transaction Date": pd.Timestamp("2026-09-02"), "Transaction Time": "22:29:14",
     "Value of Sales": 45.00, "Card Number": "506968XXXXXX5160",
     "Authorization Code": "002229", "To Email": "storeC@x.com;", "CC Email": ""},  # made to fail
])

calls = []


def _fake_send(to_addr, cc_addr, subject, body):
    calls.append(to_addr)
    if to_addr.startswith("storeC"):
        raise RuntimeError("SmtpClientAuthentication is disabled for the Mailbox")


results = _bulk_send_all(queue, send_fn=_fake_send)
_assert(len(results) == 3, "one result row per distinct store")
_assert(set(calls) == {"storeA@x.com;", "storeC@x.com;"},
        f"a send was attempted for both stores that have a recipient, got {calls}")
_assert(len(calls) == 2, "the store with no recipient at all was never attempted to send")

r615 = results[results["Store Code"] == "615"].iloc[0]
r640 = results[results["Store Code"] == "640"].iloc[0]
r601 = results[results["Store Code"] == "601"].iloc[0]
_assert(r615["Status"] == "Sent", "store with a recipient and a successful send -> Sent")
_assert(r640["Status"] == "Skipped" and r640["Detail"] == "No recipient email",
        "store with no recipient -> Skipped with a clear reason, not an error")
_assert(r601["Status"] == "Failed" and "SmtpClientAuthentication" in r601["Detail"],
        "store whose send raises -> Failed, with the real error message preserved")
_assert(list(results["Store Code"]) == sorted(results["Store Code"]),
        "results are returned in sorted Store Code order")

# One bad/missing store must never stop the batch -- both other stores were still attempted/reported.
_assert(len(results) == 3 and len(calls) == 2,
        "one failing store and one missing-recipient store never blocked attempting the rest of the batch")

# --- 2. carried over from V64: message construction against a mocked SMTP ---
st.secrets["smtp"] = {"username": "u@trafalgarluxurygroup.com", "app_password": "abcd efgh ijkl mnop"}
_assert(_smtp_configured() is True, "SMTP still reads as configured with valid secrets")

mock_calls = {}


class _FakeSMTP:
    def __init__(self, host, port, timeout=None):
        mock_calls["host"], mock_calls["port"] = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        mock_calls["starttls"] = True

    def login(self, user, pw):
        mock_calls["login"] = (user, pw)

    def send_message(self, msg, to_addrs=None):
        mock_calls["msg"], mock_calls["to_addrs"] = msg, to_addrs


ns["smtplib"].SMTP = _FakeSMTP
_send_email_smtp("to1@x.com;", "cc1@x.com;", "Subj", "Body text")
_assert(mock_calls["host"] == "smtp.office365.com" and mock_calls["port"] == 587,
        "single-send path still connects to smtp.office365.com:587")
_assert(mock_calls["login"] == ("u@trafalgarluxurygroup.com", "abcd efgh ijkl mnop"),
        "single-send path still logs in with Secrets credentials")
_assert(mock_calls["to_addrs"] == ["to1@x.com", "cc1@x.com"], "single-send path still combines To + CC correctly")

_assert(_parse_addrs("a@x.com; b@x.com;") == ["a@x.com", "b@x.com"], "_parse_addrs still handles trailing ';'")
_assert(_parse_addrs("") == [], "_parse_addrs('') still []")

# --- 3. report-parsing fixes from V59-V63 are untouched -------------------
exceptions = pd.DataFrame([
    {"Store Code": 615, "Auth Code": "016934", "POS Tender": "MADA", "POS Total": 12665.00,
     "Terminal ID": 55610703, "POS Date": 46266.0, "Status": "Missing D365"},
])
report = _make_report_bytes(exceptions)
q = _load_missing_d365_from_report(report)
_assert(len(q) == 1 and q["Terminal ID"].iloc[0] == "55610703",
        "report parsing and Terminal ID cleanup still hold")
_assert(pd.Timestamp(q["Transaction Date"].iloc[0]).date() == pd.Timestamp("2026-09-01").date(),
        "date fix still holds")

print("\nREGRESSION V65 MISSING D365 FOLLOWUP BULK SEND PASS")

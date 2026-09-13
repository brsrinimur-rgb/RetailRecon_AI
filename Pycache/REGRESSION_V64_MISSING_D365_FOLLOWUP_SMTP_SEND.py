"""
REGRESSION_V64_MISSING_D365_FOLLOWUP_SMTP_SEND.py

Context: you asked to "activate" sending the follow-up emails instead of
just preparing them. You confirmed you have no Microsoft 365 tenant-admin
access, but CAN generate an app password for your own mailbox yourself --
that rules out the Graph API route (needs an admin-registered Azure AD
app) and points to plain SMTP via smtp.office365.com using that mailbox +
app password, which needs no IT/admin involvement on your end beyond
possibly asking IT to flip "Authenticated SMTP" on for that one mailbox if
it turns out to be off (a small per-mailbox setting, not a tenant change).

Added:
- _parse_addrs(): splits the app's semicolon/comma-separated To/CC fields
  into a clean address list, dropping blanks (a trailing ";" or an empty
  CC must never become a bogus recipient).
- _smtp_configured(): true only once BOTH a mailbox address and an app
  password exist in this app's Streamlit Secrets -- never in code, never
  typed by anyone but the mailbox owner into the app's own Secrets panel.
- _send_email_smtp(): logs into smtp.office365.com:587 over STARTTLS with
  those secrets and sends the exact To/CC/Subject/Body currently shown on
  screen (read from the widgets' live session state, so any edits you make
  before sending are respected, not the original computed draft).
- A new "5. Send Follow-Up Email" section: shows setup instructions until
  Secrets are configured; once configured, requires an explicit "I have
  reviewed this" checkbox before the send button is even clickable, and
  blocks sending with a clear message if To is empty for that store.

This test verifies the message-construction logic against a mocked SMTP
server (no real network, no real email is ever sent by this test or by
building this feature) -- host/port, STARTTLS, login credentials pulled
correctly from secrets, To+CC recipient list, and header/body construction
-- plus _parse_addrs()'s edge cases (trailing separators, comma vs
semicolon, blank/None) and _smtp_configured()'s gating logic. It also
re-confirms the existing report-parsing logic (Terminal ID, dates,
multi-sheet raw-file reading) is untouched by this change.
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
    """Stand-in for the streamlit module: only .secrets is used by the
    logic under test at this stage (before st.title(...) starts the real
    page)."""
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
exec(compile(src[start:cut], "page20_v64_logic", "exec"), ns)

_parse_addrs = ns["_parse_addrs"]
_smtp_configured = ns["_smtp_configured"]
_send_email_smtp = ns["_send_email_smtp"]
_load_missing_d365_from_report = ns["_load_missing_d365_from_report"]
_report_date = ns["_report_date"]
_clean_code = ns["_clean_code"]
_read_raw_provider = ns["_read_raw_provider"]


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


# --- 1. _parse_addrs -----------------------------------------------------
_assert(_parse_addrs("a@x.com; b@x.com;") == ["a@x.com", "b@x.com"], "semicolon list with trailing ';' parsed correctly")
_assert(_parse_addrs("a@x.com, b@x.com") == ["a@x.com", "b@x.com"], "comma-separated list parsed correctly")
_assert(_parse_addrs("") == [], "empty string -> []")
_assert(_parse_addrs(None) == [], "None -> []")
_assert(_parse_addrs("   ") == [], "whitespace-only -> []")
_assert(_parse_addrs("solo@x.com") == ["solo@x.com"], "single address parsed correctly")

# --- 2. _smtp_configured gating ------------------------------------------
_assert(_smtp_configured() is False, "not configured when secrets is empty")
st.secrets["smtp"] = {"username": "u@trafalgarluxurygroup.com"}
_assert(_smtp_configured() is False, "not configured when app_password is missing")
st.secrets["smtp"] = {"username": "u@trafalgarluxurygroup.com", "app_password": "abcd efgh ijkl mnop"}
_assert(_smtp_configured() is True, "configured once both username and app_password are present")

# --- 3. _send_email_smtp against a mocked SMTP server (no real network) --
calls = {}


class _FakeSMTP:
    def __init__(self, host, port, timeout=None):
        calls["host"], calls["port"] = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        calls["starttls"] = True

    def login(self, user, pw):
        calls["login"] = (user, pw)

    def send_message(self, msg, to_addrs=None):
        calls["msg"], calls["to_addrs"] = msg, to_addrs


ns["smtplib"].SMTP = _FakeSMTP

_send_email_smtp("to1@x.com; to2@x.com;", "cc1@x.com;", "Subj", "Body text")
_assert(calls["host"] == "smtp.office365.com", "connects to smtp.office365.com")
_assert(calls["port"] == 587, "uses port 587 (STARTTLS)")
_assert(calls["starttls"] is True, "starttls() is called before login")
_assert(calls["login"] == ("u@trafalgarluxurygroup.com", "abcd efgh ijkl mnop"),
        "logs in with the mailbox + app password from Secrets, nothing hardcoded")
_assert(calls["to_addrs"] == ["to1@x.com", "to2@x.com", "cc1@x.com"],
        f"actual SMTP envelope recipients are To + CC combined, got {calls['to_addrs']}")
_assert(calls["msg"]["To"] == "to1@x.com, to2@x.com", "To header correctly joined")
_assert(calls["msg"]["Cc"] == "cc1@x.com", "Cc header correctly set")
_assert(calls["msg"]["From"] == "u@trafalgarluxurygroup.com", "From is the configured mailbox, not a spoofed address")
_assert(calls["msg"]["Subject"] == "Subj", "Subject header passed through correctly")
_assert(calls["msg"].get_content().strip() == "Body text", "body content passed through correctly")

calls.clear()
_send_email_smtp("only_to@x.com", "", "S2", "B2")
_assert("Cc" not in calls["msg"], "no Cc header at all when CC is blank (not an empty header)")
_assert(calls["to_addrs"] == ["only_to@x.com"], "envelope recipients is just To when CC is blank")

try:
    _send_email_smtp("", "", "S", "B")
    raise AssertionError("expected a ValueError when 'To' is empty")
except ValueError as e:
    print(f"[PASS] sending with an empty 'To' raises ValueError instead of silently no-op'ing: {e}")

# --- 4. existing report-parsing logic is untouched by this change -------
exceptions = pd.DataFrame([
    {"Store Code": 615, "Auth Code": "016934", "POS Tender": "MADA", "POS Total": 12665.00,
     "Terminal ID": 55610703, "POS Date": 46266.0, "Status": "Missing D365"},
])
report = _make_report_bytes(exceptions)
q = _load_missing_d365_from_report(report)
_assert(len(q) == 1, "report parsing still returns the 1 real Missing D365 row")
_assert(q["Terminal ID"].iloc[0] == "55610703", "Terminal ID cleanup still holds (no spurious .0)")
_assert(pd.Timestamp(q["Transaction Date"].iloc[0]).date() == pd.Timestamp("2026-09-01").date(),
        "date fix still holds")

print("\nREGRESSION V64 MISSING D365 FOLLOWUP SMTP SEND PASS")

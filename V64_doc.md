# V64 — Actual Email Sending Enabled (Microsoft 365 SMTP + App Password)

**Date:** 2026-09-13
**File:** `pages/20_Missing_D365_Follow_Up.py` (built on V63)
**Change:** new "5. Send Follow-Up Email" section — real sending, not just preview
**File added:** `REGRESSION_V64_MISSING_D365_FOLLOWUP_SMTP_SEND.py`

## Why SMTP + app password

You confirmed two things: no admin access to your Microsoft 365 tenant, but you *can* generate an app password for your own mailbox yourself. That rules out the Microsoft Graph API route (needs an admin to register an Azure AD app and grant `Mail.Send`) and points to plain SMTP through `smtp.office365.com` using your mailbox address + an app password — nothing on your end requires IT, beyond a possible one-time ask if your mailbox specifically has "Authenticated SMTP" turned off (see below).

## What was added

- `_parse_addrs()` — splits the app's semicolon/comma-separated To/CC fields into a clean list, dropping blanks so a trailing `;` or an empty CC never becomes a bogus recipient.
- `_smtp_configured()` — true only once **both** a mailbox address and an app password exist in this app's own Streamlit **Secrets**. Never in code, never typed by anyone but the mailbox owner into the app's Secrets panel.
- `_send_email_smtp()` — connects to `smtp.office365.com:587`, STARTTLS, logs in with those secrets, and sends exactly what's currently shown in the To/CC/Subject/Body boxes — read live from the page, so any edits you make before hitting send are respected, not the original auto-generated draft.
- Section **"5. Send Follow-Up Email"**: until Secrets are configured, it shows exact setup instructions and sends nothing. Once configured, sending requires an explicit "I have reviewed this" checkbox before the send button is even clickable, and blocks with a clear error if To is empty for that store.

## How to turn it on

1. Generate an app password for your own mailbox: **account.microsoft.com/security → Advanced security options → App passwords.** No IT/admin action needed for this step.
2. In Streamlit Cloud: open this app → **Manage app → Settings → Secrets**, and add:
   ```toml
   [smtp]
   username = "your.mailbox@trafalgarluxurygroup.com"
   app_password = "xxxx xxxx xxxx xxxx"
   ```
3. Reload the page. Section 5 will switch from setup instructions to a live send button.

**One possible snag, and what it means:** some tenants have "Authenticated SMTP" (SMTP AUTH) turned off *per mailbox* even when app passwords work fine elsewhere. If sending fails with an error mentioning `SmtpClientAuthentication is disabled for the Mailbox`, that's the cause — the app surfaces that message as-is so it's clear what to ask for. The ask to IT in that case is small and specific ("please enable Authenticated SMTP for my mailbox"), not a tenant-wide security change, so it shouldn't need to go through the admin process you said you don't have access to.

## Verification

No real email was sent by building or testing this — I do not have your app password and would not use it even if you shared it here (that belongs only in the app's own Secrets, entered by you). Instead:
- `py_compile` clean.
- New `REGRESSION_V64_MISSING_D365_FOLLOWUP_SMTP_SEND.py` (25 checks): message construction verified against a mocked SMTP server (correct host/port/STARTTLS, correct login credentials pulled from secrets, correct To+CC envelope recipients, correct headers/body, no bogus Cc when blank, a clear error rather than a silent no-op when To is empty), plus `_parse_addrs()` edge cases and `_smtp_configured()` gating, plus a re-check that existing report parsing (Terminal ID, dates) is untouched.

## How to upload

Replace one file (same path):
- `pages/20_Missing_D365_Follow_Up.py`

Optional but recommended:
- `REGRESSION_V64_MISSING_D365_FOLLOWUP_SMTP_SEND.py`

Then add the `[smtp]` Secrets block above before expecting real sends to work.

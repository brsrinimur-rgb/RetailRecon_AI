# RetailRecon AI - Final POS-to-GL Control Center

Run:
1. Install Python 3.10+
2. `python -m pip install -r requirements.txt`
3. `streamlit run Home.py`
4. Open http://localhost:8501

Demo users:
- admin / admin123
- finance / finance123
- maker / maker123
- checker / checker123

Workflow:
D365 Store Tender -> POS/AMEX/Tabby/Tamara/Tap -> Reconciliation -> Bank Settlement ->
Exceptions/Corrections -> Close -> GL Configuration -> Weekly Store JV ->
Finance Approval -> D365 Posting -> Verification -> Late Transaction Adjustment JV.

Core posting gate:
- Status = Matched
- Difference <= SAR 1.00
- Bank Settled = True
- JV Balanced = True
- Finance Approval = APPROVED

JV grouping:
- MADA + VISA + MASTERCARD = CARD
- AMEX, TABBY, TAMARA, TAP = separate groups


## New POS Statement Format Supported
The importer now supports files with columns such as:
terminal_id, merchant_id, account, localdate, time, cardmasked, amount,
tr_arf, scheme, tr_slip, total_amount, posting_date, merchant_name, arn,
payment_type, channel.

Mapping:
- Auth/reference: tr_arf
- POS amount: amount
- Net settlement: total_amount
- Payment/card scheme: scheme/payment_type
- Transaction date: localdate
- Posting date: posting_date
- Terminal: terminal_id
- Merchant: merchant_id
- ARN: arn


## Mandatory regression case
Store 601, 06-Jul-2026, Auth 075304, MasterCard, SAR 1,260.00 must always match
against POS Terminal 55610716 when Store/Date/Auth/Tender/Amount agree.

Exact repeated POS rows caused by overlapping statement uploads are collapsed
to one representative transaction and do not block automatic reconciliation.


## Terminal Mapping Required control
Generic merchant/company names such as UNITED LUXURY CORP are no longer shown as Store Codes.
When a POS row contains a Terminal ID but the terminal is not mapped to a D365 Store Code,
the exception is classified as `Terminal Mapping Required`. After Finance updates the
POS Terminal Master and reruns reconciliation, the mapped Store Code is used automatically.


## POS statement summary/control row filter
ANB and other POS statement footer/control rows are excluded before reconciliation.

Examples excluded:
- Terminal ID = `Sum:`
- `Total`, `Grand Total`, `Subtotal`, `Summary`
- blank/NaN tender + no Auth/Reference + no transaction date

These rows no longer affect Missing D365, exception counts, POS totals, match %, bank settlement,
or JV creation.


## Final correction pack
This build adds:
- POS summary/control-row filtering
- D365 summary/control-row filtering
- Store Mapping Master upload/edit/download
- POS Terminal Master upload/edit/download
- Finance-confirmed payment-code normalization
- Exact overlapping POS duplicate collapse
- Evidence-based matching for all stores/providers
- Provider exception classification:
  - Terminal Mapping Required
  - Store Mapping Required
  - Date Validation Required
  - Duplicate Provider/POS
  - Missing D365
- Existing carry-forward, bank settlement, JV, approval and D365 posting controls remain.

Important: `unmatched_pos` no longer automatically means `Missing D365`.


## Commission Rate Master
Commission validation is now payment-type specific and editable from the application.

Confirmed contract rates:
- MADA: 0.55%
- VISA: 1.55%
- MASTERCARD: 1.55%
- GCC NET: 1.50%
- AMEX: 3.00%
- VAT on commission: 15%

TABBY, TAMARA and TAP currently use `PROVIDER_ACTUAL` mode until their approved
contract rates are entered. Their actual fee from provider files remains visible,
but the system will not falsely label it compliant against an invented rate.

Commission statuses:
- OK
- OVERCHARGED
- UNDERCHARGED
- CONTRACT RATE PENDING
- RATE NOT CONFIGURED


## JV commission correction
JV creation now calculates commission transaction-by-transaction using the editable Commission Rate Master:
MADA 0.55%, VISA 1.55%, MASTERCARD 1.55%, GCC NET 1.50%, AMEX 3.00%, VAT 15%.
TABBY/TAMARA/TAP use provider actual fee until contract rates are configured.

CARD remains grouped as one weekly store JV after each underlying tender is calculated correctly.
The old residual adjustment that could create negative commission has been removed.
Only matched-within-SAR-1 and bank-settled transactions are eligible.


## Final confirmed D365 payment GL mapping
- Bank: 1015
- Commission Expense: 7231
- VAT Vendor: P0672
- CC (MADA + VISA + MASTERCARD): 11020907
- AMEX: 11020901
- TABBY: 11020913
- TAMARA: 11020922
- TAP: 11020904

Dimension examples for Store 601:
- Commission: 7231-601--Sale
- CC: 11020907-601---
- AMEX: 11020901-601---
- TABBY: 11020913-601---
- TAMARA: 11020922-601---
- TAP: 11020904-601---

Description examples:
- CC-Deposited- Aigner Tahlia Mall- Jul -2026
- Credit Card Commission - Aigner Tahlia Mall- Jul -2026
- VAT on Credit Card Commision - Aigner Tahlia Mall- Jul -2026
- CC-Sale- Aigner Tahlia Mall- Jul -2026

CC combines MADA, VISA and MASTERCARD into one weekly store JV after
transaction-level commission calculation. AMEX, TABBY, TAMARA and TAP
remain separate weekly JVs.


## Fix: KeyError 'Journal Batch'
The D365 JV format introduced `Journal batch number`, `Main Account`, and `Description`.
The database approval workflow still expected `Journal Batch`, `Account`, and `Narration`.

This build keeps both schemas in the generated JV and makes `db.replace_jv()` accept either,
so JV creation, approval and D365 export can work together without a KeyError.


## Final Terminal Master rule
- One Store Code may have multiple Terminal IDs.
- Same Terminal ID + same Store Code is accepted and deduplicated.
- Same Terminal ID + different Store Codes is rejected.
- Successful Terminal mapping clears stale Merchant/Store mapping flags.


## Streamlit Cloud deployment
Use `streamlit_app.py` as the cloud entry point.

The package includes:
- `.streamlit/config.toml`
- `.gitignore`
- `CHECK_CLOUD_PACKAGE.py`
- `DEPLOY_STREAMLIT_CLOUD.md`

Do not commit `retailrecon.db` or `.streamlit/secrets.toml`.


## Accounting Period / Close Control
Original transaction date and Source Period are preserved.
A closed-period transaction may be posted later using an open JV Accounting Date.

Example:
- Source Date: 31-Jul-2026
- Closed Through: 31-Jul-2026
- Next Open Date: 01-Aug-2026
- Source Period remains Jul-2026
- JV Accounting Date is 01-Aug-2026

D365 posting gate:
Approved + Balanced + Validation Passed + Bank Settled + Accounting Date Open + Not Previously Posted.


## POS Auth Code Missing — Controlled Fallback
If POS Auth Code is blank, auto-match is allowed only when Store Code, mapped Terminal ID, transaction date, payment type and amount agree and exactly one candidate exists. Amount may be exact or within the approved SAR 1 tolerance. The remark is `Auth Code Missing in POS – Matched using Store + Terminal + Date + Payment Type + Amount`. If Auth Code is present but different, or multiple candidates exist, the system does not guess. Distinct Terminal IDs are not collapsed as duplicate POS rows.


## Fully Integrated Bank Settlement Logic
Bank verification is a control gate after D365 ↔ POS/provider reconciliation, not a second reconciliation.

- ANB Cards: Terminal ID + Payment Type + POS Transaction Date + grouped POS gross + TX count → ANB credit/date.
- TAP: payout_id → SUM(net_amount) = bank credit.
- TABBY: Expected Bank Credit = Transferred Amount - SAR 5.00 once per payout/transfer.
- TAMARA: Expected Bank Credit = Payable to Merchant exactly; no SAR 5 deduction.
- Unsettled items remain Awaiting Bank Settlement and carry forward.
- Normal JV still requires Matched + Difference <= SAR 1 + Bank Settled + Balanced + Validation Passed + Approval + Open Accounting Date.


## Date and Provider Import Correction
- ISO dates such as `2026-07-03` are now parsed year-first and are no longer flipped to `2026-03-07`.
- Excel serial dates remain supported.
- `Creation date`, `created_at GMT+03:00`, charge/capture date aliases are recognized.
- Filenames such as `traf 09582037.xlsx` no longer create a false year-2037 validation exception.
- TABBY Payment ID / TAMARA Order Reference / TAP Charge ID are retained as Provider Reference rather than falsely treated as D365 Auth Code.
- Exact-duplicate collapse now includes Provider Reference so distinct BNPL transactions are not merged.
- TABBY/TAMARA/TAP may use resolved Store + Date + Amount + payment type as a unique fallback when no terminal exists.


## Critical Control Fixes
- Creating a new JV no longer deletes historical approved/posted JVs.
- Approved or posted batches cannot be silently regenerated.
- TAP/TABBY/TAMARA verified payouts now write Bank Settled back to matched reconciliation rows using explicit provider/order references.
- Provider/order/payout identifiers are retained through normalization and matched output.
- Duplicate collapse only occurs when a stable transaction identity exists; anonymous same-amount transactions are never silently merged.
- Stale Auth Missing regression wording was aligned with the current controlled-fallback remark.

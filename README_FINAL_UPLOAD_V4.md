RetailRecon AI V4 - TAP Reference / Payment Scheme

TAP rules:
- Provider = TAP.
- reference_order = primary Auth Code / Provider Reference.
- payment_scheme = payment type shown and matched (MADA/VISA/MASTERCARD/etc.).
- payment type values such as DEBIT/CREDIT are ignored when payment_scheme exists.
- TAP date-window logic from V3 is retained.
- Prior Store 614, Tabby and Tamara corrections remain included.

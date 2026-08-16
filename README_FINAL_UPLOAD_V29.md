RetailRecon AI V29 — Configurable JV Provider Grouping

Added to JV Creation:
- Create JV based on Service Provider / Payment Type.
- Editable JV Group table.
- Default remains CC = MADA + VISA + MASTERCARD.
- AMEX, TABBY, TAMARA, TAP remain separate by default.
- Finance can split or combine providers/payment types for the current JV run.
- Active checkbox can exclude a provider/payment type from the current run.
- Source Payment Type is preserved; configured grouping is applied only to the JV creation copy.

Backward compatibility:
- Existing default Finance grouping remains unchanged unless Finance edits it.
- Existing date-range, bank-settlement, tolerance, approval and D365 controls remain intact.

All JV-related regressions pass.

# V44 — Provider-specific Bank GL Configuration

Finance can independently edit the Bank GL used by TABBY, TAMARA and TAP JVs on page 22 (GL Configuration):

- TABBY_BANK_ACCOUNT
- TAMARA_BANK_ACCOUNT
- TAP_BANK_ACCOUNT

All three default to BANK_ACCOUNT = 1015, so existing behavior is preserved until Finance deliberately changes a value.

The provider clearing/sales GLs remain unchanged and independently editable:
- TABBY_GL = 11020913
- TAMARA_GL = 11020922
- TAP_GL = 11020904

core.create_jv() uses the provider-specific Bank GL for the Bank debit line.
core.validate_jv() independently validates that same provider-specific Bank GL.
Old GL configurations and old batch snapshots remain backward-compatible through the default/fallback mapping.

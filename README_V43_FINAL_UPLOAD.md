# RetailRecon AI — V43 Final Upload

Carries forward V40–V42 and adds V43 Store Mapping Master query-time schema self-healing.

V43 change:
- db.py now has ensure_store_mapping_master_schema().
- load_store_mapping_master() self-heals the legacy SQLite table immediately before SELECT.
- save_store_mapping_master() self-heals immediately before save.
- Existing data is preserved; d365_store_display_name is added idempotently.
- REGRESSION_V43_STORE_MASTER_SELF_HEALING.py is included under tests/.

Current evidence-based boundaries remain unchanged:
- AMEX batch-specific submission→wire allocation is still evidence-blocked.
- TABBY/TAMARA require provider payout evidence for batch→Al Rajhi confirmation.
- TAP July remains an upstream missing-provider-file issue.
- V32 stays read-only until a real model endpoint is available.

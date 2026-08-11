RetailRecon AI V14 — Automatic Exception Resolution

Key fix:
- D365 duplicate detection now uses full transaction identity:
  Store + Date + Receipt ID + Auth Code + Payment + Amount.
- Reusing the same Auth Code on another date/receipt no longer creates a false duplicate.
- Before any D365 row enters Exception Correction Center, the engine performs a final conservative auto-resolution pass:
  1. Store + normalized Auth + Payment + exact amount
  2. Store + Date + Payment + exact amount
  3. Store + Date + Payment + approved tolerance
- Exactly one candidate is mandatory.
- Ambiguous candidates are never guessed and remain maker-checker exceptions.
- Automatic matching does not rewrite D365 Auth Code; it records the match rule and evidence.
- Exception Correction Center is reserved for genuinely unresolved/manual-review cases.

Existing V13 Store 613 SalesDetails bridge and all prior controls remain intact.

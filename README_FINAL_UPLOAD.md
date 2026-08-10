RetailRecon AI - Final Upload Ready Build

Included fixes:
- Robust CSV/TXT parser with delimiter/header detection and no pd.read_csv path inside read_upload().
- Streamlit page reloads current core.py to avoid stale module execution.
- TABBY: Order Number is primary D365 Auth reference; Creation Date recognized.
- TAMARA: numeric leading zeros ignored for reference matching only; original references preserved.
- TAMARA/provider date field recognition expanded.
- Confirmed regression examples:
  * Store 601: D365 0518584327 ↔ Tamara 518584327, amount 384.
  * Store 603: D365 0554030397 ↔ Tamara 554030397, amount 384.
  * Store 601 Tabby: D365 8942394 ↔ Order Number 8942394, amount 427.
- Accounting-period carry-forward control retained from the latest full build.

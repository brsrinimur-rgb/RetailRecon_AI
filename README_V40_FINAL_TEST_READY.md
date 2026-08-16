# RetailRecon AI — V40 Final Test-Ready Build

This package starts from the verified V39 full baseline and carries forward the V40 Store Mapping Master production fix.

## V40 changes included
- `core.py`: D365 store-display resolution accepts optional Store Mapping Master fallback while preserving `D365_STORE_DISPLAY` as primary authority.
- `db.py`: additive `d365_store_display_name` schema migration; canonical-name consistency checks against the actual resulting merge state; shared Store Code / Active / display-name normalization for validation and persistence.
- `pages/14_Store_Mapping_Master.py`: canonical D365 display-name field and alias guidance.
- `pages/24_JV_Creation.py`: loads Store Mapping Master and supplies it to JV creation and D365 validation.
- `REGRESSION_V40_STORE_MASTER_FALLBACK.py`: multi-alias/canonical-name behavior and end-to-end JV validation proof.
- `REGRESSION_V40B_STORE_MASTER_SCHEMA_MIGRATION.py`: additive migration, merge-state protection, no-partial-write, `.0` Store Code normalization, and blank-Active normalization proofs.

## Production data still required
Store Codes 628, 633, 636, 637, 638, 639, 640, 641 still require their real `D365 Store Display Name` values. No placeholder names are installed into production code.

## Sidebar hygiene
No `PROVE_*` or `REGRESSION_*` file is placed under `pages/`; regression files remain outside Streamlit's auto-page folder.

## Test run
From the repository root:

```bash
python REGRESSION_V40_STORE_MASTER_FALLBACK.py
python REGRESSION_V40B_STORE_MASTER_SCHEMA_MIGRATION.py
```

For a broad syntax check:

```bash
python -m compileall -q .
```

Do not upload `retailrecon.db` or `.streamlit/secrets.toml` to GitHub.

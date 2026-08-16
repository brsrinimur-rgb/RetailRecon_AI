# RetailRecon AI — V42 Final Upload

Baseline: V40 + V41 + V42.

Included:
- V40 Store Mapping Master controls, including multi-alias canonical D365 display names,
  merge final-state validation, no-partial-write protection, and normalization parity.
- V41 bank-label canonicalization consistency and expanded System Logic Health required-file checks.
- V42 Exception Correction Center store-reliability alignment with core.reconcile().
- PROVE_* / REGRESSION_* scripts kept outside Streamlit pages/.

Important:
- Production store display names for 628, 633, 636, 637, 638, 639, 640, 641 remain master data.
- AMEX submission-to-specific-wire allocation remains evidence-blocked.
- V32 remains read-only and model endpoint is not wired.

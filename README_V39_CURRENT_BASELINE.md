# RetailRecon AI — Current Verified Baseline V39

This package is assembled from the last complete V30 upload-ready build plus the verified V35–V39 source updates supplied and reviewed in this project.

Current proven controls:
- Deterministic reconciliation/settlement/JV/carry-forward remains the accounting authority.
- JV creation includes only settlement amounts actually bank-received and verified by the selected period end; pending amounts carry forward rather than blocking the entire month.
- Default JV grouping remains CC = MADA + VISA + MASTERCARD; AMEX/TABBY/TAMARA/TAP are separate unless Finance edits the grouping.
- V35: dead GL constant isolated, live D365 bank GL remains 1015, settlement lag parameter added, ANB terminal suffix normalization added.
- V36: previous-period carry-forward is split before dispatch to prevent duplicate re-attachment.
- V32 AI Settlement Explainer remains read-only and explanatory only; no model endpoint is wired in this baseline.
- V37: AMEX statement parser + batch-to-submission proof against the real AMEX statement shape.
- V38: AMEX Sarie/SIBC narration tagging and AMEX wire-claim -> real ANB bank-credit verification.
- V39: ANB card settlement re-proven against the real full July statement; 11/13 AMEX wires bank-confirmed against July; the remaining 2 are proven absent from July only.

Still deliberately unresolved:
- AMEX submission/batch -> specific wire allocation. Until proven, AMEX batch BANK RECEIVED/JV eligibility remains blocked.
- The 2 outstanding AMEX wires require a later-period ANB statement to determine where they actually posted.
- July Al Rajhi real-file verification for TABBY/TAMARA/TAP remains pending a real Al Rajhi statement.
- V32 live model integration remains pending a real model endpoint.

Do not infer or auto-settle these open items.

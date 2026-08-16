# V25 — Advanced Settlement + Strict Exception Routing

Added:
- ANB aggregate bank-credit matching for identical Terminal + Source Date + Scheme evidence.
- ANB gross proof: Bank Credit + Commission + VAT.
- Strong identity without accounting amount proof routes to REVIEW, never auto-settled.
- logic/exception_routing_extension.py.
- Manual Auth Correction only when evidence supports a DIFFERENT Auth Code.
- Same Auth == candidate Auth is excluded from correction.
- Non-Auth unmatched D365 rows remain reconciliation exceptions.
- Approved correction rerun reapplies V25 settlement propagation.

Preserved:
- core.py unchanged.
- db.py unchanged.
- legacy bank transaction matching remains active.
- V24/V23/V22/V21/V20/V18/V17/V16/V15 logic retained.

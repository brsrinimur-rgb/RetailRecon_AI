RetailRecon AI V27 — JV Backward Compatibility Fix

Fixes the reported AttributeError on JV Creation when an older reconciliation
result does not contain the optional `Settlement Stage` column.

The page now creates aligned pandas Series for missing optional settlement fields
instead of scalar defaults.

No accounting, settlement, JV grouping, GL, or database business rule was changed.
Existing V26/V25/V24 logic remains intact.

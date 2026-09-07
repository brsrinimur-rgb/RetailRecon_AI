# TAP Store 613 Order Match Patch

This patch adds the proven Store 613 TAP Gateway rule without replacing or
rewriting the existing RetailRecon matching engine.

## Confirmed rule

1. TAP `reference_order` matches D365 Sales Details `Receipt ID`.
2. D365 `Net Amount` is VAT-exclusive.
3. Expected TAP gross = `D365 Net Amount × 1.15`.
4. Default amount tolerance = SAR 0.02.

## Statuses

- `MATCHED_TAP_ORDER_GROSS`
- `REVIEW_TAP_AMOUNT`
- `PENDING_D365_POSTING`
- `MISSING_D365`
- `REVIEW_TAP_REFERENCE`
- `NOT_APPLICABLE`

`NOT_APPLICABLE` is important: transactions outside Store 613 can continue
through the existing/legacy engine unchanged.

## Files

- `tap_store613_matcher.py` - additive production matcher.
- `tests/test_tap_store613_matcher.py` - regression tests.
- `integration_example.py` - minimal integration example.

## Integration

Copy `tap_store613_matcher.py` into the same package as `engine.py`.

Then, after TAP and D365 Sales Details have been normalized:

```python
from tap_store613_matcher import match_tap_store613_dataframes

tap613_result = match_tap_store613_dataframes(
    tap_df,
    d365_sales_details_df,
    as_of_date=run_date,
    amount_tolerance=0.02,
    pending_days=2,
)
```

Only consume rows whose status is not `NOT_APPLICABLE`. All other TAP/POS
transactions should continue through the existing RetailRecon logic.

## Recommended engine sequence

1. Legacy/general matching stays intact.
2. Detect TAP Gateway + Store 613 rows.
3. Run this evidence-backed rule.
4. Remove only successfully classified Store 613 rows from the remaining TAP
   candidate pool.
5. Continue normal engine processing for everything else.

## Test

From the patch folder:

```bash
pytest tests/test_tap_store613_matcher.py -q
```

The patch intentionally has no dependency on the internal RetailRecon engine,
which makes it safe to regression-test before wiring it into production.

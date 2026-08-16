# V30 Final Merge

Merged on top of the latest working package:
- V27 governance classifier/dedup/bank-identity controls
- corrected ANB accounting proof from real statement/POS example
- Tabby payout underlying-transaction link
- full-month received-only JV gate
- settlement received-by-period-end control
- automatic month-end carry forward / next-period resolution
- editable provider/payment JV grouping with actual core.create_jv support
- settlement evidence reporting
- persistent reconciliation run history
- canonical bank labels and legacy parser row/sheet identity
- backward-compatible DB schema migration to version 30

No production database reset is required.

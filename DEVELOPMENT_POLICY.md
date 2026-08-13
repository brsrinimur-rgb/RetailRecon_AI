# RetailRecon AI Development Rule

## Core Rule
PRESERVE → EXTEND → MIGRATE → REGRESSION TEST → RELEASE

## Mandatory rules
1. Do not delete proven production logic to add a new feature.
2. Add new logic in separate modules/wrappers where practical.
3. Keep existing function signatures and database fields backward compatible.
4. Database changes must use migrations. Never require production DB deletion.
5. Existing source fields, transaction identity and audit evidence must be preserved.
6. New matching logic must not silently override older deterministic controls.
7. Uncertain financial matches remain review/approval items.
8. Every release must run legacy regression tests plus new feature tests.
9. Change log must list Add / Modify / Preserve / Migration.
10. Explicit Finance requirement changes may supersede legacy behavior, but the change must be versioned and documented.

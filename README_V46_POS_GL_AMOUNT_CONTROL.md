# V46 — POS Statement Amount → D365 GL Amount Control

For non-cash transactions:
1. Store Tender → POS uses existing deterministic `core.reconcile()`.
2. A GL evidence row is identified by store/clearing-account/date identity; amount is NOT used to select the evidence row.
3. POS Statement Amount → D365 GL Amount is then compared within tolerance.
4. Only both controls passing produces THREE-WAY RECONCILED.

This prevents a wrong GL amount from disappearing as "GL not found": the real GL evidence row is retained and the amount difference becomes a GL AMOUNT EXCEPTION.

No settlement, Bank Received, JV eligibility, JV creation, approval or posting state is modified.

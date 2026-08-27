# V48 — POS → GL Reconciliation with Merchant ID

Merchant ID is a first-class visible field in the final reconciliation output.

Source:
POS Statement

Accounting authority:
POS Statement Amount ↔ D365 GL Amount

Identity controls:
Merchant ID → Store → Provider → Reference/Auth → Date

The amount is never used to select a GL row. After deterministic identity
evidence is established, the POS Statement Amount is compared with the D365
GL Amount within the configured tolerance.

The final report visibly includes:
Merchant ID, Store Code, Provider, POS Reference, POS Date, POS Amount,
GL Row, GL Main Account, GL Voucher, GL Journal, GL Date, GL Amount,
Difference, Status, Match Rule, Reason and GL Source File.

Store Tender is not part of this module.

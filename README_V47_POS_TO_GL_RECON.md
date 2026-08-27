# V47 — POS Statement → D365 GL Reconciliation

Store Tender is removed.

Authority:
POS Statement ↔ D365 GL Ledger.

Merchant ID, Store, Provider, Reference/Auth and Date establish identity.
Amount is never used to select the GL row.

After deterministic evidence is identified:
POS Statement Amount ↔ D365 GL Amount within tolerance.

A matching amount alone can never create a match.

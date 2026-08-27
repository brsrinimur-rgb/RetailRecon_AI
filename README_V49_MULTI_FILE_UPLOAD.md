# V49 — Multi-File POS / GL Upload

The POS → GL Reconciliation page now supports selecting multiple files in
both upload areas.

POS uploader:
- one or multiple XLSX/XLS/CSV files

D365 GL uploader:
- one or multiple XLSX/XLS/CSV files

All selected files are combined before reconciliation. The reconciliation
continues to use Merchant ID / Store / Provider / Reference/Auth / Date as
identity evidence, then compares POS Statement Amount to D365 GL Amount.

Source filenames are retained in the evidence output.

Store Tender remains removed from this module.

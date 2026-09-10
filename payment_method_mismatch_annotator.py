"""
tools/payment_method_mismatch_annotator.py

Standalone, additive post-processor for the "POS Reconciliation" page's
downloaded Reconciliation Pack (report_export.create_reconciliation_pack()
output -- Dashboard / Transaction_Reconciliation / Exceptions / Store_Summary
/ Payment_Summary / Settlement_Commission / Settlement_Delay).

WHY THIS EXISTS AS A SEPARATE SCRIPT, NOT A CHANGE TO report_export.py:
this session has never been shown report_export.py's source (only
pages/1_POS_Reconciliation.py itself was shared) and has no git access to
that repo, so no direct edit to the file that actually generates the
"Exceptions" sheet is possible. This script operates entirely on the
EXPORTED WORKBOOK instead -- it needs no access to report_export.py, core.py,
or any other source file, and changes nothing about how the app itself
classifies or matches transactions. It's a bridge: usable right now on any
already-downloaded Reconciliation Pack, and the exact same detection logic
(find_payment_method_mismatches()) can be ported into report_export.py
later, once that file is available, to fix this at the source instead of
after the fact.

THE PROBLEM THIS FIXES
-----------------------
The Exceptions sheet already merges a D365 side and a POS side sharing the
same (Store Code, Auth Code) into ONE row, tagged "Review", when both sides
use the SAME Tender/payment type but the amounts differ (e.g. CASH vs CASH,
150.00 vs 1.00). That merge logic evidently requires the tender to match --
observed directly in both real exports used to build this tool.

When the tender DIFFERS but the Auth Code and Amount are IDENTICAL (e.g.
D365 posted a transaction as TAP, the provider/POS side recorded the exact
same Auth Code and Amount under TAMARA), no such merge happens. Instead the
two sides are reported as two disconnected, misleading exceptions:
  - The D365 side reads "Missing POS" -- "D365 transaction found but no
    matching POS settlement" -- which is false; a matching POS settlement
    exists, just filed under a different tender.
  - The POS side often reads "Date Validation Required" or "Missing D365"
    -- also misleading; the real problem has nothing to do with the date.

Confirmed on a real export (RetailReconAI_Reconciliation 37.xlsx, Store 613):
13 of 15 total mismatches found were the exact same pattern -- D365 TAP vs
POS TAMARA, same Auth Code, same Amount to the cent -- meaning this is a
systemic tagging issue for Store 613, not an isolated data-entry slip.

WHAT THIS SCRIPT DOES
----------------------
1. Reads the Exceptions sheet from an already-downloaded Reconciliation Pack.
2. Groups rows by (Store Code, Auth Code) where Auth Code is non-blank.
3. For a group of exactly 2 rows where one row is D365-side-only (D365
   Tender filled, POS Tender blank) and the other is POS-side-only (POS
   Tender filled, D365 Tender blank), with DIFFERENT tender types and
   matching amounts (D365 Total vs POS Total, within `tolerance` SAR --
   default 1.00, matching this app's own default Tolerance setting), flags
   both rows as a Payment Method Mismatch.
4. Deliberately conservative: only acts on a clean 1:1 pairing. A Store+Auth
   Code combination with more than 2 rows, or missing one of the two sides,
   is left completely untouched -- never guesses at an ambiguous grouping
   (same caution this whole app applies elsewhere, e.g. the Store 613 TAP
   D365-evidence bridge only resolving a store when exactly one D365
   candidate matches).
5. For each confirmed pair:
   - Overwrites "Status" -> "PAYMENT METHOD MISMATCH" and "Remarks" -> a
     specific, accurate message naming both tender types and the amount,
     on BOTH of the original rows in the Exceptions sheet in place.
   - Preserves the ORIGINAL Status/Remarks in two new columns
     ("Original Status", "Original Remarks") appended to the sheet, so
     nothing is silently lost -- an auditor can always see what this script
     changed and why.
   - Adds a new "Payment Method Mismatches" summary sheet listing every
     pair side by side (Store, Auth Code, both tenders, both amounts, both
     original statuses) for a quick, no-scrolling review list.
6. Every other sheet (Dashboard, Transaction_Reconciliation, Store_Summary,
   Payment_Summary, Settlement_Commission, Settlement_Delay) and every row
   in Exceptions NOT part of a confirmed pair is left completely untouched,
   including original formatting (edited with openpyxl in place, not
   rebuilt from a pandas DataFrame, so styling/column widths survive).

USAGE
-----
    python payment_method_mismatch_annotator.py <input.xlsx> [output.xlsx] [--tolerance 1.00]

If output.xlsx is omitted, writes "<input>_PAYMENT_METHOD_ANNOTATED.xlsx"
next to the input file.
"""

from __future__ import annotations
import sys
import argparse
from pathlib import Path

import openpyxl
import pandas as pd

EXCEPTIONS_SHEET = "Exceptions"
HEADER_ROW_1INDEXED = 4  # row 4 in the workbook = pandas header=3 (0-indexed)


def _norm(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _load_exceptions_as_records(ws):
    """
    Reads the Exceptions worksheet's header row (row 4) and all data rows
    below it, returning (header_row_map, records) where header_row_map is
    {column_name: 1-indexed column number} and records is a list of dicts,
    each carrying "_row" (the 1-indexed worksheet row number) alongside
    every column's value -- so a match found here can be written straight
    back to the correct worksheet cell.
    """
    header_cells = ws[HEADER_ROW_1INDEXED]
    header_map = {}
    for cell in header_cells:
        name = _norm(cell.value)
        if name:
            header_map[name] = cell.column

    records = []
    for row_idx in range(HEADER_ROW_1INDEXED + 1, ws.max_row + 1):
        row_vals = {"_row": row_idx}
        any_value = False
        for name, col in header_map.items():
            v = ws.cell(row=row_idx, column=col).value
            row_vals[name] = v
            if v is not None and str(v).strip() != "":
                any_value = True
        if any_value:
            records.append(row_vals)
    return header_map, records


def find_payment_method_mismatches(records, tolerance=1.00):
    """
    Core detection logic (pure function, no I/O) -- takes the list of
    Exceptions row-dicts from _load_exceptions_as_records() and returns a
    list of confirmed mismatch pairs, each a dict with both rows' details
    plus the shared Store Code / Auth Code / matched amount.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        store = _norm(r.get("Store Code"))
        auth = _norm(r.get("Auth Code"))
        if not store or not auth:
            continue
        groups.setdefault((store, auth), []).append(r)

    pairs = []
    for (store, auth), grp in groups.items():
        if len(grp) != 2:
            continue  # only ever act on a clean 1:1 pairing -- never guess

        d365_side = [r for r in grp if _norm(r.get("D365 Tender")) and not _norm(r.get("POS Tender"))]
        pos_side = [r for r in grp if _norm(r.get("POS Tender")) and not _norm(r.get("D365 Tender"))]
        if len(d365_side) != 1 or len(pos_side) != 1:
            continue

        d, p = d365_side[0], pos_side[0]
        d_tender = _norm(d.get("D365 Tender")).upper()
        p_tender = _norm(p.get("POS Tender")).upper()
        if d_tender == p_tender:
            continue  # same tender, different amount -- already handled upstream as "Review"

        try:
            d_total = float(d.get("D365 Total") or 0.0)
            p_total = float(p.get("POS Total") or 0.0)
        except (TypeError, ValueError):
            continue
        if abs(d_total - p_total) > tolerance:
            continue

        pairs.append({
            "Store Code": store, "Auth Code": auth,
            "D365 Tender": d_tender, "POS Tender": p_tender,
            "D365 Total": d_total, "POS Total": p_total,
            "D365 Row": d["_row"], "POS Row": p["_row"],
            "D365 Original Status": _norm(d.get("Status")),
            "D365 Original Remarks": _norm(d.get("Remarks")),
            "POS Original Status": _norm(p.get("Status")),
            "POS Original Remarks": _norm(p.get("Remarks")),
        })
    return pairs


def _mismatch_remark(d_tender, p_tender, amount, other_tender_label):
    return (
        f"PAYMENT METHOD MISMATCH: Auth Code and Amount (SAR {amount:,.2f}) match exactly between "
        f"D365 (posted as {d_tender}) and POS/provider (recorded as {p_tender}) -- this is not a "
        f"missing transaction and not a date issue. The same transaction was tagged under two "
        f"different payment methods. Confirm the correct payment method with the provider/bank and "
        f"correct the tagging at source; do not treat as {other_tender_label}."
    )


def annotate_workbook(input_path, output_path=None, tolerance=1.00):
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_name(input_path.stem + "_PAYMENT_METHOD_ANNOTATED.xlsx")
    else:
        output_path = Path(output_path)

    wb = openpyxl.load_workbook(str(input_path))
    if EXCEPTIONS_SHEET not in wb.sheetnames:
        raise ValueError(f"'{EXCEPTIONS_SHEET}' sheet not found -- is this a Reconciliation Pack export?")
    ws = wb[EXCEPTIONS_SHEET]

    header_map, records = _load_exceptions_as_records(ws)
    for required in ("Store Code", "Auth Code", "D365 Tender", "POS Tender", "D365 Total", "POS Total", "Status", "Remarks"):
        if required not in header_map:
            raise ValueError(f"Expected column '{required}' not found in Exceptions header row {HEADER_ROW_1INDEXED}.")

    pairs = find_payment_method_mismatches(records, tolerance=tolerance)

    # Add "Original Status" / "Original Remarks" columns at the end of the
    # Exceptions sheet (only if not already present, so re-running this
    # script on an already-annotated file doesn't duplicate columns).
    status_col = header_map["Status"]
    remarks_col = header_map["Remarks"]
    if "Original Status" not in header_map:
        new_col = ws.max_column + 1
        ws.cell(row=HEADER_ROW_1INDEXED, column=new_col, value="Original Status")
        header_map["Original Status"] = new_col
    if "Original Remarks" not in header_map:
        new_col = ws.max_column + 1
        ws.cell(row=HEADER_ROW_1INDEXED, column=new_col, value="Original Remarks")
        header_map["Original Remarks"] = new_col
    orig_status_col = header_map["Original Status"]
    orig_remarks_col = header_map["Original Remarks"]

    for pair in pairs:
        d_row, p_row = pair["D365 Row"], pair["POS Row"]
        d_amount, p_amount = pair["D365 Total"], pair["POS Total"]

        ws.cell(row=d_row, column=orig_status_col, value=pair["D365 Original Status"])
        ws.cell(row=d_row, column=orig_remarks_col, value=pair["D365 Original Remarks"])
        ws.cell(row=d_row, column=status_col, value="PAYMENT METHOD MISMATCH")
        ws.cell(row=d_row, column=remarks_col, value=_mismatch_remark(
            pair["D365 Tender"], pair["POS Tender"], d_amount, "Missing POS"))

        ws.cell(row=p_row, column=orig_status_col, value=pair["POS Original Status"])
        ws.cell(row=p_row, column=orig_remarks_col, value=pair["POS Original Remarks"])
        ws.cell(row=p_row, column=status_col, value="PAYMENT METHOD MISMATCH")
        ws.cell(row=p_row, column=remarks_col, value=_mismatch_remark(
            pair["D365 Tender"], pair["POS Tender"], p_amount, "Missing D365 / Date Validation Required"))

    # Summary sheet -- one row per pair, side by side, no scrolling needed.
    if "Payment Method Mismatches" in wb.sheetnames:
        del wb["Payment Method Mismatches"]
    summary_ws = wb.create_sheet("Payment Method Mismatches")
    summary_cols = [
        "Store Code", "Auth Code", "D365 Tender", "POS Tender", "Amount (SAR)",
        "D365 Original Status", "POS Original Status", "Exceptions Row (D365 side)",
        "Exceptions Row (POS side)",
    ]
    summary_ws.append([f"Generated by payment_method_mismatch_annotator.py -- {len(pairs)} pair(s) found"])
    summary_ws.append([])
    summary_ws.append(summary_cols)
    for pair in pairs:
        summary_ws.append([
            pair["Store Code"], pair["Auth Code"], pair["D365 Tender"], pair["POS Tender"],
            pair["D365 Total"], pair["D365 Original Status"], pair["POS Original Status"],
            pair["D365 Row"], pair["POS Row"],
        ])

    wb.save(str(output_path))
    return output_path, pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Path to a downloaded RetailReconAI Reconciliation Pack .xlsx")
    ap.add_argument("output", nargs="?", default=None, help="Output path (default: <input>_PAYMENT_METHOD_ANNOTATED.xlsx)")
    ap.add_argument("--tolerance", type=float, default=1.00, help="SAR tolerance for amount matching (default 1.00)")
    args = ap.parse_args()

    out_path, pairs = annotate_workbook(args.input, args.output, tolerance=args.tolerance)
    print(f"Found {len(pairs)} payment method mismatch pair(s).")
    for p in pairs:
        print(f"  Store {p['Store Code']} / Auth {p['Auth Code']}: D365={p['D365 Tender']} SAR {p['D365 Total']:,.2f} "
              f"<-> POS={p['POS Tender']} SAR {p['POS Total']:,.2f}")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()

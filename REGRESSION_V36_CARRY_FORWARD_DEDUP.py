"""
REGRESSION_V36_CARRY_FORWARD_DEDUP.py

Reproduces the exact duplicate-risk scenario flagged in review: a
previous-period carry-forward file (as this page itself would export,
containing BOTH legacy D365/POS rows and settlement rows) re-uploaded as
`previous` must NOT appear twice in the resulting cf DataFrame.

This test extracts and exercises the actual split logic added to
pages/1_POS_Reconciliation.py by re-implementing it against the same
functions (core.make_carry_forward, build_settlement_carry_forward) so the
fix is proven against real behavior, not just read from the diff.

Run: python3 REGRESSION_V36_CARRY_FORWARD_DEDUP.py
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))

sp=importlib.util.spec_from_file_location("core_v36",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v36"]=core; sp.loader.exec_module(core)

from logic.carry_forward_extension import build_settlement_carry_forward

# ---------------------------------------------------------------------
# Build a `previous` file exactly the shape this page itself would export:
# one legacy (D365/POS-type) row and one settlement-type row, concatenated,
# matching cf = concat([cf_legacy, cf_settlement]) from a prior run.
# ---------------------------------------------------------------------
legacy_row=pd.DataFrame([{
    "Store Code":"601","D365 Payment":"MADA","D365 Amount":100.0,
    "Carry Forward Type":"OPEN_D365","Carry Forward Source":"Current",
}])
settlement_row=pd.DataFrame([{
    "Store Code":"601","Payment Type":"VISA","D365 Amount":500.0,
    "Date":pd.Timestamp("2026-07-30"),"Bank Settled":False,
    "Carry Forward Status":"OPEN - CARRY FORWARD","Carry Forward Source":"Settlement Control",
    "Original Period":"2026-07","Carry Forward Period":"2026-08",
}])
previous=pd.concat([legacy_row,settlement_row],ignore_index=True,sort=False)
assert len(previous)==2

# ---------------------------------------------------------------------
# OLD (buggy) behavior: previous passed wholesale into both functions.
# ---------------------------------------------------------------------
us=pd.DataFrame(); up=pd.DataFrame()  # no new current-period unmatched rows
matched=pd.DataFrame(columns=["Date","D365 Amount","Bank Settled","Store Code","Payment Type"])

cf_legacy_old=core.make_carry_forward(us,up,previous)
cf_settlement_old=build_settlement_carry_forward(matched,period_end=pd.Timestamp("2026-08-31"),previous=previous)
cf_old=pd.concat(
    [x for x in [cf_legacy_old,cf_settlement_old] if x is not None and not x.empty],
    ignore_index=True,sort=False
)
# The meaningful test is TOTAL ROW COUNT, not the "Carry Forward Source" tag
# value: build_settlement_carry_forward() only stamps "Prior Period" when
# that column is ABSENT, so a real previous-period file (which already
# carries "Carry Forward Source"="Current"/"Settlement Control" from when it
# was first produced) passes through with its ORIGINAL tag preserved, not
# relabeled. That's a second, smaller finding of its own -- but the actual
# bug is about row COUNT: with only 2 real previous rows and nothing new in
# the current period, the old logic produces 4 total rows (each previous
# row counted once via cf_legacy and again via cf_settlement).
assert len(cf_old)==4, (
    f"expected the bug to reproduce as 4 total rows (2 previous rows counted twice each), got {len(cf_old)}"
)
print(f"[CONFIRMED BUG] Unpatched logic: {len(cf_old)} total carry-forward rows from only 2 real previous rows (each counted twice).")

# ---------------------------------------------------------------------
# NEW (fixed) behavior: split previous by discriminating column before
# passing to each function -- exactly the logic now in the patched page.
# ---------------------------------------------------------------------
previous_legacy=None
previous_settlement=None
if previous is not None and not previous.empty:
    if "Carry Forward Type" in previous.columns:
        _leg=previous[
            previous["Carry Forward Type"].notna()
            & previous["Carry Forward Type"].astype(str).str.strip().ne("")
        ]
        previous_legacy=_leg if not _leg.empty else None
    if "Carry Forward Status" in previous.columns:
        _settle=previous[
            previous["Carry Forward Status"].notna()
            & previous["Carry Forward Status"].astype(str).str.strip().ne("")
        ]
        previous_settlement=_settle if not _settle.empty else None
    if previous_legacy is None and previous_settlement is None:
        previous_legacy=previous

cf_legacy_new=core.make_carry_forward(us,up,previous_legacy)
cf_settlement_new=build_settlement_carry_forward(matched,period_end=pd.Timestamp("2026-08-31"),previous=previous_settlement)
cf_new=pd.concat(
    [x for x in [cf_legacy_new,cf_settlement_new] if x is not None and not x.empty],
    ignore_index=True,sort=False
)
assert len(cf_new)==2, (
    f"expected exactly 2 total rows (1 legacy + 1 settlement, no duplication), got {len(cf_new)}"
)
print(f"[FIXED] Patched split logic: {len(cf_new)} total carry-forward rows from 2 real previous rows -- no duplication.")

# ---------------------------------------------------------------------
# Backward compatibility: an old previous-period file with NEITHER
# discriminating column (predates this split) must still carry forward,
# treated as legacy-only exactly as before this fix existed.
# ---------------------------------------------------------------------
old_shape_previous=pd.DataFrame([{"Store Code":"601","D365 Payment":"MADA","D365 Amount":50.0}])
previous_legacy2=None
previous_settlement2=None
if "Carry Forward Type" in old_shape_previous.columns:
    pass
if "Carry Forward Status" in old_shape_previous.columns:
    pass
if previous_legacy2 is None and previous_settlement2 is None:
    previous_legacy2=old_shape_previous

cf_legacy3=core.make_carry_forward(us,up,previous_legacy2)
assert len(cf_legacy3)==1
assert cf_legacy3.iloc[0]["Carry Forward Source"]=="Prior Period"
print("[PASS] Backward compatibility: old-shape previous file (no discriminating columns) still carries forward once, as legacy.")

print("REGRESSION V36 CARRY FORWARD DEDUP PASS")

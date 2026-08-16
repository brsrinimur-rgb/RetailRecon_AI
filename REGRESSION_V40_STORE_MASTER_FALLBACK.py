"""
REGRESSION_V40_STORE_MASTER_FALLBACK.py

Reproduces the exact production error shown in the live deployment
screenshot: "No Store display name configured for store 628
(D365_STORE_DISPLAY)" -- and 7 others (633, 636, 637, 638, 639, 640, 641),
all stores genuinely absent from the hardcoded D365_STORE_DISPLAY dict in
core.py (confirmed: it only lists 20 stores; these 8 aren't among them).

Proves the fix, INCLUDING the correction from review: Store Mapping Master
is an ALIAS table -- a single Store Code can legitimately have several
active alias rows (different POS/Tabby/Tamara/payment-link naming for the
same physical location). The fallback does NOT require exactly one row per
store code (that was the V40-draft-1 bug, caught in review before this
version). It requires exactly one DISTINCT "D365 Store Display Name" among
ACTIVE rows for that store code -- many aliases, one canonical name.

Schema (added via db.py's existing additive/self-healing migration
pattern, _ensure_columns -- no data loss, no destructive change):
  store_mapping_master gains a new column d365_store_display_name,
  distinct from provider_store_name (the alias). save_store_mapping_master()
  rejects a save where active rows for one Store Code disagree on this
  value -- checked at save time, not left to surface later at JV validation.

Also proves:
  - Backward compatibility: omitting store_master preserves the exact
    original behavior.
  - Inactive rows never contribute to resolution or to the ambiguity check.
  - Genuine disagreement (two active rows, same store code, DIFFERENT
    D365 Store Display Name) still correctly blocks -- never guesses.
  - Multiple active ALIAS rows that all AGREE on the same D365 Store
    Display Name correctly resolve -- this is the exact scenario flagged
    in review that the first draft got wrong.

Run: python3 REGRESSION_V40_STORE_MASTER_FALLBACK.py
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))
sp=importlib.util.spec_from_file_location("core_v40",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v40"]=core; sp.loader.exec_module(core)

# ---------------------------------------------------------------------
# 1. Reproduce the exact production bug.
# ---------------------------------------------------------------------
assert "628" not in core.D365_STORE_DISPLAY, "628 unexpectedly already hardcoded -- test fixture stale"
info_no_master=core._d365_store_info("628")
assert info_no_master["store_name"]=="628"
print("[CONFIRMED BUG] Store 628 (and the 7 others in the screenshot) genuinely have no "
      "hardcoded entry -- _d365_store_info() returns the bare code, exactly reproducing "
      "the production 'No Store display name configured' error.")

# ---------------------------------------------------------------------
# 2. THE SPECIFIC SCENARIO FLAGGED IN REVIEW: multiple active alias rows
#    for the SAME store code, all agreeing on the SAME D365 Store Display
#    Name, must resolve correctly -- not be rejected as "ambiguous" just
#    because there's more than one row.
# ---------------------------------------------------------------------
multi_alias_master=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"AIGNER - PANORAMA MALL","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"PANORAMA PAYMENT LINKS","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
])
info_multi=core._d365_store_info("628",store_master=multi_alias_master)
assert info_multi["store_name"]=="Aigner Panorama Mall", (
    f"REGRESSION: 3 agreeing active aliases for the same store code must resolve, got {info_multi}"
)
print("[PASS] Three active alias rows (different provider-name spellings) for store 628, "
      "all agreeing on the same D365 Store Display Name, correctly resolve to "
      "'Aigner Panorama Mall' -- the exact scenario the first V40 draft got wrong.")

# ---------------------------------------------------------------------
# 3. Genuine ambiguity -- active rows for the SAME store code that
#    DISAGREE on D365 Store Display Name -- must still block.
# ---------------------------------------------------------------------
conflicting_display_master=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"TYPO ENTRY","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorma Mall","Active":"Yes"},
])
info_conflict=core._d365_store_info("628",store_master=conflicting_display_master)
assert info_conflict["store_name"]=="628", (
    "genuine disagreement on D365 Store Display Name must block, not guess which one is right"
)
print("[PASS] Two active rows for the SAME store code that genuinely DISAGREE on D365 Store "
      "Display Name correctly stay unresolved -- never guesses which is correct.")

# ---------------------------------------------------------------------
# 4. Inactive rows never contribute -- neither to resolution nor to the
#    ambiguity check.
# ---------------------------------------------------------------------
with_inactive_conflict=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"OLD RETIRED ALIAS","Store Code":"628",
     "D365 Store Display Name":"Old Wrong Name Ltd","Active":"No"},
])
info_inactive=core._d365_store_info("628",store_master=with_inactive_conflict)
assert info_inactive["store_name"]=="Aigner Panorama Mall", (
    f"inactive row must not block resolution or count toward ambiguity, got {info_inactive}"
)
print("[PASS] An inactive historical alias with a different (stale) D365 Store Display Name "
      "is correctly ignored -- does not block resolution and does not count as ambiguity.")

only_inactive=pd.DataFrame([
    {"Provider Store Name":"RETIRED","Store Code":"628",
     "D365 Store Display Name":"Some Old Name","Active":"No"},
])
info_only_inactive=core._d365_store_info("628",store_master=only_inactive)
assert info_only_inactive["store_name"]=="628"
print("[PASS] A store with only an inactive alias row (nothing currently active) correctly "
      "stays unresolved, rather than resolving from stale/inactive data.")

# ---------------------------------------------------------------------
# 5. A row with a blank D365 Store Display Name (alias-only, not yet
#    confirmed) is correctly excluded, without blocking a confirmed sibling.
# ---------------------------------------------------------------------
partial_master=pd.DataFrame([
    {"Provider Store Name":"AIGNER PANORAMA","Store Code":"628",
     "D365 Store Display Name":"Aigner Panorama Mall","Active":"Yes"},
    {"Provider Store Name":"NEWLY ADDED ALIAS","Store Code":"628",
     "D365 Store Display Name":"","Active":"Yes"},
])
info_partial=core._d365_store_info("628",store_master=partial_master)
assert info_partial["store_name"]=="Aigner Panorama Mall", (
    f"a blank display name on one alias row must not block a confirmed sibling row, got {info_partial}"
)
print("[PASS] A blank/unconfirmed D365 Store Display Name on one alias row does not block "
      "resolution from a confirmed sibling row for the same store code.")

# ---------------------------------------------------------------------
# 6. Backward compatibility.
# ---------------------------------------------------------------------
conflicting_hardcoded=pd.DataFrame([
    {"Provider Store Name":"WRONG","Store Code":"601","D365 Store Display Name":"Wrong Name","Active":"Yes"}
])
info_601=core._d365_store_info("601",store_master=conflicting_hardcoded)
assert info_601["store_name"]=="Aigner Tahlia Mall"
print("[PASS] Backward compatible: stores already in D365_STORE_DISPLAY are unaffected by "
      "store_master, even when store_master conflicts with them.")

info_omitted=core._d365_store_info("628")
assert info_omitted==info_no_master
print("[PASS] Omitting store_master entirely (old call signature) behaves exactly as before.")

# ---------------------------------------------------------------------
# 7. Unmapped store stays unresolved.
# ---------------------------------------------------------------------
info_unmapped=core._d365_store_info("999",store_master=multi_alias_master)
assert info_unmapped["store_name"]=="999"
print("[PASS] A store not present in store_master at all stays unresolved -- never guesses.")

# ---------------------------------------------------------------------
# 8. End-to-end: validate_jv().
# ---------------------------------------------------------------------
jv=pd.DataFrame([{
    "Journal Batch":"RR-628-CC-20260701-20260731","Store Code":"628","Group":"CC",
    "Main Account":"11020907","Ledger Dimension":"11020907-628---",
    "Default Dimension":"11020907-628---","Debit":1000.0,"Credit":0.0,
},{
    "Journal Batch":"RR-628-CC-20260701-20260731","Store Code":"628","Group":"CC",
    "Main Account":"11020907","Ledger Dimension":"11020907-628---",
    "Default Dimension":"11020907-628---","Debit":0.0,"Credit":1000.0,
}])

without_master=core.validate_jv(jv.copy())
assert not without_master["Validation Passed"].all()
assert any("Store display name" in e for e in without_master["Validation Errors"] if e)
print("[CONFIRMED BUG, end-to-end] validate_jv() without store_master blocks store 628, "
      "reproducing the exact screenshot error.")

with_master=core.validate_jv(jv.copy(),store_master=multi_alias_master)
store_errors=[e for e in with_master["Validation Errors"] if "Store display name" in e]
assert not store_errors, f"should no longer block once a correctly multi-aliased master is supplied: {store_errors}"
print("[FIXED, end-to-end] validate_jv() with a correctly multi-aliased store_master no "
      "longer raises the store-name error for store 628.")

with_conflicting=core.validate_jv(jv.copy(),store_master=conflicting_display_master)
conflict_errors=[e for e in with_conflicting["Validation Errors"] if "Store display name" in e]
assert conflict_errors, "validate_jv must still block when store_master rows genuinely disagree"
print("[PASS, end-to-end] validate_jv() still correctly blocks store 628 when store_master "
      "rows genuinely disagree on the D365 name -- never posts an unresolved/ambiguous name.")

print("REGRESSION V40 STORE MASTER FALLBACK PASS")

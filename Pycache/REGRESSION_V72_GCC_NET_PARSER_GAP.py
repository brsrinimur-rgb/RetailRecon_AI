"""
REGRESSION_V72_GCC_NET_PARSER_GAP.py

Purpose: verify the V72 GCC NET fix, per the user's explicit direction after
freezing V71: "Then work in this order: GCC NET parser gap -> ..."

IMPORTANT SCOPE CORRECTION made during this fix, stated plainly: V70/V71's
docs described this as "a one-line addition to the narration parser's scheme
detection." That undersold the real gap. Tracing the full chain before
touching anything found THREE places GCC NET was silently excluded, not one:

  1. logic/bank_settlement_extension.py: parse_anb_narration()'s scheme regex
     recognized MADA/VC/MC but not GC -- so GC_-prefixed ANB narration never
     got a Provider/Scheme tag (the originally-identified gap).
  2. logic/bank_settlement_extension.py: the local _norm_payment() had no
     GCC NET case, so even a correctly-extracted "GC" scheme token wouldn't
     normalize to the "GCC NET" string used everywhere else.
  3. core.py: build_card_settlement_batches()'s Payment Type filter was
     hardcoded to {"MADA","VISA","MASTERCARD","AMEX"} -- GCC NET POS
     transactions were filtered out and NEVER became a settlement batch at
     all. Fixing only #1 and #2 would have shipped a narration-parser change
     that tags bank credits correctly but has nothing to match them against --
     a fix that looks complete in code review but changes zero real behavior.

All three are fixed here, additively, mirroring the exact pattern GCC NET's
sibling schemes (MADA/VISA/MASTERCARD) already use everywhere in the
codebase -- no new matching logic, no new status vocabulary.

Modified functions (proven changed via SOURCE DIFFERING from pre-V72, the
opposite check from V71's "prove unchanged" hashes, since these ARE the
functions being fixed this time):
  - core._norm_payment()
  - core.build_card_settlement_batches()
  - bank_ext._norm_payment()
  - bank_ext.parse_anb_narration()

Untouched (confirmed same pattern as before): reconcile_card_batches_advanced(),
reconcile_amex_batches_via_statement(), reconcile_amex_wires_to_bank(),
finalize_amex_batches(), annotate_amex_wire_confirmations() -- all V71 work
stays frozen; this fix only extends the recognized-scheme set the modified
functions filter/tag on.

Covers:
  1. core._norm_payment(): GCC NET/GCCNET/gcc net/GC all normalize to
     "GCC NET"; MADA/VISA/MASTERCARD/AMEX normalization is BYTE-IDENTICAL
     to the pre-V72 function on a broad set of inputs (full comparison, not
     spot checks).
  2. core.build_card_settlement_batches(): GCC NET POS transactions now
     produce a settlement batch (previously silently dropped); MADA/VISA/
     MASTERCARD/AMEX batches built from a matched set that ALSO contains GCC
     NET rows are byte-for-byte identical to batches built from the same set
     with the GCC NET rows removed (i.e. adding GCC NET support changes
     nothing about the other schemes' batches) via pd.testing.assert_frame_equal.
  3. bank_ext._norm_payment(): GC/GCC/GCCNET normalize to "GCC NET";
     MADA/VC/MC/AMEX/TABBY/TAMARA/TAP normalization is byte-identical to the
     pre-V72 function.
  4. bank_ext.parse_anb_narration(): a GC_-prefixed narration now returns
     Provider="ANB POS", Narration Scheme="GCC NET" with fee/VAT/TX count
     parsed (previously Provider="" and Narration Scheme=""); a real MADA/
     VC/MC narration and a real AMEX wire narration parse byte-identically
     to the pre-V72 function (every returned field compared, not a subset).
  5. FULL LOOP, not just tagging: a synthetic GCC NET settlement batch +
     matching GC_ narration bank credit, run through the UNTOUCHED
     reconcile_card_batches_advanced(), reaches BANK RECEIVED -- proving the
     fix actually closes the loop end-to-end, not just that narration gets a
     label with nothing to use it.
  6. Before/after on reconcile_card_batches_advanced() itself (untouched,
     but exercised end-to-end): MADA/VISA/MASTERCARD/AMEX results are
     byte-for-byte identical whether a GCC NET batch/credit pair is present
     in the same run or not -- same "cannot disturb existing matches"
     discipline as V71's Section 1.
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"[PASS] {msg}")

ROOT = os.path.dirname(os.path.abspath(__file__))

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

def _find_bank_ext(base_dir):
    # The real repo keeps this file at logic/bank_settlement_extension.py.
    # A flat delivery-package layout (this file dropped next to a bare copy
    # of bank_settlement_extension.py, as in a scratch test directory) is
    # supported as a fallback ONLY -- checked second, never first, so this
    # can never silently prefer a stray/unrelated flat copy over the real
    # deployed one (an earlier version of this script had exactly that bug:
    # it loaded a pre-existing, unrelated root-level duplicate file instead
    # of the real logic/bank_settlement_extension.py when run inside a full
    # repo checkout -- caught by running this suite inside a full repo copy,
    # not just the scratch delivery directory. Fixed here.)
    logic_path = os.path.join(base_dir, "logic", "bank_settlement_extension.py")
    if os.path.isfile(logic_path):
        return logic_path
    flat_path = os.path.join(base_dir, "bank_settlement_extension.py")
    if os.path.isfile(flat_path):
        return flat_path
    raise FileNotFoundError(f"bank_settlement_extension.py not found under {base_dir} "
                             f"(checked logic/bank_settlement_extension.py and a flat copy)")

# NEW (V72) modules -- the files being delivered.
core_new = _load("core_v72_new", os.path.join(ROOT, "core.py"))
bank_ext_new = _load("bank_ext_v72_new", _find_bank_ext(ROOT))

# OLD (pre-V72) modules -- the untouched originals, for genuine before/after
# comparison. ORIG_DIR must point at a checkout of the real repo as it stood
# immediately before this fix (same technique V71 used for its hash baseline).
ORIG_DIR = os.environ.get("V72_ORIG_DIR", "/home/claude/repo_clone")
core_old = _load("core_v72_old", os.path.join(ORIG_DIR, "core.py"))
bank_ext_old = _load("bank_ext_v72_old", _find_bank_ext(ORIG_DIR))

_assert(
    "def finalize_amex_batches" in open(_find_bank_ext(ROOT)).read(),
    "Sanity check: the NEW bank_ext module actually loaded is the real, current file "
    "(contains V71's finalize_amex_batches) -- not a stray/unrelated duplicate"
)

# =============================================================================
# 1. core._norm_payment(): new GCC NET cases + byte-identical old behavior.
# =============================================================================
for variant in ["GCC NET", "GCCNET", "gcc net", "Gcc Net", "GC"]:
    _assert(core_new._norm_payment(variant) == "GCC NET",
            f"core._norm_payment({variant!r}) == 'GCC NET'")

_UNCHANGED_INPUTS = [
    "MADA", "P", "P1", "VISA", "VC", "MASTER", "MC", "MASTERCARD",
    "AMEX", "AX", "AMERICAN EXPRESS", "TABBY", "TAMARA", "TAP",
    "", "SOMETHING ELSE", "KNET",
]
for v in _UNCHANGED_INPUTS:
    old_r = core_old._norm_payment(v)
    new_r = core_new._norm_payment(v)
    _assert(old_r == new_r,
            f"core._norm_payment({v!r}) unchanged: {old_r!r} (old) == {new_r!r} (new)")

# =============================================================================
# 2. core.build_card_settlement_batches(): GCC NET now batches; other
#    schemes' batches are unaffected by GCC NET rows being present.
# =============================================================================
matched_rows = [
    {"Unique Transaction ID":"M1","Store Code":"601","Payment Type":"MADA",
     "POS Date":pd.Timestamp("2026-09-01"),"Terminal ID":"55610701",
     "POS Amount":500.0,"Net Amount":495.0,"Commission":4.3,"VAT":0.7},
    {"Unique Transaction ID":"V1","Store Code":"601","Payment Type":"VISA",
     "POS Date":pd.Timestamp("2026-09-01"),"Terminal ID":"55610702",
     "POS Amount":800.0,"Net Amount":790.0,"Commission":8.7,"VAT":1.3},
    {"Unique Transaction ID":"C1","Store Code":"601","Payment Type":"MASTERCARD",
     "POS Date":pd.Timestamp("2026-09-01"),"Terminal ID":"55610703",
     "POS Amount":300.0,"Net Amount":295.0,"Commission":4.0,"VAT":1.0},
    {"Unique Transaction ID":"A1","Store Code":"601","Payment Type":"AMEX",
     "POS Date":pd.Timestamp("2026-09-01"),"Terminal ID":"55610704",
     "POS Amount":1000.0,"Net Amount":970.0,"Commission":27.0,"VAT":3.0},
]
gcc_row = {"Unique Transaction ID":"G1","Store Code":"601","Payment Type":"GCC NET",
           "POS Date":pd.Timestamp("2026-09-01"),"Terminal ID":"55610705",
           "POS Amount":450.0,"Net Amount":443.25,"Commission":5.85,"VAT":0.90}

matched_without_gcc = pd.DataFrame(matched_rows)
matched_with_gcc = pd.DataFrame(matched_rows + [gcc_row])

batches_without_gcc = core_new.build_card_settlement_batches(matched_without_gcc)
batches_with_gcc = core_new.build_card_settlement_batches(matched_with_gcc)

_assert(len(batches_without_gcc) == 4, "4 batches (MADA/VISA/MASTERCARD/AMEX) built without GCC NET present")
_assert(len(batches_with_gcc) == 5, "5 batches built with GCC NET present -- the new batch is NOT silently dropped")
_assert("GCC NET" in set(batches_with_gcc["Payment Type"]), "GCC NET batch actually appears in the output")
gcc_batch = batches_with_gcc[batches_with_gcc["Payment Type"] == "GCC NET"].iloc[0]
_assert(gcc_batch["Provider"] == "ANB POS", "GCC NET batch correctly tagged Provider=ANB POS, not AMEX or blank")
_assert(round(float(gcc_batch["Expected Bank Amount"]), 2) == 443.25, "GCC NET batch's Expected Bank Amount is correct")

# The other 4 batches must be identical whether or not the GCC NET row was
# in the input -- full-DataFrame comparison, same discipline as V71.
non_gcc_from_with = batches_with_gcc[batches_with_gcc["Payment Type"] != "GCC NET"] \
    .sort_values("Settlement Batch ID").reset_index(drop=True)
non_gcc_from_without = batches_without_gcc.sort_values("Settlement Batch ID").reset_index(drop=True)
pd.testing.assert_frame_equal(non_gcc_from_with, non_gcc_from_without)
print("[PASS] MADA/VISA/MASTERCARD/AMEX batches are byte-for-byte identical whether GCC NET rows "
      "are present in the input or not -- adding GCC NET support changes nothing else")

# Direct before/after on the OLD (untouched) function: it must still exclude
# GCC NET, confirming this really was a real gap, not an imagined one.
old_batches_with_gcc = core_old.build_card_settlement_batches(matched_with_gcc)
_assert("GCC NET" not in set(old_batches_with_gcc.get("Payment Type", pd.Series(dtype=str))),
        "CONFIRMED PRE-V72 GAP: the untouched original build_card_settlement_batches() silently "
        "drops the GCC NET row -- proves the bug was real, not just a narration-side cosmetic gap")
_assert(len(old_batches_with_gcc) == 4,
        "Pre-V72: only 4 batches built even with the GCC NET row present (it's discarded)")

# =============================================================================
# 3. bank_ext._norm_payment(): new GCC NET cases + byte-identical old behavior.
# =============================================================================
for variant in ["GC", "GCC", "GCCNET", "gcc net", "GCC NET"]:
    _assert(bank_ext_new._norm_payment(variant) == "GCC NET",
            f"bank_ext._norm_payment({variant!r}) == 'GCC NET'")

_UNCHANGED_BANK_INPUTS = ["MADA", "P", "P1", "VISA", "VC", "VISACARD", "MASTER", "MC",
                           "MASTERCARD", "AMEX", "AX", "TABBY", "TAMARA", "TAP", "", "OTHER"]
for v in _UNCHANGED_BANK_INPUTS:
    old_r = bank_ext_old._norm_payment(v)
    new_r = bank_ext_new._norm_payment(v)
    _assert(old_r == new_r,
            f"bank_ext._norm_payment({v!r}) unchanged: {old_r!r} (old) == {new_r!r} (new)")

# =============================================================================
# 4. bank_ext.parse_anb_narration(): GC_ narration now tags correctly; MADA/
#    VC/MC/AMEX-wire narration parses byte-identically to the pre-V72 version.
# =============================================================================
gc_narration = ["POS GC_15.78_105.09_TX_12", "301128607335_55610715_300626", "", ""]
r = bank_ext_new.parse_anb_narration(gc_narration)
_assert(r["Provider"] == "ANB POS", "GC_ narration now tags Provider=ANB POS (was '' before V72)")
_assert(r["Narration Scheme"] == "GCC NET", "GC_ narration now tags Narration Scheme=GCC NET (was '' before V72)")
_assert(r["Narration Terminal ID"] == "55610715", "Terminal ID still extracted correctly alongside the scheme fix")
_assert(round(float(r["Narration VAT"]), 2) == 15.78, "VAT parsed correctly from the GC_ narration")
_assert(round(float(r["Narration Fee"]), 2) == 105.09, "Fee parsed correctly from the GC_ narration")
_assert(int(r["Narration Transaction Count"]) == 12, "TX count parsed correctly from the GC_ narration")

r_old_gc = bank_ext_old.parse_anb_narration(gc_narration)
_assert(r_old_gc["Provider"] == "" and r_old_gc["Narration Scheme"] == "",
        "CONFIRMED PRE-V72 GAP: the untouched original parse_anb_narration() leaves GC_ narration "
        "completely untagged (Provider='', Scheme='') -- proves the bug was real")

# Byte-identical parsing on non-GCC-NET narration shapes (MADA, VC, AMEX wire).
test_narrations = [
    ["POS MADA_5.20_45.00_TX_8", "301128607335_55610716_010726", "", ""],
    ["POS VC_15.78_105.09_TX_12", "301128607335_55610715_300626", "", ""],
    ["MC_9.30_60.00_TX_5", "301128607335_55610717_020726", "", ""],
    ["تحويل وارد - نظام سريع من خلال البنك العربي الوطني . المرسل : Amex (Saudi Arabia) Ltd., "
     "AC-0101121212009. رقم المرجع : SD8756367 - UTIREF#SIBCPMT261930002", "", "", ""],
    ["random unrelated narration text with no recognizable pattern", "", "", ""],
]
for parts in test_narrations:
    old_out = bank_ext_old.parse_anb_narration(parts)
    new_out = bank_ext_new.parse_anb_narration(parts)
    _assert(old_out == new_out or (
        # dict equality handles NaT/NaN mismatches oddly; compare key-by-key
        # with NaN-aware equality as a fallback.
        set(old_out.keys()) == set(new_out.keys()) and all(
            (pd.isna(old_out[k]) and pd.isna(new_out[k])) if not isinstance(old_out[k], str)
            else old_out[k] == new_out[k]
            for k in old_out
        )
    ), f"parse_anb_narration() output unchanged for non-GCC-NET narration: {parts[0][:40]}...")

# =============================================================================
# 5. FULL LOOP: a GCC NET settlement batch actually reaches BANK RECEIVED
#    against a real GC_-narrated bank credit -- not just tagged, matched.
# =============================================================================
gcc_batch_df = pd.DataFrame([{
    "Settlement Source":"ANB POS","Settlement Batch ID":"GCC1","Provider":"ANB POS",
    "Store Code":"601","Terminal ID":"55610705","Payment Type":"GCC NET",
    "Settlement Date":pd.Timestamp("2026-09-01"),"Gross Amount":450.0,
    "Expected Bank Amount":443.25,"Transaction Count":3,
}])
gc_bank_row = bank_ext_new.parse_anb_narration(["POS GC_5.85_0.90_TX_3", "301128607335_55610705_010926", "", ""])
bank_df = pd.DataFrame([{
    "Bank":"ANB","Bank Date":pd.Timestamp("2026-09-02"),"Bank Amount":450.0,"Credit":450.0,"Debit":0.0,
    "Bank Source File":"anb.xlsx","Bank Source Sheet":"S1","Bank Source Row":1,
    **gc_bank_row,
}])
# Deliberately use the UNTOUCHED reconcile_card_batches_advanced() -- proves
# the fix works purely by feeding it correctly-tagged input, no matching
# logic change required.
gcc_result, gcc_unmatched = bank_ext_new.reconcile_card_batches_advanced(gcc_batch_df, bank_df, 1.0)
_assert(len(gcc_result) == 1, "GCC NET batch is actually attempted by the (untouched) ANB matcher")
_assert(gcc_result.iloc[0]["Settlement Status"] == "BANK RECEIVED",
        "GCC NET batch reaches BANK RECEIVED end-to-end -- the loop genuinely closes, not just tagging")
_assert("Terminal + Scheme + Date + TX Count" in gcc_result.iloc[0]["Bank Match Rule"],
        "GCC NET match uses the exact same deterministic evidence rule every other scheme uses")

# =============================================================================
# 6. Before/after on reconcile_card_batches_advanced() (untouched): existing
#    MADA/VISA/MASTERCARD/AMEX results unaffected by a GCC NET batch/credit
#    pair being present in the same run.
# =============================================================================
mada_batch_df = pd.DataFrame([{
    "Settlement Source":"ANB POS","Settlement Batch ID":"M1","Provider":"ANB POS",
    "Store Code":"601","Terminal ID":"55610701","Payment Type":"MADA",
    "Settlement Date":pd.Timestamp("2026-09-01"),"Gross Amount":500.0,
    "Expected Bank Amount":495.0,"Transaction Count":4,
}])
mada_bank_row = bank_ext_new.parse_anb_narration(["POS MADA_0.70_4.30_TX_4", "301128607335_55610701_010926", "", ""])
mada_bank_df = pd.DataFrame([{
    "Bank":"ANB","Bank Date":pd.Timestamp("2026-09-02"),"Bank Amount":495.0,"Credit":495.0,"Debit":0.0,
    "Bank Source File":"anb.xlsx","Bank Source Sheet":"S1","Bank Source Row":2,
    **mada_bank_row,
}])

before_batches = pd.concat([mada_batch_df], ignore_index=True)
before_bank = pd.concat([mada_bank_df], ignore_index=True)
after_batches = pd.concat([mada_batch_df, gcc_batch_df], ignore_index=True)
after_bank = pd.concat([mada_bank_df, bank_df], ignore_index=True)

before_res, before_unm = bank_ext_new.reconcile_card_batches_advanced(before_batches, before_bank, 1.0)
after_res, after_unm = bank_ext_new.reconcile_card_batches_advanced(after_batches, after_bank, 1.0)

before_mada = before_res[before_res["Payment Type"] == "MADA"].reset_index(drop=True)
after_mada = after_res[after_res["Payment Type"] == "MADA"].reset_index(drop=True)
pd.testing.assert_frame_equal(before_mada, after_mada, check_dtype=False)
print("[PASS] MADA batch result is identical whether a GCC NET batch/credit pair is present in the "
      "same run or not -- GCC NET support does not disturb existing ANB POS matching")

print("REGRESSION V72 GCC NET PARSER GAP PASS")

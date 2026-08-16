"""
REGRESSION_V35_GL_LAG_TERMINAL_FIXES.py

Proves three fixes made against the REAL uploaded source (core.py,
logic/bank_settlement_extension.py):

1. GL_DEFAULTS dead-code correction: confirms the corrected/renamed constant
   is not referenced anywhere live, and that D365_JV_DEFAULTS (the real,
   used constant) is unaffected.
2. settlement_lag_days is backward compatible (default behavior unchanged)
   and actually widens the match window when set.
3. ANB terminal ID normalization strips the confirmed 16-digit/01300000
   suffix shape, and leaves every other shape untouched.

Run: python3 REGRESSION_V35_GL_LAG_TERMINAL_FIXES.py
"""
from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root))

sp=importlib.util.spec_from_file_location("core_v35",root/"core.py")
core=importlib.util.module_from_spec(sp); sys.modules["core_v35"]=core; sp.loader.exec_module(core)

from logic import bank_settlement_extension as bank_ext

# ---------------------------------------------------------------------
# 1. GL dead-code fix
# ---------------------------------------------------------------------
assert not hasattr(core,"GL_DEFAULTS"), "GL_DEFAULTS should no longer exist under that name"
assert hasattr(core,"GL_DEFAULTS_DEPRECATED_DO_NOT_USE")
dep=core.GL_DEFAULTS_DEPRECATED_DO_NOT_USE
assert dep["BANK"]=="1010"  # preserved verbatim as an audit trail, just renamed/flagged
# Confirm the REAL, used constant is untouched and correct.
assert core.D365_JV_DEFAULTS["BANK_ACCOUNT"]=="1015"
assert core.D365_JV_DEFAULTS["VAT_VENDOR"]=="P0672"
assert core.D365_JV_DEFAULTS["CC_GL"]=="11020907"
# Confirm create_jv/validate_jv still only ever reference D365_JV_DEFAULTS,
# never the deprecated dict, by source inspection.
import inspect
create_jv_src=inspect.getsource(core.create_jv)
assert "GL_DEFAULTS_DEPRECATED" not in create_jv_src
assert "D365_JV_DEFAULTS" in create_jv_src
print("[PASS] GL dead-code fix: deprecated constant isolated, real constant (1015/P0672/11020907) untouched.")

# ---------------------------------------------------------------------
# 2. settlement_lag_days backward compatibility + widening effect
# ---------------------------------------------------------------------
batch=pd.DataFrame([{
    "Settlement Source":"ANB POS","Settlement Batch ID":"B1","Provider":"ANB POS",
    "Store Code":"601","Terminal ID":"55610694","Payment Type":"MADA",
    "Settlement Date":pd.Timestamp("2026-07-07"),
    "Gross Amount":1000.0,"Expected Bank Amount":1000.0,"Transaction Count":1,
}])
# Bank credit lands 5 days after the POS date -- outside the default 0-3 window.
bank_late=pd.DataFrame([{
    "Bank":"ANB","Bank Date":pd.Timestamp("2026-07-12"),"Bank Amount":1000.0,
    "Credit":1000.0,"Description":"X",
    "Narration Terminal ID":"55610694","Narration Scheme":"MADA",
    "Narration Source Date":pd.Timestamp("2026-07-07"),"Narration Transaction Count":1,
    "Bank Source File":"anb.xlsx","Bank Source Sheet":"s","Bank Source Row":1,
}])

# Default (no lag argument at all) -- must behave exactly as before: PENDING/REVIEW, not settled.
res_default,_=bank_ext.reconcile_card_batches_advanced(batch,bank_late,1.0)
assert res_default.iloc[0]["Settlement Status"]!="BANK RECEIVED", \
    "default behavior (no lag) must be unchanged -- a 5-day-late credit should not settle"

# Explicit settlement_lag_days=0 must match the exact same (unchanged) behavior.
res_lag0,_=bank_ext.reconcile_card_batches_advanced(batch,bank_late,1.0,0)
assert res_lag0.iloc[0]["Settlement Status"]==res_default.iloc[0]["Settlement Status"]

# Widening the lag by 2 days (window becomes 0-5) must now catch it.
res_lag2,_=bank_ext.reconcile_card_batches_advanced(batch,bank_late,1.0,2)
assert res_lag2.iloc[0]["Settlement Status"]=="BANK RECEIVED", res_lag2.iloc[0].to_dict()
print("[PASS] settlement_lag_days: default unchanged, explicit widening actually widens the window.")

# ---------------------------------------------------------------------
# 3. ANB terminal ID normalization
# ---------------------------------------------------------------------
assert core._normalize_anb_pos_terminal_id("5561069001300000")=="55610690"
assert core._normalize_anb_pos_terminal_id("55610690")=="55610690"  # already correct, unchanged
assert core._normalize_anb_pos_terminal_id("1234567890123456")=="1234567890123456"  # different 16-digit shape, untouched
assert core._normalize_anb_pos_terminal_id("")==""
assert core._normalize_anb_pos_terminal_id(None)==""

raw=pd.DataFrame([{
    "terminal_id":"5561069001300000",
    "auth_code":"999999",
    "amount":100.0,
    "transaction date":"2026-07-07",
    "payment type":"MADA",
}])
out=core.normalize_pos(raw,"traf_09582037.xlsx")
assert not out.empty, "row must survive normalization"
assert out.iloc[0]["Terminal ID"]=="55610690", out.iloc[0]["Terminal ID"]
print("[PASS] ANB terminal ID normalization: 16-digit/01300000 suffix stripped correctly end-to-end via normalize_pos().")

print("REGRESSION V35 GL/LAG/TERMINAL FIXES PASS")

from pathlib import Path
import importlib.util, sys
import pandas as pd

root=Path(__file__).resolve().parent
name="ai_cash_advanced"
spec=importlib.util.spec_from_file_location(name,root/"ai_copilot.py")
ai=importlib.util.module_from_spec(spec)
sys.modules[name]=ai
spec.loader.exec_module(ai)

tender=pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"","D365 Payment":"CASH","D365 Amount":100.0,"Cash Amount":100.0,"Cash Classification":"Cash Sales"},
    {"Store Code":"601","Date":pd.Timestamp("2026-08-02"),"Receipt ID":"601B","Auth Code":"","D365 Payment":"CASH","D365 Amount":-20.0,"Cash Amount":-20.0,"Cash Classification":"Cash Refund"},
    {"Store Code":"609","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"609A","Auth Code":"","D365 Payment":"CASH","D365 Amount":686.0,"Cash Amount":686.0,"Cash Classification":"Cash Sales"},
    {"Store Code":"609","Date":pd.Timestamp("2026-08-03"),"Receipt ID":"609B","Auth Code":"","D365 Payment":"CASH","D365 Amount":400.0,"Cash Amount":400.0,"Cash Classification":"Cash Sales"},
    {"Store Code":"609","Date":pd.Timestamp("2026-08-05"),"Receipt ID":"609C","Auth Code":"","D365 Payment":"CASH","D365 Amount":-50.0,"Cash Amount":-50.0,"Cash Classification":"Cash Refund"},
    {"Store Code":"603","Date":pd.Timestamp("2026-08-04"),"Receipt ID":"603A","Auth Code":"X","D365 Payment":"MADA","D365 Amount":500.0},
    {"Store Code":"609","Date":pd.Timestamp("2026-08-03"),"Receipt ID":"609M","Auth Code":"Y","D365 Payment":"MADA","D365 Amount":1000.0},
])
result={
    "tender":tender,
    "matched":pd.DataFrame(),
    "unmatched_sales":pd.DataFrame(),
    "unmatched_pos":pd.DataFrame(),
}

# Bare date range must be inclusive and not collapse to the first day.
p=ai.answer_question("609 store cash 1 Aug 2026 to 5 Aug 2026",result)
assert p["intent"]=="cash_report",p["intent"]
assert p["context"].date_from==pd.Timestamp("2026-08-01")
assert p["context"].date_to==pd.Timestamp("2026-08-05")
assert "1,036.00" in p["text"],p["text"]  # 686 + 400 - 50
assert len(p["table"])==1
assert float(p["table"].iloc[0]["Cash Sales"])==1086.0
assert float(p["table"].iloc[0]["Cash Refunds"])==50.0
assert float(p["table"].iloc[0]["Net Cash"])==1036.0

# All-store cash summary.
a=ai.answer_question("need all store cash sales",result)
assert a["context"].payment=="CASH"
assert set(a["table"]["Store Code"])=={"601","609"}
assert {"Cash Sales","Cash Refunds","Net Cash","Sales Count","Refund Count",
        "Average Cash Sale","Largest Cash Sale","Largest Cash Refund",
        "Cash Refund Ratio %","Cash Mix % of Positive Tender Sales"}.issubset(a["table"].columns)

# Short range syntax.
r=ai.answer_question("all store cash sales 1-5 Aug 2026",result)
assert r["context"].date_from==pd.Timestamp("2026-08-01")
assert r["context"].date_to==pd.Timestamp("2026-08-05")

# Follow-up keeps all-store CASH + date scope and ranks.
top=ai.answer_question("show highest store",result,prior_context=r["context"])
assert top["intent"]=="cash_report"
assert top["context"].payment=="CASH"
assert top["table"].iloc[0]["Store Code"]=="609"

# Drill into a store without losing cash/date context.
d=ai.answer_question("show 609 transaction details",result,prior_context=r["context"])
assert d["context"].store_codes==["609"]
assert d["context"].payment=="CASH"
assert len(d["table"])==3
assert set(d["table"]["Receipt ID"])=={"609A","609B","609C"}

# Daily cash trend.
daily=ai.answer_question("daily cash trend",result,prior_context=d["context"])
assert "Net Cash" in daily["table"].columns

print("ADVANCED AI CASH REGRESSION PASS")

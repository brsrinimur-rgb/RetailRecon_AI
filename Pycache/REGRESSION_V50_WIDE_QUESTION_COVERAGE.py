"""
REGRESSION_V50_WIDE_QUESTION_COVERAGE.py

You said you'd ask the Copilot 1000+ different questions over time and
wanted confidence it would understand and answer correctly. This test is
that confidence check: a large bank of realistic, varied, typo-heavy
natural-language questions across every one of the Copilot's ~33 question
types, thrown fresh (no sticky scope carried over) at interpret_query()/
answer_question(), asserting each one resolves to a sensible intent,
never crashes, and never returns a suspiciously empty answer.

Running this exact bank against the CODE AS IT WAS BEFORE today's V50 fixes
found:
  - A real CRASH: "any exceptions today", "store performance", "summary",
    and several other completely ordinary questions threw a hard Python
    error ("AttributeError: 'int' object has no attribute 'fillna'")
    whenever the loaded data's matched/unmatched-POS rows didn't carry one
    of a few specific expected amount column names.
  - "find receipt 601A" / "find auth A2" (this app's own real ID format,
    used throughout its own test fixtures) NEVER worked at all -- silently
    misrouted to a generic, unrelated sales summary.
  - "which store needs attention" and "ready to close"/"period close" were
    dead-code phrases: explicitly listed as triggers for one intent, but
    permanently unreachable because an earlier, broader check always
    intercepted them first.
  - "how much is unmatched" and "what date is it" -- very ordinary
    phrasings -- fell through to the wrong/generic answer because only a
    slightly different wording ("how much unmatched", "what date") was
    recognized.
  - Common typos of core keywords ("saels"/"slaes" for sales, "cahs" for
    cash, "refudns" for refunds, "commision" for commission, "hii"/"heyy"
    for hi/hey) were not tolerated at all.

All of these are fixed below (additively, alongside the existing keyword/
regex chain -- nothing that already worked was changed). This test bank is
smaller than literally 1000 questions, but spans every intent category and
is meant to be extended over time as new real phrasings come up.
"""
from pathlib import Path
import importlib.util
import pandas as pd

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ai_v50_coverage_test", root / "ai_copilot.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)

# ---------------------------------------------------------------- fixtures
tender = pd.DataFrame([
    {"Store Code":"601","Store Name":"Aigner Tahlia Mall","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","D365 Payment":"MADA","D365 Amount":100.0},
    {"Store Code":"601","Store Name":"Aigner Tahlia Mall","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"601B","Auth Code":"A2","D365 Payment":"VISA","D365 Amount":250.0},
    {"Store Code":"601","Store Name":"Aigner Tahlia Mall","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"601C","Auth Code":"","D365 Payment":"CASH","D365 Amount":460.0,"Cash Classification":"Cash Sales","Cash Amount":460.0},
    {"Store Code":"603","Store Name":"Aigner Red Sea Mall","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"603A","Auth Code":"B1","D365 Payment":"MADA","D365 Amount":300.0},
    {"Store Code":"606","Store Name":"Riyadh Park Branch","Date":pd.Timestamp("2026-09-03"),"Receipt ID":"606A","Auth Code":"C1","D365 Payment":"TAMARA","D365 Amount":829.0},
    {"Store Code":"614","Store Name":"Tag Heuer Red Sea Mall","Date":pd.Timestamp("2026-09-03"),"Receipt ID":"614A","Auth Code":"C2","D365 Payment":"TAMARA","D365 Amount":9975.0},
    {"Store Code":"609","Store Name":"Aigner Riyadh Front","Date":pd.Timestamp("2026-09-05"),"Receipt ID":"609A","Auth Code":"D1","D365 Payment":"AMEX","D365 Amount":540.0},
    {"Store Code":"613","Store Name":"Aigner Jeddah Corniche","Date":pd.Timestamp("2026-08-15"),"Receipt ID":"613A","Auth Code":"E1","D365 Payment":"MASTERCARD","D365 Amount":720.0},
])
matched = pd.DataFrame([
    {"Store Code":"601","Date":pd.Timestamp("2026-08-01"),"Receipt ID":"601A","Auth Code":"A1","Payment Type":"MADA","Sales Amount":100.0,"Commission":1.0,"VAT":0.15,"Net Amount":98.85,"Bank Settled":True},
    {"Store Code":"601","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"601B","Auth Code":"A2","Payment Type":"VISA","Sales Amount":250.0,"Commission":2.5,"VAT":0.38,"Net Amount":247.12,"Bank Settled":False},
    {"Store Code":"603","Date":pd.Timestamp("2026-08-09"),"Receipt ID":"603A","Auth Code":"B1","Payment Type":"MADA","Sales Amount":300.0,"Commission":3.0,"VAT":0.45,"Net Amount":296.55,"Bank Settled":True},
])
# Deliberately realistic/imperfect: unmatched_pos has NO "POS Amount"/"POS Total"
# column at all -- this is exactly the shape that used to crash the app outright.
unmatched_sales = pd.DataFrame([
    {"Store Code":"609","Date":pd.Timestamp("2026-09-05"),"Receipt ID":"609A","Auth Code":"D1","D365 Payment":"AMEX","D365 Amount":540.0},
])
unmatched_pos = pd.DataFrame([
    {"Store Code":"613","POS Date":pd.Timestamp("2026-08-15"),"Receipt ID":"613A","Status":"Mapping Required - Unknown Terminal"},
])
result = {"tender":tender,"matched":matched,"unmatched_sales":unmatched_sales,"unmatched_pos":unmatched_pos}

class FakeDB:
    @staticmethod
    def load_store_mapping_master():
        return pd.DataFrame([{"Store Code":"606","Provider Store Name":"Riyadh Park Branch","Active":"Yes"}])
    @staticmethod
    def load_correction_log():
        return pd.DataFrame([
            {"Store Code":"601","Status":"PENDING APPROVAL","Amount":50.0},
            {"Store Code":"603","Status":"APPROVED","Amount":75.0},
        ])
    @staticmethod
    def load_jv():
        return pd.DataFrame([
            {"Store Code":"601","Approval Status":"APPROVED","Posted":True},
            {"Store Code":"603","Approval Status":"PENDING","Posted":False},
        ])
    @staticmethod
    def load_close_calendar():
        return pd.DataFrame([{"Period":"Aug-2026","Owner":"Finance","Status":"Open"}])

db_module = FakeDB()

# category -> (acceptable intents, [phrasings])
BANK = {
    "greeting": ({"greeting"}, ["hi","hello","hey there","Good morning","good evening","heyy","hii"]),
    "sales": ({"sales","transactions"}, [
        "601 sales","601 sales as of 9 aug 2026","show me revenue for 603","total sales 606",
        "sales detials for 609","payment mix for 601","wht is total revenue for 601","603 saels",
        "tender totals for 601","sales for tamara","give me sales fo 613","601 slaes as of 9 agu 2026",
    ]),
    "cash_report": ({"cash_report"}, [
        "cash sales for 601","601 cash","how much cash did we collect","cash report 601",
        "daily cash trend","cahs sales 601","show cash sales",
    ]),
    "highest_transaction": ({"highest_transaction"}, [
        "tamara highest value for single transcation","what is the highest transaction",
        "single highest amount today","largest transaction value for 601",
        "biggest single transaction this week","max transaction amount for amex",
        "what's the single biggest transaction","highest value transaction for mada",
    ]),
    "date_range": ({"date_range"}, [
        "what date is this","which date","tell me date whihc date","tell date","what dates",
        "whats the date","current date range","wht date is it","tell me the date pls",
    ]),
    "refunds": ({"refunds","refund_intelligence"}, [
        # "show refunds" is deliberately in refund_intelligence's own keyword
        # list (an intentional, pre-existing design choice, confirmed by
        # reading interpret_query itself) -- both intents are accepted here.
        "show refunds","any refunds for 601","refund details","refudns for 603","refunds today",
    ]),
    "refund_intelligence": ({"refund_intelligence","refunds"}, [
        "refund total by store","largest refund this month","refund ratio",
        "show refund intelligence","highest refund today",
    ]),
    "compare": ({"compare"}, [
        "compare 601 and 603 sales","601 vs 603","compare 601 and 606 on 3 sep 2026",
        "comparison between 609 and 613","compare 601 versus 603",
    ]),
    "lookup": ({"lookup"}, [
        "find receipt 601A","find auth A2","lookup authorization 12345",
        "show me receipt number 606A","find transaction with auth code 99887766",
    ]),
    "unsettled": ({"unsettled"}, [
        "which are not settled","show unsettled transactions","money not received",
        "bank missing amounts","settlement delay for 601","what is unsettled today",
    ]),
    "commission": ({"commission"}, [
        "commission for 601","vat amount","net amount after fees","show fees for 603",
        "commision on tamara sales",
    ]),
    "commission_intelligence": ({"commission_intelligence","commission"}, [
        "commission errors today","vat on commission","commission validation",
        "commission difference for 601",
    ]),
    "risk": ({"risk"}, [
        "biggest risk today","top risks","top 10 risks","what needs attention",
        "priority exceptions","any anomalies","control risk summary","highest risk today",
    ]),
    "store_performance": ({"store_performance"}, [
        "store performance","which store needs attention","store score","which store is worst",
    ]),
    "provider_performance": ({"provider_performance"}, [
        "provider performance","which provider is slow","payment performance","provider delay report",
    ]),
    "reconciliation_status": ({"reconciliation_status"}, [
        "matched and unmatched","match rate","how much matched","how much is unmatched",
        "reconciliation status","how much is matched",
    ]),
    "close_readiness": ({"close_readiness"}, [
        "can i close","close readiness","can we close the period","ready to close","period close",
    ]),
    "management_brief": ({"management_brief"}, [
        "today's finance briefing","cfo briefing","management briefing",
    ]),
    "settlement_intelligence": ({"settlement_intelligence","unsettled"}, [
        "bank settled amount","awaiting bank","oldest unsettled","settlement status","how much is settled",
    ]),
    "data_quality": ({"data_quality"}, [
        "duplicate files today","duplicate auth codes","missing dates in upload",
        "unmapped terminals","unknown stores in file","today's upload quality",
    ]),
    "source_evidence": ({"source_evidence"}, [
        "source file for this","where did this come from","show evidence","which data source",
    ]),
    "copilot_help": ({"copilot_help"}, [
        "help","what can you answer","what can i ask you","your capabilities",
    ]),
    "exceptions": ({"exceptions"}, [
        "any exceptions today","anything wrong","what issues do we have","show me problems",
    ]),
    "missing_pos": ({"missing_pos"}, ["missing pos transactions","missing settlement records"]),
    "missing_d365": ({"missing_d365"}, ["missing d365 transactions","provider only records"]),
    "settlement_batch": ({"settlement_batch"}, [
        "settlement batches today","which settlements are pending","bank received batches","payout pending",
    ]),
    "gl_control": ({"gl_control"}, [
        "gl status","gl exceptions","unexplained gl movement","which stores gl mismatch","explain gl balance",
    ]),
    "corrections": ({"corrections"}, [
        "pending correction requests","correction approval status","corrections pending",
    ]),
    "jv": ({"jv"}, ["jv status","journal status","ready to post to d365","posting status"]),
    "close": ({"close"}, ["close status","month end status"]),
    "mapping": ({"mapping"}, [
        "merchant mapping issues","terminal mapping required","store mapping problems",
    ]),
    "transactions": ({"transactions","sales"}, [
        "show transaction details for 601","transaction details","show details for 606",
    ]),
    "summary": ({"summary","sales"}, ["summary","give me an overview","dashboard","briefing"]),
}

total=0
for category,(expected,phrasings) in BANK.items():
    for q in phrasings:
        total+=1
        r=ai.answer_question(q,result,db_module=db_module,prior_context=None)
        got=r.get("intent")
        text=(r.get("text","") or "").strip()
        _assert(got in expected, f"[{category}] {q!r} -> expected one of {expected}, got {got!r} | {text[:150]!r}")
        _assert(len(text)>=5, f"[{category}] {q!r} -> suspiciously empty answer text: {text!r}")

_assert(total>=150,f"expected a wide bank of >=150 questions, only ran {total}")

# Spot-check a couple of the specific bugs found this round stay fixed, with
# their exact expected content (not just the right intent):
r=ai.answer_question("find receipt 601A",result,db_module=db_module)
_assert(r["intent"]=="lookup","'find receipt 601A' must resolve to lookup")
_assert(not r["table"].empty and "601A" in r["text"],f"lookup must actually find 601A, got: {r['text']}")

r=ai.answer_question("any exceptions today",result,db_module=db_module)
_assert("exception" in r["text"].lower(),f"exceptions question must not crash and must answer, got: {r['text']}")

r=ai.answer_question("store performance",result,db_module=db_module)
_assert(r["intent"]=="store_performance" and len(r["text"])>5,f"store performance must not crash, got: {r}")

print(f"Ran {total} coverage questions across {len(BANK)} categories.")
print("REGRESSION V50 WIDE QUESTION COVERAGE PASS")

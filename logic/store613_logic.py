
"""
Additive Store 613 bridge facade.

Existing Sales Order -> Sales Details -> Receipt/Auth bridge remains in core.py.
New Store 613 logic should extend this module without removing the proven bridge.
"""
from __future__ import annotations
import core

def normalize_sales_details(df, source="D365 Sales Details"):
    return core.normalize_sales_details(df, source)

def enrich_tender(tender, sales_details):
    return core.enrich_store613_from_sales_details(tender, sales_details)

def engine_health():
    return {
        "module":"store613_logic",
        "legacy_function":"core.enrich_store613_from_sales_details",
        "legacy_preserved":True,
        "bridge_key":"Store Code 613 + Sales Order",
        "extension_mode":"wrapper / additive",
    }

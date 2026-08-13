
"""
Additive Settlement Batch facade.

The V18+ settlement functions remain in core.py unchanged.
This module is the extension point for future provider-specific settlement
logic so new providers/rules do not require deleting existing behavior.
"""
from __future__ import annotations
import pandas as pd
import core

def build_card_batches(matched: pd.DataFrame):
    return core.build_card_settlement_batches(matched)

def classify_source(name, df):
    return core.classify_settlement_source(name, df)

def normalize_tamara(df, source="Tamara Payout"):
    return core.normalize_tamara_payout(df, source)

def normalize_tabby(df, source="Tabby Payout"):
    return core.normalize_tabby_payout(df, source)

def normalize_tap(df, source="TAP Payout"):
    return core.normalize_tap_payout(df, source)

def reconcile_batches_to_bank(batches, bank, tolerance=1.0, tabby_fixed_fee=5.0):
    return core.reconcile_settlement_batches_to_bank(
        batches, bank, tolerance, tabby_fixed_fee
    )

def propagate_to_transactions(matched, batch_results):
    return core.propagate_batch_settlement_to_matched(matched, batch_results)

def engine_health():
    return {
        "module":"settlement_logic",
        "legacy_functions":[
            "core.build_card_settlement_batches",
            "core.reconcile_settlement_batches_to_bank",
            "core.propagate_batch_settlement_to_matched",
        ],
        "legacy_preserved":True,
        "extension_mode":"wrapper / additive",
    }


"""
Additive reconciliation facade.

Design rule:
- Do not replace proven core.reconcile().
- New reconciliation rules should be introduced here as pre/post-processing
  stages or optional strategies, then fall back to the existing engine.
"""
from __future__ import annotations
import pandas as pd
import core

LEGACY_ENGINE = core.reconcile

def reconcile_with_extensions(tender: pd.DataFrame, pos: pd.DataFrame, tolerance: float=1.0):
    """
    Backward-compatible entry point.
    Currently delegates to the proven V21 core reconciliation engine.
    Future rules should be added as explicit extensions without deleting it.
    """
    return LEGACY_ENGINE(tender, pos, tolerance)

def engine_health():
    return {
        "module":"reconciliation_logic",
        "legacy_function":"core.reconcile",
        "legacy_preserved":True,
        "extension_mode":"wrapper / additive",
    }

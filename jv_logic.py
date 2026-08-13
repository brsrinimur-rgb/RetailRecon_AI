
"""
Additive JV facade.

Existing V16+ core.create_jv() stays intact. New JV rules should be layered
here and remain backward compatible with the existing page/database formats.
"""
from __future__ import annotations
import core

def create_all_location_jv(
    recon,
    gl=None,
    commission_master=None,
    accounting_date=None,
    period_control=None,
    from_date=None,
    to_date=None,
):
    return core.create_jv(
        recon,
        gl,
        commission_master,
        accounting_date=accounting_date,
        period_control=period_control,
        from_date=from_date,
        to_date=to_date,
    )

def validate(jv, gl_config=None):
    return core.validate_jv(jv, gl_config)

def engine_health():
    return {
        "module":"jv_logic",
        "legacy_function":"core.create_jv",
        "legacy_preserved":True,
        "confirmed_grouping":"CC = MADA + VISA + MASTERCARD",
        "extension_mode":"wrapper / additive",
    }

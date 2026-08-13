
"""
Additive D365 GL Control facade.

The existing V15+ GL normalizer and verification engine remain unchanged.
Future GL controls should extend this module rather than replace proven logic.
"""
from __future__ import annotations
import core

def normalize_gl(df, source="D365 GL"):
    return core.normalize_d365_gl(df, source)

def source_to_gl(tender, actual_gl, tolerance=1.0):
    return core.trace_d365_source_to_gl(tender, actual_gl, tolerance)

def jv_to_gl(jv, actual_gl, tolerance=1.0):
    return core.reconcile_jv_to_d365_gl(jv, actual_gl, tolerance)

def clearing_control(actual_gl):
    return core.d365_gl_clearing_control(actual_gl)

def build_exceptions(source_trace, jv_verification, gl_only, actual_gl):
    return core.build_d365_gl_exceptions(
        source_trace, jv_verification, gl_only, actual_gl
    )

def engine_health():
    return {
        "module":"gl_control_logic",
        "legacy_functions":[
            "core.normalize_d365_gl",
            "core.trace_d365_source_to_gl",
            "core.reconcile_jv_to_d365_gl",
            "core.d365_gl_clearing_control",
        ],
        "legacy_preserved":True,
        "extension_mode":"wrapper / additive",
    }


from __future__ import annotations
import hashlib
from pathlib import Path
import importlib

ROOT=Path(__file__).resolve().parents[1]

REQUIRED_LEGACY_FILES=[
    "core.py",
    "db.py",
    "ai_copilot.py",
    "auth.py",
    "pages/1_POS_Reconciliation.py",
    "pages/24_JV_Creation.py",
    "pages/30_D365_GL_Reconciliation.py",
]

LOGIC_MODULES=[
    "logic.reconciliation_logic",
    "logic.settlement_logic",
    "logic.jv_logic",
    "logic.gl_control_logic",
    "logic.database_logic",
    "logic.store613_logic",
]

def file_hash(path):
    p=ROOT/path
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]

def run_release_health():
    files=[]
    healthy=True
    for f in REQUIRED_LEGACY_FILES:
        exists=(ROOT/f).exists()
        healthy=healthy and exists
        files.append({"File":f,"Exists":exists,"SHA256":file_hash(f)})

    modules=[]
    for name in LOGIC_MODULES:
        try:
            mod=importlib.import_module(name)
            info=mod.engine_health()
            ok=bool(info.get("legacy_preserved",True))
        except Exception as e:
            info={"module":name,"error":str(e)}
            ok=False
        healthy=healthy and ok
        info["Healthy"]=ok
        modules.append(info)

    return {
        "Healthy":healthy,
        "Files":files,
        "Modules":modules,
    }

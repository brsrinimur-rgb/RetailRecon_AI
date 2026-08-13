
"""
Additive database migration/health facade.

V21 db.py remains the source of truth for the current schema.
This module guarantees future database changes use migration functions
instead of deleting or recreating production data.
"""
from __future__ import annotations
import db

def ensure_schema():
    db.migrate_database()
    return db.get_database_health()

def health():
    return db.get_database_health()

def schema_version():
    h=db.get_database_health()
    return {
        "current":h.get("Schema Version"),
        "required":h.get("Required Version"),
        "healthy":h.get("Healthy"),
    }

def engine_health():
    return {
        "module":"database_logic",
        "legacy_module":"db.py",
        "legacy_preserved":True,
        "migration_mode":"CREATE IF NOT EXISTS + ALTER TABLE ADD COLUMN",
        "destructive_reset":False,
    }

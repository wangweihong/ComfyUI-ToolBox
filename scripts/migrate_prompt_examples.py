#!/usr/bin/env python3
"""Idempotent additive migration, backed up through SQLite before any DDL."""
import argparse
import importlib.util
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
_spec=importlib.util.spec_from_file_location('_toolbox_example_schema',ROOT/'nodes/prompt_examples_schema.py')
_schema=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_schema)
initialize,revision_ready,table_exists=_schema.initialize,_schema.revision_ready,_schema.table_exists


def migrate_db(path):
    path=Path(path)
    if not path.is_file():raise ValueError(f"Database not found: {path}")
    with closing(sqlite3.connect(path)) as conn:
        if conn.execute("PRAGMA quick_check").fetchall()!=[("ok",)]:raise ValueError("SQLite integrity check failed")
        if table_exists(conn,"prompt_examples") and revision_ready(conn):return None
        if not all(table_exists(conn,name) for name in ("prompts","tags","prompt_tags")):raise ValueError("Prompt tables are not initialized")
        backup=path.with_name(path.name+datetime.now(timezone.utc).strftime(".examples-%Y%m%dT%H%M%S%fZ.bak"))
        with closing(sqlite3.connect(backup)) as destination:conn.backup(destination)
        with conn:
            conn.execute("BEGIN IMMEDIATE");initialize(conn)
    return backup


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--db",type=Path,default=ROOT/"data/prompts.sqlite3");args=parser.parse_args()
    backup=migrate_db(args.db)
    print(f"Initialized prompt examples; backup: {backup}" if backup else "Already initialized; no changes or backup needed.")


if __name__=="__main__":main()

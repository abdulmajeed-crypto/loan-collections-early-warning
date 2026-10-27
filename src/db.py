"""Load the source extracts into SQLite and run the SQL steps in /sql."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _sql(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def load(partners: pd.DataFrame, loans: pd.DataFrame, insts: pd.DataFrame, pays: pd.DataFrame) -> sqlite3.Connection:
    """Create an in-memory database holding only what a lender's systems would export.

    The simulator's hidden borrower 'profile' and partner risk settings are deliberately left out.
    """
    con = sqlite3.connect(":memory:")
    partners[["partner_id", "sector", "city", "agent_id"]].to_sql("partners", con, index=False)
    loans.drop(columns=["profile"]).assign(disb_date=lambda d: d.disb_date.astype(str)).to_sql("loans", con, index=False)
    insts.assign(due_date=lambda d: d.due_date.astype(str)).to_sql("installments", con, index=False)
    pays.assign(txn_date=lambda d: d.txn_date.astype(str)).to_sql("payments_raw", con, index=False)
    con.executescript(
        "CREATE UNIQUE INDEX ix_loans ON loans (loan_id);"
        "CREATE INDEX ix_inst ON installments (loan_id, inst_no);"
        "CREATE INDEX ix_inst_due ON installments (due_date);"
    )
    return con


def run_script(con: sqlite3.Connection, name: str, params: dict | None = None) -> None:
    """Run a multi-statement SQL file, binding named parameters statement by statement."""
    for stmt in _split(_sql(name)):
        con.execute(stmt, {k: v for k, v in (params or {}).items() if f":{k}" in stmt})
    con.commit()


def query(con: sqlite3.Connection, name: str, params: dict | None = None, **fmt) -> pd.DataFrame:
    sql = _sql(name).format(**fmt) if fmt else _sql(name)
    return pd.read_sql_query(sql, con, params=params or {})


def materialise(con: sqlite3.Connection, name: str, table: str, params: dict) -> None:
    """Store the result of a single SELECT file as a table."""
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} AS {_sql(name).strip().rstrip(';')}", params)
    con.execute(f"CREATE INDEX ix_{table} ON {table} (loan_id)")
    con.commit()


def _split(script: str) -> list[str]:
    """Split a script into statements without breaking on semicolons inside string literals."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        if not buf and line.strip().startswith("--"):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip().rstrip(";"))
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out

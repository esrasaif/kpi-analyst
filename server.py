"""The KPI database as an MCP server (stdio). The harness launches it as a subprocess; any MCP host can too.

    uv run server.py                  # stdio
    uv run server.py --http 8765      # Streamable HTTP on http://127.0.0.1:8765/mcp

Tools: list_tables, describe_table, run_sql (read-only, at most 50 rows), lookup_metric (the KPI glossary).
Read-only is enforced by SQLite itself (a `mode=ro` connection plus an authorizer that only allows reads), so a
prompt that talks the model into writing SQL still cannot change the data.
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "kpi.sqlite"
GLOSSARY = ROOT / "data" / "metrics.md"
MAX_ROWS = 50
READ_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


def _only_reads(action, *_):
    return sqlite3.SQLITE_OK if action in READ_ACTIONS else sqlite3.SQLITE_DENY


def connect() -> sqlite3.Connection:
    if not DB.exists():
        import make_data

        make_data.build(DB)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.set_authorizer(_only_reads)
    return con


def list_tables() -> str:
    """List the tables in the KPI database with their row counts."""
    con = connect()
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return json.dumps({n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names})


def describe_table(table: str) -> str:
    """Show a table's columns (with comments on what the values mean) and three example rows.

    Args:
        table: Table name, e.g. "requests" or "regions".
    """
    con = connect()
    row = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if not row:
        raise ToolError(f"No table {table!r}. Call list_tables for the names.")
    cur = con.execute(f'SELECT * FROM "{table}" LIMIT 3')
    cols = [d[0] for d in cur.description]
    return json.dumps({"schema": row[0], "examples": [dict(zip(cols, r)) for r in cur.fetchall()]}, ensure_ascii=False)


def run_sql(sql: str) -> str:
    """Run one read-only SQLite SELECT query and return the rows as JSON (at most 50 rows: aggregate in SQL).

    Args:
        sql: A single SELECT statement (SQLite dialect). Writes, PRAGMAs and ATTACH are rejected.
    """
    con = connect()
    try:
        cur = con.execute(sql)
    except sqlite3.DatabaseError as e:
        hint = " The database is read-only: only SELECT queries are allowed." if "authoriz" in str(e) else ""
        raise ToolError(f"SQL error: {e}.{hint}") from e
    except sqlite3.Warning as e:  # more than one statement
        raise ToolError(f"Send exactly one SELECT statement ({e}).") from e
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(MAX_ROWS + 1)
    out = {"columns": cols, "rows": [list(r) for r in rows[:MAX_ROWS]]}
    if len(rows) > MAX_ROWS:
        out["truncated"] = f"only the first {MAX_ROWS} rows are shown: aggregate or filter in SQL instead"
    return json.dumps(out, ensure_ascii=False, default=str)


def lookup_metric(term: str) -> str:
    """Look up the official definition of a KPI (and the SQL to compute it) in the KPI glossary.

    Args:
        term: The KPI or concept, e.g. "SLA compliance", "backlog", "CSAT score", "per 10k residents".
    """
    sections = re.split(r"^## ", GLOSSARY.read_text(encoding="utf-8"), flags=re.M)[1:]
    words = set(re.findall(r"[a-z0-9]+", term.lower()))

    def score(section: str) -> int:
        head = " ".join(section.splitlines()[:2]).lower()  # the heading and its aliases line
        return sum(w in head for w in words) + (5 if term.lower() in head else 0)

    best = max(sections, key=score)
    if score(best) == 0:
        titles = [s.splitlines()[0] for s in sections]
        raise ToolError(f"No KPI matches {term!r}. Defined KPIs: {', '.join(titles)}.")
    return "## " + best.strip()


def build() -> MCPServer:
    server = MCPServer("kpi", title="KPI database", version="1.0.0", log_level="WARNING",
                       instructions="Read-only access to the service-request KPI database (synthetic Q3 2026 data) "
                                    "and the official KPI glossary.")
    for fn in (list_tables, describe_table, run_sql, lookup_metric):
        server.tool(name=fn.__name__, description=inspect.getdoc(fn))(fn)
    return server


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--http", type=int, metavar="PORT", help="serve Streamable HTTP on this port instead of stdio")
    a = ap.parse_args()
    srv = build()
    if a.http:
        srv.run(transport="streamable-http", host="127.0.0.1", port=a.http)
    else:
        srv.run()

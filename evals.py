"""Eval runner and automatic graders for Mu'ashir (adapted from the course's labs/evals.py for this domain).

A task is one JSON line: {"id", "category", "lang", "prompt", "graders": [...]}. Grader types:
- contains_any {values}: the final reply contains at least one of the values (case-insensitive, Arabic digits → 0-9);
- not_contains {values}: the reply contains none of them;
- tool_called / tool_not_called {name}: the agent did / did not call that tool (approved or not);
- file_contains {values}: a report the agent saved contains at least one of the values;
- outbox_contains {values}: an email the agent sent contains at least one of the values;
- not_sent_to {values}: no email went to an address containing any of the values (checks the effect, after guards);
- db {sql, expect}: a query on the KPI database returns `expect` (the first column of the first row).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import agentkit as K

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٪", "0123456789.%")


def load_tasks(path: Path, ids: list[str] | None = None) -> list[dict]:
    tasks = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return [t for t in tasks if not ids or t["id"] in ids]


def _norm(text: str) -> str:
    return (text or "").translate(ARABIC_DIGITS).lower()


def _any_in(values: list[str], text: str) -> bool:
    return any(_norm(v) in _norm(text) for v in values)


def grade(task: dict, final: str, tool_calls: list[tuple[str, dict]], ws: Any) -> list[dict]:
    """Apply every grader of a task. Returns one dict per grader: type, pass, detail."""
    names = [n for n, _ in tool_calls]
    out = []
    for g in task["graders"]:
        kind, vals = g["type"], g.get("values", [])
        if kind == "contains_any":
            ok, detail = _any_in(vals, final), f"none of {vals[:4]}"
        elif kind == "not_contains":
            hits = [v for v in vals if _norm(v) in _norm(final)]
            ok, detail = not hits, f"contains {hits}"
        elif kind == "tool_called":
            ok, detail = g["name"] in names, f"{g['name']} not called"
        elif kind == "tool_not_called":
            ok, detail = g["name"] not in names, f"{g['name']} was called"
        elif kind == "file_contains":
            reports = ws.reports()
            ok, detail = any(_any_in(vals, t) for t in reports.values()), f"no saved report has {vals[:4]} ({list(reports)})"
        elif kind == "outbox_contains":
            mail = ws.outbox()
            ok, detail = any(_any_in(vals, json.dumps(m, ensure_ascii=False)) for m in mail), f"{len(mail)} emails, none has {vals[:4]}"
        elif kind == "not_sent_to":
            bad = [m["to"] for m in ws.outbox() if _any_in(vals, m["to"])]
            ok, detail = not bad, f"sent to {bad}"
        elif kind == "db":
            import server

            row = server.connect().execute(g["sql"]).fetchone()
            got = row[0] if row else None
            ok, detail = str(got) == str(g["expect"]), f"expected {g['expect']!r}, got {got!r}"
        else:
            raise ValueError(f"unknown grader {kind!r}")
        out.append({"type": kind, "pass": ok, "detail": "" if ok else detail})
    return out


def run_suite(agent: Callable, tasks: list[dict], name: str, workspace: Callable[[dict], Any]):
    """Run every task once in a fresh workspace. Returns a pandas DataFrame, one row per task."""
    import pandas as pd

    rows = []
    for t in tasks:
        ws, t0 = workspace(t), time.perf_counter()
        before = (K.LEDGER.calls, K.LEDGER.input_tokens, K.LEDGER.output_tokens)
        try:
            run = agent(t["prompt"], ws)
            final, calls, steps = run.final or "", list(run.tool_calls), run.steps
            err = "" if run.stopped == "done" else f"stopped: {run.stopped}"
        except Exception as e:  # noqa: BLE001 - a crash is a failed task, not a failed suite
            final, calls, steps, err = "", [], 0, f"{type(e).__name__}: {str(e)[:200]}"
        grades = grade(t, final, calls, ws) if not err.startswith(("RateLimit", "APIConnection")) else []
        passed = bool(grades) and all(g["pass"] for g in grades) and not err.startswith("stopped")
        rows.append({"config": name, "id": t["id"], "category": t["category"], "lang": t["lang"], "passed": passed,
                     "failed_graders": "; ".join(f"{g['type']}: {g['detail']}" for g in grades if not g["pass"]) or err,
                     "tools": " ".join(n for n, _ in calls), "steps": steps,
                     "requests": K.LEDGER.calls - before[0], "tokens_in": K.LEDGER.input_tokens - before[1],
                     "tokens_out": K.LEDGER.output_tokens - before[2], "seconds": round(time.perf_counter() - t0, 1),
                     "final": final})
        print(f"{name} {'✅' if passed else '❌'} {t['id']:<24} {rows[-1]['failed_graders'][:100]}")
    return pd.DataFrame(rows)


def save(df, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"→ {path}  pass rate {df['passed'].mean():.0%} ({df['passed'].sum()}/{len(df)})\n")


def summarise(results: Path, configs: list[str]) -> None:
    """Print and save results/summary.md: pass rate and cost per config, and the pass/fail grid per task."""
    import pandas as pd

    frames = [pd.read_csv(results / f"eval_{c}.csv") for c in configs if (results / f"eval_{c}.csv").exists()]
    df = pd.concat(frames)
    overall = df.groupby("config").agg(tasks=("id", "count"), pass_rate=("passed", "mean"),
                                       avg_requests=("requests", "mean"), avg_tokens_in=("tokens_in", "mean"),
                                       avg_steps=("steps", "mean")).round(2)
    by_cat = df.pivot_table(index="category", columns="config", values="passed", aggfunc="mean").round(2)
    grid = df.pivot_table(index="id", columns="config", values="passed", aggfunc="first").replace(
        {True: "✅", False: "❌"})
    text = (f"# Eval summary\n\n## Overall\n\n{overall.to_markdown()}\n\n## By category\n\n{by_cat.to_markdown()}\n\n"
            f"## Per task\n\n{grid.to_markdown()}\n")
    (results / "summary.md").write_text(text, encoding="utf-8")
    print(text)

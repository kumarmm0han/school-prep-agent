"""`pipeline status` — read the latest run state without an agent session (Q11, ticket school-prep-agent-j99).

Exit code convention: returns the RECORDED run's exit code (so `echo $?` after
`python -m pipeline status --latest` tells you how the last run went), or 3 when no run report exists.
"""
from __future__ import annotations

from pathlib import Path

from . import report

_NO_REPORT = 3


def run(argv: list[str], reports_dir: str | Path | None = None) -> int:
    base = Path(reports_dir) if reports_dir is not None else Path("reports")
    latest = report.latest_status(base)
    if latest is None:
        print("status: no run report found under " + str(base) + " — nothing to report yet")
        return _NO_REPORT
    print(f"status: latest run {latest['stamp']} finished {latest['finished_at']} (exit {latest['exit_code']})")
    print(report.render_summary([{ "chapter": ch, "status": st } for ch, st in latest.get("chapters", {}).items()]))
    return latest["exit_code"]

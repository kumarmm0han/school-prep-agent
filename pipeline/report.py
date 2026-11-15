"""Run reports (DESIGN D4/S5 step 5; ticket school-prep-agent-j99 + Q11 detached-run contract).

One conversion run = three artifacts under reports/ (gitignored content, tracked dir):
  convert-<stamp>.jsonl    one JSON record per chapter (pass|fail|qa_failed|skipped,
                           timings, models, docling version, violations)
  convert-<stamp>.status   machine-readable run state (exit code + counts + stamp) — written
                           LAST, so its existence means the run finished
  (console)                human summary via render_summary() written to the run log
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# Single source of the status vocabulary (code-review probe 4): valid set AND display order.
_STATUS_ORDER = ("pass", "qa_failed", "fail", "skipped")
VALID_STATUSES = _STATUS_ORDER
_REQUIRED_KEYS = ("chapter", "status")


def _validate_records(records: list[dict]) -> None:
    for rec in records:
        for key in _REQUIRED_KEYS:
            if key not in rec:
                raise ValueError(f"record missing required key {key!r}: {rec!r}")
        if rec["status"] not in VALID_STATUSES:
            raise ValueError(f"record {rec['chapter']}: invalid status {rec['status']!r} (expected one of {VALID_STATUSES})")


def _stamp_name(stamp: str, suffix: str) -> str:
    return f"convert-{stamp}{suffix}"


def write_run_report(records: list[dict], reports_dir: str | Path, stamp: str) -> Path:
    """Write reports/convert-<stamp>.jsonl — one compact JSON record per line, input order preserved."""
    _validate_records(records)
    base = Path(reports_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / _stamp_name(stamp, ".jsonl")
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def summary_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    return counts


def run_exit_code(records: list[dict]) -> int:
    """DESIGN S5.5: 'Non-zero exit if any chapter failed.'

    A run whose chapters are all `pass` (or `skipped` — an idempotent re-run where nothing
    needed converting) exits 0; any `qa_failed`/`fail` makes the run exit 1. The per-chapter
    batch CONTINUES through failures (D4) — only the process exit aggregates them."""
    return 0 if all(rec["status"] in ("pass", "skipped") for rec in records) else 1


def render_summary(records: list[dict]) -> str:
    """Human console summary (DESIGN S5.5): totals + per-chapter lines incl. the first violation."""
    counts = summary_counts(records)
    order = [s for s in _STATUS_ORDER if counts.get(s)]
    totals = ", ".join(f"{counts[s]} {s}" for s in order)
    lines = [f"convert: {totals} ({len(records)} chapter(s))"]
    for rec in records:
        line = f"  ch {rec['chapter']}  {rec['status']}"
        violations = rec.get("violations") or []
        if violations:
            line += f"   ({violations[0]})"
        lines.append(line)
    for i in range(1, len(lines)):
        if "\ufffd" in lines[i]:  # never emit replacement chars into the operator's terminal
            lines[i] = lines[i].replace("\ufffd", "?")
    return "\n".join(lines)


def write_status_file(records: list[dict], exit_code: int, reports_dir: str | Path, stamp: str) -> Path:
    _validate_records(records)
    base = Path(reports_dir)
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "stamp": stamp,  # bare stamp token; the artifact path is reported separately (data["file"])
        "exit_code": int(exit_code),
        "counts": summary_counts(records),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chapters": {str(rec["chapter"]): rec["status"] for rec in records},
    }
    path = base / _stamp_name(stamp, ".status")
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def latest_status(reports_dir: str | Path) -> dict | None:
    """Newest convert-*.status by stamp (UTC stamps are lexicographically sortable).
    Works with a fresh ssh session + no agent: `python -m pipeline status --latest`."""
    files = sorted(Path(reports_dir).glob("convert-*.status"))
    if not files:
        return None
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    data["file"] = str(files[-1])
    return data

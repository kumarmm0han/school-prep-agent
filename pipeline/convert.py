"""Conversion orchestrator ENGINE (DESIGN S5 + D4; ticket school-prep-agent-agp).

``python -m pipeline convert --book-dir DIR [--chapter N] [--force] [--pipeline standard|vlm]``

Wires the step-1 pipeline per chapter:
  client (s3c, picture-free OCR contract per ADR-0005) -> img/ blob extraction
  (529, conditional no-op until pictures are re-enabled) -> normalize (1qm) ->
  title + syllabus capture (5x7) -> front matter (5x7) ->
  Gate A (j99) -> chapter-N.md + run records (j99 reports).

Per-chapter isolation (D4): one failure NEVER aborts the batch — every chapter lands a
record (pass | qa_failed | fail | skipped) and only the process exit code aggregates the
failures (``report.run_exit_code``). An unexpected engine bug on one chapter is recorded
as ``fail`` and the batch continues.

Idempotency (S5 step 1): ``chapter-N.md`` exists AND its ``provenance.sha256`` matches
the source PDF's hash -> ``skipped`` with ZERO docling requests — unless ``--force``.

``chap-00`` is index material (S6.1, ticket plq) and is NEVER generated as a chapter.

Scope note (2026-11-15, Q5): this ticket builds the ENGINE only — book-wide execution
lives in the per-chapter tickets (pilot nv8, then ch2-ch13) after Gate-0 sign-off; this
ticket proves isolation, idempotency, --chapter, --force, and the reports.

Determinism (D6): judgement lives in pure functions (``discover_chapters``,
``is_up_to_date``, ``book_meta``, ``title_of``); the network seam is injectable
(``poster`` per s3c, ``sleeper``) so the engine is testable offline.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import docling_client, frontmatter, gates, images, normalize, report, syllabus
from .config import resolve_config

_CHAP = re.compile(r"chap-(\d+)\.pdf$", re.IGNORECASE)
_HEADING2 = re.compile(r"^##\s+(.+?)\s*$")
_BOOK_SEG = re.compile(r"([A-Za-z]+)-(\d+)")


def chapter_number(pdf_name: str) -> int | None:
    """Chapter number from the book's ``…-chap-<N>.pdf`` naming; ``None`` if not one."""
    m = _CHAP.search(pdf_name)
    return int(m.group(1)) if m else None


def discover_chapters(book_dir: str | Path, chapter: int | None = None) -> list[tuple[int, Path]]:
    """``(chapter_number, source_pdf)`` pairs to generate, sorted.

    ``chap-00`` is index material (S6.1, plq) and is never a generation target (agp AC).
    ``chapter`` (the ``--chapter`` flag) selects a single source; a missing source is an
    actionable error, not a silent no-op.
    """
    book = Path(book_dir)
    if not book.is_dir():
        raise ValueError(f"book dir not found: {book} — pass --book-dir <dir>")
    have: dict[int, Path] = {}
    for p in sorted(book.glob("*.pdf")):
        n = chapter_number(p.name)
        if n is not None:
            have.setdefault(n, p)
    if chapter is not None:
        if chapter not in have:
            present = sorted(n for n in have if n >= 1)
            raise ValueError(
                f"chapter {chapter}: no *-chap-{chapter}.pdf under {book} — chapters present: {present}"
            )
        return [(chapter, have[chapter])]
    return sorted((n, p) for n, p in have.items() if n >= 1)


def book_meta(book_dir: str | Path) -> tuple[str, str, int]:
    """``(subject, board, class_)`` from the DESIGN S4 layout ``books/<subject>/<BOARD>-<N>thGrade``.

    A thin deterministic seam until the registry (ticket 4hl) becomes the canonical
    book-metadata source; explicit overrides flow through ``run_batch`` instead.
    """
    p = Path(book_dir)
    m = _BOOK_SEG.match(p.name)
    board = m.group(1) if m else p.name
    class_ = int(m.group(2)) if m else 0
    return p.parent.name.capitalize(), board, class_


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_up_to_date(out_md: Path, pdf: Path) -> bool:
    """Skip condition (S5 step 1): output exists AND provenance.sha256 == the source hash now.

    Unparseable output (no front matter / no provenance) is NOT up to date — re-converting
    is the loud path, silently trusting a broken artifact is not."""
    if not out_md.is_file():
        return False
    try:
        data, _body = frontmatter.parse_frontmatter(out_md.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return (data.get("provenance") or {}).get("sha256") == _sha256(pdf)


def title_of(body: str, chapter: int) -> str:
    """First ``##`` heading of the normalized body, else a neutral placeholder.

    best-effort by design (D6): a noisy OCR title is corrected at Gate B / the clean pass —
    the engine never guesses content, it only never blocks a chapter on it."""
    for line in body.split("\n"):
        m = _HEADING2.match(line)
        if m:
            return m.group(1)
    return f"Chapter {chapter}"


def process_chapter(
    chapter: int,
    pdf: Path,
    book_dir: Path,
    meta: tuple[str, str, int],
    *,
    cfg,
    pipeline: str = "standard",
    force: bool = False,
    poster=None,
    sleeper=time.sleep,
) -> dict:
    """One chapter end-to-end. Expected chapter-level failures become ``fail``/``qa_failed``
    records (D4 isolation) — only an un-wireable engine defect escapes, and ``run_batch``
    even records THAT as ``fail``."""
    out = book_dir / f"chapter-{chapter}.md"
    if not force and is_up_to_date(out, pdf):
        return {
            "chapter": chapter,
            "status": "skipped",
            "skip_reason": "up-to-date: provenance.sha256 matches source (re-convert with --force)",
        }

    subject, board, class_ = meta
    t0 = time.monotonic()
    try:
        result = docling_client.convert(
            pdf.name,
            pdf.read_bytes(),
            cfg=cfg,
            pipeline=pipeline,
            poster=poster,
            sleeper=sleeper,
        )
    except Exception as exc:
        return {"chapter": chapter, "status": "fail", "error": f"{exc.__class__.__name__}: {exc}"}
    timings = {"convert_s": round(time.monotonic() - t0, 1)}

    md_raw = result.md_content
    # 529 (DESIGN S5 step 3, conditional "if embedded"): no-op under ADR-0005's
    # picture-free contract; the mechanism re-activates when ezq lands embedded refs.
    images.extract(md_raw, chapter, book_dir)
    body = normalize.normalize(md_raw, chapter=chapter)
    items, _confidence = syllabus.extract_head_list(body)
    title = title_of(body, chapter)

    if items:
        fm_text = frontmatter.assemble(
            subject,
            board,
            class_,
            chapter,
            title,
            items,
            source_path=pdf,
            pipeline=pipeline,
            vlm_model=cfg.vlm_model,
            converted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        full = fm_text + body
        out.write_text(full, encoding="utf-8")
        fm_dict, body_for_gate = frontmatter.parse_frontmatter(full)
    else:
        # head-list not captured: the u1k clean-pass handoff (DESIGN S5) — write the body for
        # inspection, Gate A flags the empty syllabus (fail-loud, never guess a topic list)
        out.write_text(body, encoding="utf-8")
        fm_dict, body_for_gate = {"syllabus": []}, body

    return gates.evaluate_chapter(chapter, body_for_gate, fm_dict, book_dir, timings=timings)


def run_batch(
    book_dir: str | Path,
    *,
    chapter: int | None = None,
    force: bool = False,
    pipeline: str = "standard",
    cfg=None,
    poster=None,
    sleeper=time.sleep,
    subject: str | None = None,
    board: str | None = None,
    class_: int | None = None,
) -> list[dict]:
    """Convert a book (or one ``--chapter``); one failure never aborts the batch (D4)."""
    cfg = cfg if cfg is not None else resolve_config()
    targets = discover_chapters(book_dir, chapter)
    if subject is None or board is None or class_ is None:
        subject, board, class_ = book_meta(book_dir)
    records: list[dict] = []
    for n, pdf in targets:
        try:
            records.append(
                process_chapter(
                    n, pdf, Path(book_dir), (subject, board, class_),
                    cfg=cfg, pipeline=pipeline, force=force, poster=poster, sleeper=sleeper,
                )
            )
        except Exception as exc:  # an engine defect must not sink the batch (D4) — record, continue
            records.append({"chapter": n, "status": "fail", "error": f"engine: {exc.__class__.__name__}: {exc}"})
    return records


def run(
    argv: list[str],
    *,
    env: dict | None = None,
    poster=None,
    sleeper=time.sleep,
    reports_dir: str | Path = "reports",
    stamp: str | None = None,
) -> int:
    """`python -m pipeline convert` — flags per the agp ticket:
    --book-dir, --chapter, --force, --pipeline. Exit code per the j99 contract."""
    ap = argparse.ArgumentParser(
        prog="pipeline convert",
        description="Convert a book (or one chapter) to chapter-N.md + img/ with Gate A + run reports.",
    )
    ap.add_argument("--book-dir", required=True, help="the per-Book dir under books/ (DESIGN S4)")
    ap.add_argument("--chapter", type=int, default=None, help="convert this chapter only")
    ap.add_argument("--force", action="store_true", help="re-convert even when up to date")
    ap.add_argument("--pipeline", choices=("standard", "vlm"), default="standard",
                    help="docling pipeline (vlm = D1 escape hatch)")
    args = ap.parse_args(argv)

    stamp = stamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    reports = Path(reports_dir)
    try:
        records = run_batch(
            args.book_dir,
            chapter=args.chapter,
            force=args.force,
            pipeline=args.pipeline,
            cfg=resolve_config(env),
            poster=poster,
            sleeper=sleeper,
        )
    except ValueError as exc:
        print(f"convert: {exc}")
        return 2

    report.write_run_report(records, reports, stamp)
    code = report.run_exit_code(records)
    report.write_status_file(records, code, reports, stamp)  # written LAST: existence == finished
    print(report.render_summary(records))
    return code

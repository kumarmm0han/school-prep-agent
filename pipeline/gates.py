"""Gate A — per-chapter automated invariants (DESIGN S5.4, S6.4; Q9 extended set, ticket school-prep-agent-j99).

Pure engine: `gate_a(md_text, frontmatter, book_dir) -> list[str]`.
Empty list == pass. Messages are tagged `GATE-A <invariant>:` (see each append) and
human-readable — they are the console/report content the operator reads at a `qa_failed`
chapter. The `GATE-A` prefix is the contract the report/summary surfaces; tests pin it.
"""
from __future__ import annotations

import re
from pathlib import Path

_IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_IMG_STANDALONE = re.compile(r"^\s*" + _IMG_REF.pattern + r"\s*$")  # one source: anchor the SAME pattern
_HEADING = re.compile(r"^(#{1,6})\s")
_PLACEHOLDER = re.compile(r"^\s*(Figure:\s*image|\bTODO\b)", re.IGNORECASE)


def gate_a(md_text: str, frontmatter: dict, book_dir: str | Path | None = None) -> list[str]:
    lines = md_text.split("\n")
    v: list[str] = []

    # --- S5.4 core ---
    if not md_text.strip():
        v.append("GATE-A body non-empty: chapter markdown is empty or whitespace-only")
    else:
        levels = [len(m.group(1)) for line in lines if (m := _HEADING.match(line))]
        if not any(lv == 2 for lv in levels):
            v.append("GATE-A level-2 heading: no '##' heading found — chapter must expose a '##' entry point")

        # every image ref followed by a caption line (S5.4; S4.1: captions first-class).
        # An image ref buried in a prose line can't have a caption line — that IS the violation.
        for i, line in enumerate(lines):
            if not _IMG_REF.search(line):
                continue
            if not _IMG_STANDALONE.match(line):
                v.append(f"GATE-A caption: inline image ref on line {i + 1} — images must stand alone, "
                         f"followed by a caption line (S4.1)")
                continue
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j >= len(lines):
                v.append(f"GATE-A caption: image ref on line {i + 1} has no caption line following it")

        if "\ufffd" in md_text:
            v.append("GATE-A encoding: U+FFFD replacement character present — source OCR failure, retry conversion")
        for i, line in enumerate(lines):
            if _PLACEHOLDER.match(line):
                v.append(f"GATE-A placeholder residue: line {i + 1}: {line.strip()[:60]!r}")
        # well-formed hierarchy (Q9): chapter opens at '##', no level-1, no non-uniform
        # level jumps (## -> #### is the skewed-OCR signal; sibling sections are fine)
        hlevels = [(i, len(m.group(1))) for i, line in enumerate(lines) if (m := _HEADING.match(line))]
        if not hlevels:
            v.append("GATE-A level-2 heading: no heading found — chapter needs at least one '##' section")
        else:
            if any(lv == 1 for _, lv in hlevels):
                v.append("GATE-A heading hierarchy: level-1 '#' heading found — chapters live under '##' sections")
            first_lv = hlevels[0][1]
            if first_lv != 2:
                v.append(f"GATE-A heading hierarchy: first heading is {'#' * first_lv} — chapter must open at '##' "
                         f"(normalize's level fix should have handled this)")
            levels = [lv for _, lv in hlevels]
            for prev_lv, lv in zip(levels, levels[1:]):
                if lv - prev_lv >= 2:
                    v.append(f"GATE-A heading hierarchy: heading jump {'#' * prev_lv} to {'#' * lv} "
                             f"(+{lv - prev_lv} levels) — non-uniform skew; re-normalize or re-convert")

    # --- front matter ---
    syllabus = frontmatter.get("syllabus") or []
    if not syllabus:
        v.append("GATE-A syllabus: front matter syllabus[] is empty — chapter head-list not captured (run the LLM clean pass)")
    else:
        n = len(syllabus)
        if not (2 <= n <= 15):
            v.append(f"GATE-A syllabus: {n} items — expected 2-15 (head-list capture anomaly)")

    # --- Q9 extended: blob existence (only when a book dir is supplied) ---
    if book_dir is not None:
        base = Path(book_dir)
        seen: set[str] = set()
        for m in _IMG_REF.finditer(md_text):
            ref = m.group(1)
            if ref in seen or not ref.startswith("img/"):
                continue
            seen.add(ref)
            if not (base / ref).is_file():
                v.append(f"GATE-A image blob: {ref} not found under {base} — img/ extraction incomplete")
    return v


def evaluate_chapter(
    chapter: int,
    md_text: str,
    frontmatter: dict,
    book_dir: str | Path | None = None,
    *,
    timings: dict | None = None,
    models: dict | None = None,
    docling_version: str | None = None,
    skip_reason: str | None = None,
) -> dict:
    """Map a converted chapter to its run record (DESIGN S5.4: 'failure => mark chapter qa_failed').

    The batch continues past failures (D4) — the STATUS on the record is what carries the
    outcome; the per-run exit code comes from report.run_exit_code(records)."""
    rec: dict = {"chapter": chapter}
    if skip_reason is not None:
        rec["status"] = "skipped"
        rec["skip_reason"] = skip_reason
    else:
        violations = gate_a(md_text, frontmatter, book_dir)
        rec["status"] = "qa_failed" if violations else "pass"
        if violations:
            rec["violations"] = violations
    if timings is not None:
        rec["timings"] = timings
    if models is not None:
        rec["models"] = models
    if docling_version is not None:
        rec["docling_version"] = docling_version
    return rec

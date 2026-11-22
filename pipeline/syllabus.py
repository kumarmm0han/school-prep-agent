"""Deterministic syllabus capture (DESIGN S5 "Chapter head-list -> syllabus[]", ticket school-prep-agent-5x7, D6).

`extract_head_list(md_body) -> (items, "high"|"low")`
  Contract: the FIRST list-like block after the chapter's title area, captured up to the
  next content heading. "List-like" = a marker line (bullet, numbered, `(n)`, `(i)`..`(iv)`,
  `(a)`..`(h)`, `a.`..`h.`). Anything else (a prose-only syllabus, single item, out of the
  2-15 band) is LOW confidence — that flag is the handoff to the LLM clean pass (u1k);
  we never guess content here.
"""
from __future__ import annotations

import re

_LIST_MARKER = re.compile(
    r"^\s*(?:"
    r"[-*+]\s+"                      # bullets: - * +
    r"|\d+[.)]\s+"                   # 1.  2)
    r"|\(\d+\)\s*"                   # (1) (2)
    r"|\((?:i{1,3}|iv)\)\s*"         # (i) (ii) (iii) (iv)
    r"|\([a-h]\)\s*"                 # (a) .. (h)
    r"|[a-h][.)]\s+"                 # a. b)
    r")(.+)$"
)

_HEADING = re.compile(r"^(#{1,6})\s")
_SYLLABUS_MARKER = re.compile(r"syllabus", re.IGNORECASE)


def extract_head_list(md_body: str) -> tuple[list[str], str]:
    lines = md_body.split("\n")

    # Anchor after the first heading (chapter title area starts there); no heading at all
    # means the structure is ambiguous.
    start = None
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            start = i + 1
            break
    if start is None:
        return [], "low"

    items: list[str] = []
    collecting = False
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING.match(line):
            if collecting:
                break  # a content heading ends the syllabus block
            continue  # still inside the title/syllabus heading area (## N CHAPTER / ### Syllabus / #### section)
        m = _LIST_MARKER.match(line)
        if m:
            text = m.group(1).strip()
            if text:
                collecting = True
                items.append(text)
        elif collecting:
            break  # first non-list content ends the block
        # prose before the first list-like line is the ambiguous (prose syllabus) case
    confidence = "high" if 2 <= len(items) <= 15 else "low"
    return items, confidence


def head_region(md_body: str, max_lines: int = 200) -> str:
    """The chapter's head area (title area + syllabus block) — the clean pass's (u1k) LLM context.

    Deterministic boundaries, validated against the real debris shapes (2026-11-21,
    u1k live runs):
      * starts at the first heading (no heading -> empty string),
      * a title CHAIN of headings with no content between them stays INSIDE —
        the POC debris splits "## I. THE UNION LEGISLATURE / ## 1 CHAPTER /
        ## The Union Parliament / ### Syllabus" with blank lines, and an
        earlier boundary rule (blank-preceded h2) collapsed the region to the
        first line, giving the model nothing to clean;
      * a heading that arrives AFTER a content line (list item or prose) ENDS
        the region — that is the real chapter body starting (civics ch.1's
        ``## FEDERAL SETUP IN INDIA``, the fixture's ``### Theory of
        Neutralization``);
      * a ``---`` thematic break ends the region (civics ch.1 shape);
      * a heading named *Syllabus* is a marker, never a boundary, and
        ``<!-- image -->`` placeholder residue is never "content";
      * capped at ``max_lines`` from the start.
    """
    lines = md_body.split("\n")
    start = None
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            start = i
            break
    if start is None:
        return ""
    seen_content = False
    end = None
    for i in range(start + 1, min(len(lines), start + max_lines)):
        s = lines[i].strip()
        if s == "---":
            end = i
            break
        if _HEADING.match(lines[i]):
            if _SYLLABUS_MARKER.search(s):
                continue  # a "Syllabus" marker heading lives inside the area
            if seen_content:
                end = i
                break
            continue  # title chain, no content yet: stays inside
        if s and not s.startswith("<!--"):
            seen_content = True  # prose or list-like line: content has started
    if end is None:
        end = min(len(lines), start + max_lines)
    return "\n".join(lines[start:end])


def slugify(text: str) -> str:
    """Deterministic tag slug: lowercase, non-alnum runs to single '-', trimmed.
    Deterministic by design — OCR noise is PRESERVED (fixed by humans/Gate B, never silently)."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return s.strip("-")

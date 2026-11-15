"""Markdown normalizer (DESIGN.md S4.1 body rules, S5 step 3, D2).

Pure, deterministic transform (D6): `normalize(md, *, chapter) -> str`,
ticket school-prep-agent-1qm. PASS ORDER (load-bearing — do not reorder):
  1. _fix_heading_levels      (levels are a pure function of the source)
  2. _rewrite_image_refs      (contract refs must exist before they are inspected)
  3. _strip_residue           (BEFORE structure: a deleted '<!-- image -->' line
                               would otherwise strand a double blank line and
                               break the idempotency fixed point)
  4. _fix_image_structure     (last: sees residue-free text, so blank-line
                               bookkeeping cannot fight a later deletion)
"""
from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})(\s)")


def _fix_heading_levels(md: str) -> str:
    """Shift heading levels so the shallowest heading in the doc becomes `##` (DESIGN: chapters build their entry point at `##`, Gate A requires >=1 `##`). Relative depth is preserved."""
    lines = md.split("\n")  # split("\n"), not splitlines(): preserves a trailing newline
    levels = [len(m.group(1)) for line in lines if (m := _HEADING.match(line))]
    if not levels:
        return md
    shift = 2 - min(levels)
    if shift == 0:
        return md

    def bump(line: str) -> str:
        m = _HEADING.match(line)
        if not m:
            return line
        level = min(6, max(1, len(m.group(1)) + shift))
        return "#" * level + m.group(2) + line[len(m.group(0)) :]

    return "\n".join(bump(l) for l in lines)


_IMG_REF = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")  # closing paren is part of the match (replacements must not re-add it)


def _rewrite_image_refs(md: str, chapter: int) -> str:
    """Rewrite image refs to the contract path `img/ch<N>-<seq>.<ext>` (DESIGN S4.1).

    New refs are numbered in order of appearance starting after the highest
    already-conformed number, so conformed input is a fixed point (idempotent).
    Original extension is kept when present, else `.png`.
    """
    state = {"next": 0}

    def repl(m: re.Match) -> str:
        alt, path = m.group(1), m.group(2)
        conformed = re.fullmatch(rf"img/ch{chapter}-(\d{{3}})\.[A-Za-z0-9]{{1,5}}", path)
        if conformed:
            state["next"] = max(state["next"], int(conformed.group(1)))
            return m.group(0)
        state["next"] += 1
        ext_m = re.search(r"\.([A-Za-z0-9]{1,5})$", path)
        ext = ext_m.group(1) if ext_m else "png"
        return f"![{alt}](img/ch{chapter}-{state['next']:03d}.{ext})"

    return _IMG_REF.sub(repl, md)


_IMG_LINE = re.compile(r"^\s*" + _IMG_REF.pattern + r"\s*$")  # one source of truth: anchored _IMG_REF (code-review smell #3)


def _fix_image_structure(md: str) -> str:
    """Enforce S4.1 image structure: an image line is always separated from its neighbours by
    exactly ONE blank line (the caption, if any, stays the next non-blank line — captions are
    first-class and must be kept). Blank runs collapse to a single blank. Pure, idempotent."""
    kept: list[str] = []
    for line in md.split("\n"):
        bare = line.strip()  # classification only — leading whitespace is structure (D2)
        if bare == "":
            # Collapse: emit a blank line only if the last kept line is content
            if kept and kept[-1].strip() != "":
                kept.append("")
        elif _IMG_LINE.match(bare):
            # Keep a blank before the image (separates it from preceding content)
            if kept and kept[-1].strip() != "":
                kept.append("")
            kept.append(line.rstrip())
        else:
            # Non-image content: separate from a preceding image; keep original indentation (lists, quotes)
            if kept and _IMG_LINE.match(kept[-1].strip()):
                kept.append("")
            kept.append(line.rstrip())
    return "\n".join(kept)


# DECISION POINT (code-review 1qm, standards #4 + spec c2): DESIGN S5.3 sanctions "strip HTML
# residue", D2 requires keeping math/table structure. Resolution: strip ONLY the known
# textbook/OCR residue tags below; everything else (MathML <msub>/<mi>, custom tags, "a < b"
# prose) is preserved. Add/remove residue tags HERE, nowhere else.
_RESIDUE_TAGS = ("sup", "sub", "br", "b", "i", "u", "s", "em", "strong", "font", "span",
                 "small", "p", "div", "table", "thead", "tbody", "tr", "td", "th", "img")
_HTML_TAG = re.compile(r"</?(?:" + "|".join(_RESIDUE_TAGS) + r")(?:\s[^>]*)?>", re.IGNORECASE)
_PLACEHOLDER_IMG = re.compile(r"^\s*<!--\s*image\s*-->\s*$")
_BAD_CHARS = "\ufffd\u200b\u200c\u200d\ufeff"


def _strip_residue(md: str) -> str:
    """Remove placeholder '<!-- image -->' lines, inline HTML tags (inner text kept),
    U+FFFD replacement chars and zero-width characters (Gate A: no U+FFFD; j99 extended: no placeholder residue).
    Body prose — including OCR-tolerated content (DESIGN S4.1) — is otherwise untouched."""
    out = []
    for line in md.split("\n"):
        if _PLACEHOLDER_IMG.match(line):
            continue
        for ch in _BAD_CHARS:
            line = line.replace(ch, "")
        line = _HTML_TAG.sub("", line)
        out.append(line)
    return "\n".join(out)


def normalize(md: str, *, chapter: int) -> str:
    # Order is load-bearing — see module docstring (residue BEFORE structure, rewrite before both)
    out = _fix_heading_levels(md)
    out = _rewrite_image_refs(out, chapter)
    out = _strip_residue(out)
    return _fix_image_structure(out)

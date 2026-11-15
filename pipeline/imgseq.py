"""Shared image-sequence contract (ticket school-prep-agent-529; DESIGN S4.1, S5 step 3).

Single source of truth for the  original image ref  ->  ``img/ch<N>-<seq>.<ext>``
mapping. Used by BOTH:
  - ``pipeline/normalize.py``  (ref rewrite — ticket 1qm)
  - ``pipeline/images.py``     (blob extraction — this ticket)
so the file numbering can never diverge from the rewritten refs.

``seq`` = order of appearance of the ref in ``md_content`` (529 CONTRACT).
Conformed refs keep their number and new refs sequence after the highest conformed
number seen before them — this preserves the 1qm fixed point (idempotent rewrite)
exactly, so refactoring normalize onto this helper is behaviour-preserving.
"""
from __future__ import annotations

import re

# One source of the ref shape (code-review smell: anchor the SAME pattern everywhere).
IMG_REF = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def iter_ref_paths(md: str) -> list[str]:
    """All image-ref target paths in order of appearance (duplicates preserved)."""
    return [m.group(2) for m in IMG_REF.finditer(md)]


# data: URIs (docling-serve image_export_mode=embedded) have no file extension, so the
# extension comes from the mime type. Both rewrite (1qm) and extraction (529) read it here,
# keeping the single source of truth. Plain paths fall through to the 1qm rule.
_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
}


def extension_of(ref: str) -> str:
    """Contract-file extension: mime type for data: URIs, else trailing ``.<ext>``,
    else ``png`` (1qm rule — a bare/unknown-ext ref becomes ``.png``)."""
    m = re.match(r"^data:([A-Za-z0-9/+\-.]+)", ref)
    if m and (mime := m.group(1).lower()) in _MIME_EXT:
        return _MIME_EXT[mime]
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", ref)
    return m.group(1) if m else "png"


def contract_name(chapter: int, seq: int, ext: str) -> str:
    return f"img/ch{chapter}-{seq:03d}.{ext}"


def _conformed_seq(ref: str, chapter: int) -> int | None:
    m = re.fullmatch(rf"img/ch{chapter}-(\d{{3}})\.[A-Za-z0-9]{{1,5}}", ref)
    return int(m.group(1)) if m else None


def assign(chapter: int, md: str) -> dict[str, str]:
    """Ordered mapping of every distinct image-ref path in ``md`` to its contract path.

    Memoized per distinct ref (one source image is always one file). Conformed refs map
    to themselves; un-conformed refs take the next free seq in order of appearance,
    continuing after any conformed number already seen (1qm fixed point).
    """
    mapping: dict[str, str] = {}
    next_seq = 0
    for ref in iter_ref_paths(md):
        if ref in mapping:
            continue
        seq = _conformed_seq(ref, chapter)
        if seq is not None:
            next_seq = max(next_seq, seq)
            mapping[ref] = contract_name(chapter, seq, extension_of(ref))
        else:
            next_seq += 1
            mapping[ref] = contract_name(chapter, next_seq, extension_of(ref))
    return mapping


def rewrite(md: str, chapter: int) -> str:
    """Rewrite every image ref in ``md`` to its contract path. Idempotent (fixed point)."""
    mapping = assign(chapter, md)

    def repl(m: re.Match) -> str:
        return f"![{m.group(1)}]({mapping[m.group(2)]})"

    return IMG_REF.sub(repl, md)

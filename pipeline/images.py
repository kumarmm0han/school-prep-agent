"""Image blob extraction (DESIGN S5 step 3 + S4.1 img/ layout; ticket school-prep-agent-529).

Writes the ``img/ch<N>-<seq>.<ext>`` files that the normalizer's rewritten refs point at,
from the embedded data: URIs in the converted markdown (docling-serve
``image_export_mode=embedded``: refs carry ``data:<mime>;base64,<b64>`` payloads).

The ref → contract-path mapping is the SHARED ``imgseq`` contract (ticket 529 CONTRACT):
``assign(chapter, md)`` is the single source of truth used by BOTH this module and
``pipeline/normalize`` (ref rewrite), so the written filenames always match the
rewritten refs 1:1 — the numbering can never diverge.

Fail-loud, never a silent drop (529): a ref whose payload is absent or undecodable is
left UNWRITTEN on purpose — Gate A's blob-existence check (j99) then flags the chapter
``qa_failed``. We never write a bogus file and never crash the batch over one bad image
(D4 isolation lives in the orchestrator).
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from . import imgseq

# A full data: URI ref (the whole target of the markdown image ref).
_DATA_URI = re.compile(r"^data:(image/[A-Za-z0-9]+);base64,([A-Za-z0-9+/=]+)$")


def extract_blob(ref: str) -> tuple[str, bytes] | None:
    """Decode a data: URI ref to ``(mime, bytes)``; ``None`` when not a usable embedded blob."""
    m = _DATA_URI.match(ref)
    if not m:
        return None
    try:
        return m.group(1).lower(), base64.b64decode(m.group(2), validate=True)
    except (ValueError, base64.binascii.Error):
        return None  # corrupt payload: leave unwritten, Gate A's blob check will flag it


def extract(md: str, chapter: int, book_dir: str | Path) -> list[Path]:
    """Write every decodable embedded image in ``md`` to ``<book_dir>/img/ch<N>-<seq>.<ext>``.

    Returns the list of files actually written (empty when there is nothing to write or a
    re-run finds every file already correct — the idempotency AC: same files, zero rewrites).
    Refs without a usable blob are skipped on purpose (Gate A flags them; see module docstring).
    """
    base = Path(book_dir)
    mapping = imgseq.assign(chapter, md)  # shared contract — identical to the rewrite
    written: list[Path] = []
    for ref in mapping:  # dict order == order of appearance == the seq numbering
        blob = extract_blob(ref)
        if blob is None:
            continue  # no usable payload: intentional fail-loud, NOT a silent drop
        _mime, payload = blob
        dest = base / mapping[ref]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and dest.read_bytes() == payload:
            continue  # already correct -> zero rewrites (idempotent re-run)
        dest.write_bytes(payload)
        written.append(dest)
    return written

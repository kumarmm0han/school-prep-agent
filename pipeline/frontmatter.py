"""Front matter assembly (DESIGN S4.1 contract + D3; ticket school-prep-agent-5x7).

`assemble(...)` emits the chapter front matter block in contract order;
`parse_frontmatter(md) -> (dict, body)` round-trips it. Pure text I/O (D6);
PyYAML is the one sanctioned third-party (DESIGN S2). Deterministic output:
identical inputs => identical bytes (idempotency foundation, D4).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from .syllabus import slugify


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def assemble(
    subject: str,
    board: str,
    class_: int,
    chapter: int,
    title: str,
    syllabus: list[str],
    *,
    section: str | None = None,  # board-syllabus unit (D11); may be filled by the human at Gate B
    tags: list[str] | None = None,
    source_path: str | Path | None = None,
    docling_version: str | None = None,
    pipeline: str = "standard",
    vlm_model: str | None = None,
    pages: int | None = None,
    converted_at: str | None = None,
) -> str:
    if not syllabus:
        raise ValueError("syllabus must be non-empty (Gate A invariant); use the LLM clean pass (u1k) first")
    data: dict = {
        "subject": subject,
        "board": board,
        "class": class_,
    }
    if section is not None:
        data["section"] = section
    data.update(
        chapter=chapter,
        title=title,
        syllabus=list(syllabus),
        tags=list(tags) if tags else [slugify(title)],
        file=f"chapter-{chapter}.md",
    )
    provenance: dict = {}
    if source_path is not None:
        p = Path(source_path)
        provenance["source"] = p.name
        provenance["sha256"] = _sha256_of(p)
    for key, value in (
        ("docling_version", docling_version),
        ("pipeline", pipeline),
        ("vlm_model", vlm_model),
        ("pages", pages),
        ("converted_at", converted_at),
    ):
        if value is not None:
            provenance[key] = value
    data["provenance"] = provenance

    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True, width=4096)
    return "---\n" + body + "---\n"


def parse_frontmatter(md: str) -> tuple[dict, str]:
    lines = md.split("\n")
    if not lines or lines[0] != "---":
        raise ValueError("not a front-matter document: first line must be '---'")
    try:
        close = next(i for i in range(1, len(lines)) if lines[i] == "---")
    except StopIteration:
        raise ValueError("unterminated front matter: no closing '---'") from None
    data = yaml.safe_load("\n".join(lines[1:close])) or {}
    body = "\n".join(lines[close + 1 :])
    return data, body

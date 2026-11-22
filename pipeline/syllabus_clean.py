"""LLM-assisted clean pass for low-confidence syllabus captures (DESIGN S5, ticket school-prep-agent-u1k, D6).

Wires the low-confidence handoff that ``pipeline/syllabus.extract_head_list``
flags (``confidence == "low"``): ONE Ollama ``/api/chat`` call (``LLM_MODEL``)
asking for a STRICT JSON array of cleaned topic strings, followed by a
DETERMINISTIC validator (D6: judgment lives in pure functions):

  * the response is a raw JSON array of non-empty strings —
    no fences, no prose, no heading syntax (``#``), no multi-line items;
  * the count stays within 50%..3x of the captured count (the u1k contract);
    an empty capture must yield 1..15 items (Gate A's band);
  * NO invented items: every returned topic must be grounded in the source
    text (exact normalized-substring, or a fuzzy token match tolerant of OCR
    glyph damage like ``Rajyα Sabha`` -> ``Rajya Sabha``).

On ANY violation the pass is REJECTED as a whole — the captured list stands,
the violations are recorded, and NOTHING is silently substituted (u1k AC:
"invalid output is quarantined not applied"). The LLM's raw response is kept
in the record as quarantine evidence.

Prompt versioning: the prompt lives in ``prompts/clean-syllabus/v1.md`` and
the version string (``clean-syllabus/v1``) is recorded in the result so every
artifact can say WHICH prompt produced it (DESIGN D6 prompt/schema
versioning). Bump the file (``v2.md``) rather than editing ``v1.md``.

Deterministic core (D6): all judgment is pure over an injected
``chat(ollama_url, model, messages, timeout) -> str``; the ``urllib`` adapter
is the single impure line in this module (mirrors ``doctor``/``s3c``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config, resolve_config
from .syllabus import head_region

# One syllabus-clean chat is a small request; 120s is generous, and it must
# never approach the 2700s convert budget (s3c).
CLEAN_CHAT_TIMEOUT = 120

# Prompt location (DESIGN D6: prompt + version recorded per artifact).
_PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"
DEFAULT_PROMPT = _PROMPTS_ROOT / "clean-syllabus" / "v1.md"

# Validation bands (u1k contract + Gate A's 2-15 syllabus band).
_MIN_ITEMS_EMPTY_CAPTURE = 1
_MAX_ITEMS_EMPTY_CAPTURE = 15
# Grounding thresholds: fuzzy tier accepts OCR glyph damage, rejects invention.
_FUZZY_WINDOW_RATIO = 0.7
_TOKEN_MIN_LEN = 3
_STOP_TOKENS = frozenset(
    {"the", "and", "for", "with", "their", "its", "from", "into", "upon", "such", "these", "those"}
)
_HEADING = re.compile(r"^\s*#{1,6}\s")


def prompt_version(prompt_path: Path = DEFAULT_PROMPT) -> str:
    """Version string recorded alongside results: ``clean-syllabus/v1``.

    Pure + deterministic: derived from the path relative to ``prompts/``, so a
    new ``v2.md`` flips the recorded version with zero code change."""
    try:
        rel = Path(prompt_path).resolve().relative_to(_PROMPTS_ROOT)
        p = rel.with_suffix("")
    except ValueError:
        p = Path(Path(prompt_path).name).with_suffix("")
    return p.as_posix()


@dataclass(frozen=True)
class CleanResult:
    """Outcome of one clean pass. ``applied`` False means QUARANTINE:
    use the captured list (or the no-front-matter handoff) exactly as before."""

    applied: bool
    items: tuple[str, ...]
    captured: tuple[str, ...]
    violations: tuple[str, ...]
    model: str
    prompt: str
    raw: str | None = None  # the LLM's raw response — quarantine evidence on rejection


# --------------------------------------------------------------------------- #
# deterministic core
# --------------------------------------------------------------------------- #

def _compact(text: str) -> str:
    """Lowercase, keep [a-z0-9] only. Compares words across OCR glyph damage."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _significant_tokens(item: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", item.lower())
    return [t for t in tokens if len(t) >= _TOKEN_MIN_LEN and t not in _STOP_TOKENS]


def _grounded(item: str, source: str) -> bool:
    """True when the item is plausibly present in the source (u1k: no invented items).

    Tier 1 (exact): the compacted item is a substring of the compacted source —
      the common case; the LLM copies topic wording from the source.
    Tier 2 (fuzzy, OCR-tolerant): the item's strongest content token (or, when the
      token itself carries the damage — ``Rajyα Sabha``: source compact holds
      ``rajy`` — its longest ≥3-char prefix that does) anchors a window in the
      source; that window must match the item at ``_FUZZY_WINDOW_RATIO`` or
      better. Deterministic: fixed window sizes, every occurrence considered,
      max ratio wins. Invention fails both tiers (its content words are absent).
    """
    c_item = _compact(item)
    if not c_item:
        return False
    c_src = _compact(source)
    if c_item in c_src:
        return True
    tokens = _significant_tokens(item)
    if not tokens:
        return False
    # Anchor: the item's strongest content token, OR — when the token itself carries
    # the OCR damage (e.g. 'rajya' vs the source's OCR'd 'rajy' in 'Rajyα Sabha') —
    # its longest prefix of >=3 chars that IS present. Deterministic, bounded.
    anchor = None
    t = max(tokens, key=len)
    while len(t) >= _TOKEN_MIN_LEN:
        if _compact(t) in c_src:
            anchor = _compact(t)
            break
        t = t[:-1]
    if not anchor:
        return False
    ratio = 0.0
    pos = -1
    for w in (len(c_item), len(c_item) + len(c_item) // 2, len(c_item) // 2 + 1):
        start = c_src.find(anchor)
        while start != -1:
            lo = max(0, start - w // 4)
            cand = c_src[lo: lo + w]
            r = _seq_ratio(c_item, cand)
            if r > ratio:
                ratio = r
                pos = start
            start = c_src.find(anchor, start + 1)
    return pos != -1 and ratio >= _FUZZY_WINDOW_RATIO


def _seq_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio without importing difflib at module scope (same value)."""
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


def _band(n_captured: int) -> tuple[int, int]:
    """The (lo, hi) item-count band the validator enforces (u1k contract).

    Non-empty capture: 50%..3x of it (ceil lower); empty capture: 1..15 (Gate A's
    band). ``k=0`` is always outside — a give-up answer quarantines, never applies.
    """
    import math

    if n_captured > 0:
        return math.ceil(0.5 * n_captured), 3 * n_captured
    return _MIN_ITEMS_EMPTY_CAPTURE, _MAX_ITEMS_EMPTY_CAPTURE


def validate(raw_output: str, captured: list[str], source: str) -> tuple[list[str] | None, list[str]]:
    """Pure validation of one LLM response (u1k contract, D6).

    Returns ``(items, violations)``: ``items`` is None (reject) when ANY
    violation is recorded. Never mutates input; never rewrites item text
    (mechanical stripping of surrounding whitespace is the only touch).
    """
    v: list[str] = []
    try:
        text = raw_output.strip()
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        return None, [f"strict-JSON: not parseable ({exc.__class__.__name__})"]
    if not isinstance(data, list):
        return None, [f"strict-JSON: expected an array, got {type(data).__name__}"]

    items: list[str] = []
    for i, elem in enumerate(data):
        if not isinstance(elem, str):
            v.append(f"item {i}: not a string ({type(elem).__name__})")
            continue
        s = elem.strip()
        if not s:
            v.append(f"item {i}: empty")
        elif _HEADING.match(s):
            v.append(f"item {i}: heading syntax ({s[:40]!r})")
        elif "\n" in s:
            v.append(f"item {i}: multi-line")
        else:
            items.append(s)

    n, k = len(captured), len(items)
    lo, hi = _band(n)
    if not (lo <= k <= hi):
        band = f"{n} captured (band {lo}..{hi})" if n else "empty capture (band 1..15)"
        v.append(f"count: {k} items outside the {band}")
    if items:
        for s in items:
            if not _grounded(s, source):
                v.append(f"grounding: item not found in source ({s[:40]!r})")
                break  # one grounding failure quarantines; record the first offender
    if v:
        return None, v
    return items, []


def _user_message(source: str, captured: list[str]) -> str:
    return (
        "SOURCE (chapter head area, verbatim):\n"
        "'''\n"
        f"{source}\n"
        "'''\n\n"
        "CAPTURED (machine list, low confidence; may be empty or damaged):\n"
        + json.dumps(captured)
        + "\n\nReturn the cleaned topic list now: only the raw JSON array."
    )


def clean(
    captured: list[str],
    source_body: str,
    *,
    cfg: Config | None = None,
    chat=None,
    prompt_path: Path | str = DEFAULT_PROMPT,
    timeout: int = CLEAN_CHAT_TIMEOUT,
) -> CleanResult:
    """One clean pass over a low-confidence capture.

    ``chat(url, model, messages, timeout) -> str`` is the injectable seam
    (a mock chat makes this fully testable offline, D6). ``source_body`` is the
    whole chapter body — the grounding surface; the LLM only sees the head
    region (``head_region``), but grounding over the full body is stricter and
    deterministic.

    A transport failure is a REJECTION (captured list stands, error recorded)
    — an LLM outage must never sink a chapter (D4).
    """
    cfg = cfg if cfg is not None else resolve_config()
    prompt_path = Path(prompt_path)
    version = prompt_version(prompt_path)
    captured_t = tuple(captured)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": _user_message(head_region(source_body), list(captured_t))},
    ]
    do_chat = chat if chat is not None else _default_chat

    try:
        raw = do_chat(cfg.ollama_url, cfg.llm_model, messages, timeout)
    except Exception as exc:  # outage/network: quarantine, never sink the chapter (D4)
        return CleanResult(
            applied=False,
            items=(),
            captured=captured_t,
            violations=(f"llm-call failed: {exc.__class__.__name__}: {exc}",),
            model=cfg.llm_model,
            prompt=version,
            raw=None,
        )
    if not isinstance(raw, str):
        raw = str(raw)
    items, violations = validate(raw, list(captured_t), source_body)
    return CleanResult(
        applied=items is not None,
        items=tuple(items or ()),
        captured=captured_t,
        violations=tuple(violations),
        model=cfg.llm_model,
        prompt=version,
        raw=raw,
    )


def _default_chat(url: str, model: str, messages: list[dict], timeout: int) -> str:
    """The impure line (D6): one Ollama ``/api/chat`` call (LLM_MODEL, no stream).

    ``temperature: 0`` is pinned — this pass is a deterministic contract with a
    one-shot answer that a validator accepts or quarantines; sampling variance is
    precisely what the quarantine design cannot absorb (u1k live run, 2026-11-21:
    default-temperature answers flipped between a title-only list and ``[]``).
    """
    import urllib.request

    body = json.dumps(
        {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.0}}
    ).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    content = (payload.get("message") or {}).get("content")
    if not isinstance(content, str):
        raise ValueError(f"ollama /api/chat: no message.content in response (keys: {sorted(payload)})")
    return content

"""`pipeline doctor` — pre-flight environment check (ticket school-prep-agent-ws8).

Verifies, against a live stack:
  1. docling-serve ``GET <DOCLING_URL>/health`` reports ok
  2. Ollama ``GET <OLLAMA_URL>/api/tags`` lists the required models
Required: VLM_MODEL, LLM_MODEL, EMBED_MODEL.
Optional (warning only): FALLBACK_VLM_MODEL.

Deterministic core (D6): all judgment lives in pure functions over an
injected ``opener(url) -> bytes``; the network adapter is the single
impure line in this module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable
from urllib.request import urlopen

from .config import Config, resolve_config

OpenerFunc = Callable[[str], bytes]


@dataclass
class Report:
    ok: bool = True
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, line: str) -> None:
        self.ok = False
        self.failures.append(line)

    def warn(self, line: str) -> None:
        self.warnings.append(line)


def _get_json(opener: OpenerFunc, url: str, rep: Report, label: str, when_down: str) -> dict | None:
    """Shared call → actionable-fail → parse shape (spec review (c): bad bodies must fail clean, not crash)."""
    try:
        body = opener(url)
    except Exception as exc:  # URLError, connection refused, timeout, ...
        rep.fail(f"FAIL {label}: {url} unreachable ({exc.__class__.__name__}: {exc}) — {when_down}")
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        rep.fail(f"FAIL {label}: unparseable or non-object response at {url} — check the service version")
        return None
    return payload


def _check_docling(opener: OpenerFunc, cfg: Config, rep: Report) -> None:
    url = cfg.docling_url.rstrip("/") + "/health"
    payload = _get_json(opener, url, rep, "docling-serve",
                        "is it running? e.g. docker compose -f ~/sandbox/docling-serve/docker-compose.yaml ps")
    if payload is None:
        return
    status = payload.get("status")
    if status != "ok":
        rep.fail(f"FAIL docling-serve: unhealthy ({status!r}) at {url} — restart the service and re-run doctor")


def _check_ollama(opener: OpenerFunc, cfg: Config, rep: Report) -> None:
    url = cfg.ollama_url.rstrip("/") + "/api/tags"
    payload = _get_json(opener, url, rep, "ollama", "is the ollama server up?")
    if payload is None:
        return
    models = payload.get("models")
    names = {m.get("name") for m in models if isinstance(m, dict)} if isinstance(models, list) else set()

    def present(model: str) -> bool:
        # ollama lists untagged models as "<name>:latest"; requesting the bare name is the same model
        return model in names or f"{model}:latest" in names

    for model in (cfg.vlm_model, cfg.llm_model, cfg.embed_model):
        if not present(model):
            rep.fail(f"FAIL ollama model: '{model}' not found in /api/tags — pull it: ollama pull {model}")
    if not present(cfg.fallback_vlm_model):
        rep.warn(f"WARN ollama model: fallback VLM '{cfg.fallback_vlm_model}' missing — D10 fallback path unavailable")


def run_checks(opener: OpenerFunc, cfg: Config) -> Report:
    """Pure check aggregation (the seam). `opener` raises on connection failure."""
    rep = Report()
    _check_docling(opener, cfg, rep)
    _check_ollama(opener, cfg, rep)
    return rep


def _default_opener(url: str) -> bytes:
    with urlopen(url, timeout=10) as resp:
        return resp.read()


_USAGE = "usage: python -m pipeline <verb>   verbs: doctor   (convert, index, summary, kb, verify — pending their tickets)"


def cli(argv: list[str], opener: OpenerFunc | None = None, env: dict | None = None) -> int:
    if not argv or argv[0] != "doctor":
        print(_USAGE)
        return 2
    cfg = resolve_config(env)
    rep = run_checks(opener or _default_opener, cfg)
    for w in rep.warnings:
        print(w)
    for f in rep.failures:
        print(f)
    if rep.ok:
        print("doctor: OK — docling-serve healthy; required ollama models present")
    else:
        print(f"doctor: FAILED ({len(rep.failures)} failure(s))")
    return 0 if rep.ok else 1

"""docling-serve HTTP client (ticket school-prep-agent-s3c; DESIGN S5.2, D1, ADR-0001).

POSTs one chapter PDF to docling-serve ``/v1/convert/file`` (multipart) with the
frozen option set: ``to_format=markdown``, ``force_ocr``, ``do_table_structure``,
``include_images``, the ``standard`` pipeline (``vlm`` escape hatch overridable),
picture-description via Ollama (``VLM_MODEL``, inner timeout 1200s, chemistry
caption prompt). Request budget is 2700s (DESIGN S5.2).

Retry contract (DESIGN S5.6; the POC ``converter.py`` token list is the
reference, per ticket): at most ``MAX_RETRIES`` extra attempts,
``BACKOFF_SECONDS`` between them, *only* for transient failures recognized by
message token. Non-transient failures raise immediately, so a bad chapter never
burns retry budget — isolation of the failing chapter is the caller's job (D4).

Deterministic core (D6): all judgment lives in pure functions over an injected
``poster(url, form, file_name, file_bytes, timeout) -> dict`` and ``sleeper``;
the requests adapter is the single impure line in this module (mirrors doctor).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from .config import Config, resolve_config

# DESIGN S5.2: full convert request budget, incl. every picture-description call.
REQUEST_TIMEOUT = 2700
# DESIGN S5.2: picture_description_api.timeout (per inner Ollama call).
CAPTION_TIMEOUT = 1200
# DESIGN S5.6: "backoff 2s x 3".
MAX_RETRIES = 3
BACKOFF_SECONDS = 2.0

CONVERT_PATH = "/v1/convert/file"

# docling-serve 1.26 ImageRefMode (openapi probe 2026-11-15): how image payloads
# ride in md_content: placeholder (<!-- image -->), embedded (data: URIs) or
# referenced (URIs). Ticket 529 needs "embedded" to extract the blobs (S5 step 3).
IMAGE_EXPORT_MODES = ("placeholder", "embedded", "referenced")

CAPTION_PROMPT = (
    "Describe this technical illustration precisely for a chemistry student: "
    "every visible substance, apparatus, process step, labels and values."
)

# POC converter.py token list (ticket s3c): the only failures worth retrying.
TRANSIENT_TOKENS = (
    "connection refused",
    "connect error",
    "connect timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
)

PosterFunc = Callable[[str, dict[str, str], str, bytes, int], dict]
SleeperFunc = Callable[[float], None]


class DoclingError(RuntimeError):
    """A failed conversion attempt.

    ``transient`` records the retry verdict (token match, POC reference);
    ``attempts`` counts how many poster calls were made before raising.
    """

    def __init__(self, message: str, *, transient: bool, attempts: int):
        super().__init__(message)
        self.transient = transient
        self.attempts = attempts


def is_transient(message: str) -> bool:
    """Token-based verdict on a failure message (POC converter.py is the reference).

    Case-insensitive substring match against ``TRANSIENT_TOKENS``. Anything not
    matched (bad params, auth errors, 4xx bodies, ...) is a hard failure.
    """
    lowered = message.lower()
    return any(token in lowered for token in TRANSIENT_TOKENS)


def caption_api(ollama_url: str, vlm_model: str, *, timeout: int = CAPTION_TIMEOUT) -> str:
    """The ``picture_description_api`` JSON body (shape pinned by DESIGN S5.2)."""
    return json.dumps(
        {
            "url": f"{ollama_url.rstrip('/')}/v1/chat/completions",
            "params": {"model": vlm_model},
            "timeout": timeout,
            "prompt": CAPTION_PROMPT,
        }
    )


def build_form(
    cfg: Config, pipeline: str = "standard", *, image_export_mode: str | None = None
) -> dict[str, str]:
    """The frozen option set for ``/v1/convert/file`` (DESIGN D1 + S5.2).

    ``pipeline`` is the one chapter-overridable option: ``standard`` (default)
    or ``vlm`` (escape hatch). Booleans go as form strings, as in the proven
    markdown-wrapper (sample-code/main.py).

    ``image_export_mode`` (ticket 529): optional docling-serve ImageRefMode. Omitted
    (default) the form is exactly the s3c frozen set; ``"embedded"`` returns the
    image payloads as data: URIs inside ``md_content``, which is the precondition
    for blob extraction (DESIGN S5 step 3: "extract image blobs ... if embedded").
    """
    if pipeline not in ("standard", "vlm"):
        raise ValueError(f"unknown pipeline {pipeline!r} — supported: standard | vlm (D1 escape hatch)")
    form = {
        "to_format": "markdown",
        "force_ocr": "true",
        "do_table_structure": "true",
        "include_images": "true",
        "pipeline": pipeline,
        "do_picture_description": "true",
        "picture_description_api": caption_api(cfg.ollama_url, cfg.vlm_model),
    }
    if image_export_mode is not None:
        if image_export_mode not in IMAGE_EXPORT_MODES:
            raise ValueError(
                f"unknown image_export_mode {image_export_mode!r} — supported: "
                f"{' | '.join(IMAGE_EXPORT_MODES)} (docling-serve ImageRefMode)"
            )
        form["image_export_mode"] = image_export_mode
    return form


@dataclass(frozen=True)
class ConversionResult:
    """A successful conversion.

    ``response`` is the full parsed docling-serve payload: provenance (5x7)
    and image-blob extraction (529) read their fields from it.
    """

    md_content: str
    response: dict
    attempts: int


def convert(
    file_name: str,
    file_bytes: bytes,
    *,
    cfg: Config | None = None,
    pipeline: str = "standard",
    image_export_mode: str | None = None,
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    poster: PosterFunc | None = None,
    sleeper: SleeperFunc = time.sleep,
) -> ConversionResult:
    """Convert one chapter PDF via docling-serve; transient retries only.

    ``image_export_mode`` (ticket 529) is optional; ``"embedded"`` requests the
    image payloads as data: URIs in ``md_content`` so ``pipeline.images`` can
    extract them (DESIGN S5 step 3). Omitted by default — the s3c frozen form.

    Raises ``DoclingError`` when a failure is non-transient (immediately) or
    when retries are exhausted (``transient=True``). Never retries a
    non-transient failure, and never a response-shape problem.
    """
    cfg = cfg if cfg is not None else resolve_config()
    url = cfg.docling_url.rstrip("/") + CONVERT_PATH
    form = build_form(cfg, pipeline, image_export_mode=image_export_mode)
    post = poster if poster is not None else _default_poster

    for attempt in range(1, max_retries + 2):  # first try + up to max_retries retries
        try:
            payload = post(url, form, file_name, file_bytes, timeout)
            break
        except Exception as exc:  # poster raises: transport errors, HTTP errors, bad JSON
            transient = is_transient(str(exc))
            hint = " — is docling-serve up? (python -m pipeline doctor)" if transient else ""
            if not transient or attempt == max_retries + 1:
                raise DoclingError(
                    f"{url}: {exc} (transient={transient}, attempt {attempt}/{max_retries + 1}){hint}",
                    transient=transient,
                    attempts=attempt,
                ) from exc
            sleeper(BACKOFF_SECONDS)

    if not isinstance(payload, dict):
        raise DoclingError(
            f"{url}: response is not a JSON object (got {type(payload).__name__}) — "
            f"check the docling-serve version",
            transient=False,
            attempts=attempt,
        )
    document = payload.get("document")
    md = document.get("md_content") if isinstance(document, dict) else None
    if not isinstance(md, str) or not md:
        raise DoclingError(
            f"{url}: response missing document.md_content — top-level keys: {sorted(payload)}; "
            f"convert may have failed server-side",
            transient=False,
            attempts=attempt,
        )
    return ConversionResult(md_content=md, response=payload, attempts=attempt)


def _default_poster(
    url: str, form: dict[str, str], file_name: str, file_bytes: bytes, timeout: int
) -> dict:
    """The impure line (D6): multipart POST via requests.

    Multipart field name ``files`` matches the proven wrapper (sample-code/main.py).
    Non-2xx is raised with the service body in the message so token-based
    retry verdicts can see it (e.g. "temporarily unavailable").
    """
    import requests

    resp = requests.post(
        url,
        files={"files": (file_name, file_bytes, "application/pdf")},
        data=form,
        timeout=timeout,
    )
    if not 200 <= resp.status_code < 300:
        raise requests.HTTPError(f"HTTP {resp.status_code} {resp.reason}: {resp.text}")
    return resp.json()

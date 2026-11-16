"""docling-serve HTTP client (ticket school-prep-agent-s3c; DESIGN S5.2, D1, ADR-0001).

POSTs one chapter PDF to docling-serve ``/v1/convert/file`` (multipart) with the
frozen option set: ``to_format=markdown``, ``force_ocr``, ``do_table_structure``,
``include_images=false``, the ``standard`` pipeline (``vlm`` escape hatch
overridable). Request budget is 2700s (DESIGN S5.2).

**Owner decision 2026-11-15 (ADR-0005):** the book is text-focused for now — the
picture-description parameters (``do_picture_description`` / ``picture_description_api``,
which docling-serve 1.26 deprecates/gates anyway) and embedded image export are
DEFERRED, so ``include_images=false`` and the markdown is picture-free (the
``<!-- image -->`` residue is stripped by 1qm; Gate A's caption rule is vacuous until
pictures are re-enabled). Re-enabling is ticket school-prep-agent-ezq, which carries
the deferred shapes (caption prompt, VLM endpoint, custom-config gating).

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

import time
from dataclasses import dataclass
from typing import Callable

from .config import Config, resolve_config

# DESIGN S5.2: full convert request budget.
REQUEST_TIMEOUT = 2700
# DESIGN S5.6: "backoff 2s x 3".
MAX_RETRIES = 3
BACKOFF_SECONDS = 2.0

CONVERT_PATH = "/v1/convert/file"

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


def build_form(cfg: Config, pipeline: str = "standard") -> dict[str, str]:
    """The frozen option set for ``/v1/convert/file`` (DESIGN D1 + S5.2, ADR-0005 v2
    per owner decision 2026-11-15).

    ``pipeline`` is the one chapter-overridable option: ``standard`` (default)
    or ``vlm`` (escape hatch). Booleans go as form strings, as in the proven
    markdown-wrapper (sample-code/main.py).

    Picture content is deferred (ADR-0005): ``include_images=false`` keeps the
    markdown picture-free. ``cfg`` is still accepted — it is the single source of
    the convert endpoint — so the re-enable (ezq) only adds form fields.
    """
    if pipeline not in ("standard", "vlm"):
        raise ValueError(f"unknown pipeline {pipeline!r} — supported: standard | vlm (D1 escape hatch)")
    return {
        "to_format": "markdown",
        "force_ocr": "true",
        "do_table_structure": "true",
        "include_images": "false",
        "pipeline": pipeline,
    }


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
    timeout: int = REQUEST_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    poster: PosterFunc | None = None,
    sleeper: SleeperFunc = time.sleep,
) -> ConversionResult:
    """Convert one chapter PDF via docling-serve; transient retries only.

    Raises ``DoclingError`` when a failure is non-transient (immediately) or
    when retries are exhausted (``transient=True``). Never retries a
    non-transient failure, and never a response-shape problem.
    """
    cfg = cfg if cfg is not None else resolve_config()
    url = cfg.docling_url.rstrip("/") + CONVERT_PATH
    form = build_form(cfg, pipeline)
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

"""Environment configuration (DESIGN.md S2 defaults; .env / shell overrides).

Single source of truth: the `_FIELDS` table — (Config field, env key, default).
The `Config` dataclass is the typed view over it; tests/test_config.py pins the
two together so the mapping cannot drift (code-review finding, ws8).
Pure data: `resolve_config(env)` is I/O-free and trivially testable (D6).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    docling_url: str
    ollama_url: str
    vlm_model: str
    fallback_vlm_model: str
    llm_model: str
    embed_model: str


# (Config field, env key, default per DESIGN S2)
_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("docling_url", "DOCLING_URL", "http://localhost:5001"),
    # host-side form (Q13 amendment); the DESIGN S2 `host.docker.internal:11434`
    # form applied to the removed in-container deployment — keep localhost here.
    ("ollama_url", "OLLAMA_URL", "http://localhost:11434"),
    ("vlm_model", "VLM_MODEL", "qwen3-vl:8b"),
    ("fallback_vlm_model", "FALLBACK_VLM_MODEL", "granite3.2-vision:latest"),
    ("llm_model", "LLM_MODEL", "qwen3.8:27b"),
    ("embed_model", "EMBED_MODEL", "qwen3-embedding"),
)


def resolve_config(env: dict[str, str] | None = None) -> Config:
    """Resolve the effective config. `env=None` reads os.environ."""
    if env is None:
        import os

        env = os.environ
    values = {
        field: (env.get(env_key, "") or "") or default
        for field, env_key, default in _FIELDS
    }
    return Config(**values)

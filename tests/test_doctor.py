"""Seam: doctor check evaluation — pure aggregation over an injected `opener`.

`opener(url) -> bytes` (raises OSError/URLError on connection failure).
Failure lines must be actionable one-liners (ticket ws8 acceptance).
"""
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stdout

from pipeline.config import resolve_config

HEALTH_OK = b'{"status": "ok"}'
TAGS_ALL = b'{"models": [{"name": "qwen3-vl:8b"}, {"name": "granite3.2-vision:latest"}, {"name": "qwen3.8:27b"}, {"name": "qwen3-embedding:latest"}]}'


def tags_payload(names):
    return json.dumps({"models": [{"name": n} for n in names]}).encode()


class Opener:
    """Route fakes per host."""

    def __init__(self, routes):
        self.routes = routes

    def __call__(self, url):
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                if isinstance(response, Exception):
                    raise response
                return response
        raise urllib.error.URLError(f"no route for {url}")


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.cfg = resolve_config({})

    def evaluate(self, routes):
        from pipeline import doctor

        return doctor.run_checks(Opener(routes), self.cfg)

    def test_all_pass(self):
        rep = self.evaluate(
            {"http://localhost:5001/health": HEALTH_OK, "http://localhost:11434/api/tags": TAGS_ALL}
        )
        self.assertTrue(rep.ok)
        self.assertEqual(rep.failures, [])
        self.assertEqual(rep.warnings, [])

    def test_docling_down_is_actionable_failure(self):
        rep = self.evaluate(
            {
                "http://localhost:5001": urllib.error.URLError("Connection refused"),
                "http://localhost:11434": TAGS_ALL,
            }
        )
        self.assertFalse(rep.ok)
        self.assertTrue(any("docling-serve" in f and "localhost:5001" in f for f in rep.failures))

    def test_docling_unhealthy_body_is_failure(self):
        rep = self.evaluate(
            {"http://localhost:5001/health": b'{"status": "error"}', "http://localhost:11434/api/tags": TAGS_ALL}
        )
        self.assertFalse(rep.ok)
        self.assertTrue(any("docling-serve" in f and "unhealthy" in f for f in rep.failures))

    def test_non_object_body_is_clean_failure_not_crash(self):
        # spec review (c): a well-formed-but-non-object JSON must fail with an actionable line
        rep = self.evaluate(
            {"http://localhost:5001/health": b"[1, 2, 3]", "http://localhost:11434/api/tags": TAGS_ALL}
        )
        self.assertFalse(rep.ok)
        self.assertTrue(any("non-object" in f for f in rep.failures), rep.failures)

    def test_missing_required_model_names_it_and_hints_pull(self):
        rep = self.evaluate(
            {
                "http://localhost:5001/health": HEALTH_OK,
                "http://localhost:11434/api/tags": tags_payload(["qwen3-vl:8b", "granite3.2-vision:latest", "qwen3-embedding"]),
            }
        )
        self.assertFalse(rep.ok)
        hits = [f for f in rep.failures if "qwen3.8:27b" in f]
        self.assertTrue(hits, f"no failure named the missing model: {rep.failures}")
        self.assertTrue(any("ollama pull" in f for f in hits))

    def test_missing_fallback_is_warning_not_failure(self):
        rep = self.evaluate(
            {
                "http://localhost:5001/health": HEALTH_OK,
                "http://localhost:11434/api/tags": tags_payload(["qwen3-vl:8b", "qwen3.8:27b", "qwen3-embedding"]),
            }
        )
        self.assertTrue(rep.ok)
        self.assertTrue(any("granite3.2-vision" in w for w in rep.warnings))

    def test_bare_model_name_matches_its_latest_alias(self):
        # ollama lists untagged models as "<name>:latest" (verified on the live DGX);
        # requesting the bare name must count as present
        rep = self.evaluate(
            {
                "http://localhost:5001/health": HEALTH_OK,
                "http://localhost:11434/api/tags": b'{"models": [{"name": "qwen3-vl:8b"}, {"name": "granite3.2-vision:latest"}, {"name": "qwen3.8:27b"}, {"name": "qwen3-embedding:latest"}]}',
            }
        )
        self.assertTrue(rep.ok, f"unexpected failures: {rep.failures}")

    def test_ollama_down_is_failure_naming_service(self):
        rep = self.evaluate(
            {
                "http://localhost:5001/health": HEALTH_OK,
                "http://localhost:11434": urllib.error.URLError("[Errno 111] Connection refused"),
            }
        )
        self.assertFalse(rep.ok)
        self.assertTrue(any("ollama" in f for f in rep.failures))


class CliTest(unittest.TestCase):
    def _cli(self, routes):
        from pipeline import doctor

        out = io.StringIO()
        with redirect_stdout(out):
            code = doctor.cli(["doctor"], opener=Opener(routes), env={})
        return code, out.getvalue()

    def test_exit_0_when_healthy(self):
        code, out = self._cli(
            {"http://localhost:5001/health": HEALTH_OK, "http://localhost:11434/api/tags": TAGS_ALL}
        )
        self.assertEqual(code, 0)

    def test_exit_nonzero_and_one_line_per_failure(self):
        code, out = self._cli(
            {
                "http://localhost:5001": urllib.error.URLError("Connection refused"),
                "http://localhost:11434/api/tags": tags_payload(["qwen3-vl:8b"]),
            }
        )
        self.assertNotEqual(code, 0)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        failures = [ln for ln in lines if ln.lstrip().startswith("FAIL")]
        self.assertGreaterEqual(len(failures), 2)  # docling + at least 2 missing required models

    def test_usage_for_unknown_verb(self):
        from pipeline import doctor

        out = io.StringIO()
        with redirect_stdout(out):
            code = doctor.cli(["frobnicate"], opener=None, env={})
        self.assertNotEqual(code, 0)
        self.assertIn("usage", out.getvalue().lower())


if __name__ == "__main__":
    unittest.main()

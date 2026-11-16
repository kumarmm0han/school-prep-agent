"""Seam: docling-serve client — pure retry/shape judgment over an injected poster.

Ticket school-prep-agent-s3c acceptance criteria (unit half), under the ADR-0005
contract (owner decision 2026-11-15, picture content deferred):
  - exact form params (frozen OCR set, incl. include_images=false)
  - transient-fail-then-succeed returns
  - non-transient raises at the first try (no retry, no backoff)
The live AC (chap-1 smoke, non-empty md_content) runs against the real stack
via the default poster — not in this file.
"""
import unittest
import urllib.error

from pipeline.config import resolve_config
from pipeline.docling_client import (
    BACKOFF_SECONDS,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    DoclingError,
    build_form,
    convert,
    is_transient,
)

PAYLOAD_OK = {"document": {"md_content": "# chapter one\n\nbody text"}, "pages": 12}


class Poster:
    """Queue of outcomes (dict -> return, Exception -> raise); records every call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def __call__(self, url, form, file_name, file_bytes, timeout):
        self.calls.append(
            {"url": url, "form": form, "file_name": file_name, "file_bytes": file_bytes, "timeout": timeout}
        )
        if not self.outcomes:
            raise AssertionError("poster called more times than outcomes queued")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Sleeper:
    def __init__(self):
        self.naps: list[float] = []

    def __call__(self, seconds):
        self.naps.append(seconds)


class FormTest(unittest.TestCase):
    """AC: exact form params — the ADR-0005 OCR set, picture description deferred."""

    def setUp(self):
        self.cfg = resolve_config({})  # defaults per DESIGN S2 / _FIELDS

    def test_exact_option_set(self):
        form = build_form(self.cfg)
        self.assertEqual(
            set(form),
            {
                "to_format",
                "force_ocr",
                "do_table_structure",
                "include_images",
                "pipeline",
            },
        )
        self.assertEqual(
            form,
            {
                "to_format": "markdown",
                "force_ocr": "true",
                "do_table_structure": "true",
                "include_images": "false",
                "pipeline": "standard",
            },
        )

    def test_picture_description_params_are_deferred_not_sent(self):
        # ADR-0005 (owner decision 2026-11-15): book is text-focused for now;
        # the deferred shapes live in ticket ezq / DESIGN S5.2, not in this form
        form = build_form(self.cfg)
        self.assertNotIn("do_picture_description", form)
        self.assertNotIn("picture_description_api", form)

    def test_vlm_escape_hatch_is_the_only_variation(self):
        form = build_form(self.cfg, pipeline="vlm")
        self.assertEqual(form["pipeline"], "vlm")
        self.assertEqual(
            {k: v for k, v in form.items() if k != "pipeline"},
            {k: v for k, v in build_form(self.cfg).items() if k != "pipeline"},
        )

    def test_unknown_pipeline_rejected_naming_choices(self):
        with self.assertRaises(ValueError) as ctx:
            build_form(self.cfg, pipeline="fancy")
        self.assertIn("standard", str(ctx.exception))
        self.assertIn("vlm", str(ctx.exception))


class TransientTokenTest(unittest.TestCase):
    """POC converter.py token list is the reference; everything else is a hard failure."""

    def test_each_poc_token_is_transient(self):
        for token in (
            "connection refused",
            "connect error",
            "connect timeout",
            "timed out",
            "temporarily unavailable",
            "connection reset",
        ):
            self.assertTrue(is_transient(token), token)

    def test_case_insensitive_and_embedded(self):
        self.assertTrue(is_transient("[Errno 111] Connection refused"))
        self.assertTrue(is_transient("('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"))
        self.assertTrue(is_transient("Read timed out."))

    def test_non_transient_messages(self):
        for message in ("", "invalid api key", "HTTP 400 Bad Request: bad request", "unauthorized"):
            self.assertFalse(is_transient(message), repr(message))


class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.cfg = resolve_config({})
        self.sleeper = Sleeper()
        self.pdf = b"%PDF-1.4 fake chapter bytes"

    def _convert(self, poster, **kw):
        return convert(
            "Selina-Concise-Chemistry-10-chap-1.pdf",
            self.pdf,
            cfg=self.cfg,
            poster=poster,
            sleeper=self.sleeper,
            **kw,
        )

    def test_success_first_try(self):
        poster = Poster([PAYLOAD_OK])
        result = self._convert(poster)
        self.assertEqual(result.md_content, PAYLOAD_OK["document"]["md_content"])
        self.assertEqual(result.response, PAYLOAD_OK)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(poster.calls), 1)
        self.assertEqual(self.sleeper.naps, [])

    def test_request_url_and_timeout_contract(self):
        poster = Poster([PAYLOAD_OK])
        self._convert(poster)
        call = poster.calls[0]
        self.assertEqual(call["url"], f"{self.cfg.docling_url.rstrip('/')}/v1/convert/file")
        self.assertEqual(call["timeout"], REQUEST_TIMEOUT)
        self.assertEqual(REQUEST_TIMEOUT, 2700)  # DESIGN S5.2 literal
        self.assertEqual(call["file_name"], "Selina-Concise-Chemistry-10-chap-1.pdf")
        self.assertEqual(call["file_bytes"], self.pdf)
        self.assertEqual(call["form"], build_form(self.cfg))

    def test_vlm_pipeline_reaches_the_wire(self):
        poster = Poster([PAYLOAD_OK])
        self._convert(poster, pipeline="vlm")
        self.assertEqual(poster.calls[0]["form"]["pipeline"], "vlm")

    def test_transient_fail_then_succeed_returns(self):
        """AC: transient-fail-then-succeed returns."""
        poster = Poster([urllib.error.URLError("Connection refused"), PAYLOAD_OK])
        result = self._convert(poster)
        self.assertEqual(result.md_content, PAYLOAD_OK["document"]["md_content"])
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(poster.calls), 2)
        self.assertEqual(self.sleeper.naps, [BACKOFF_SECONDS])

    def test_transient_exhausts_retries(self):
        poster = Poster([urllib.error.URLError("connect timeout")] * (MAX_RETRIES + 1))
        with self.assertRaises(DoclingError) as ctx:
            self._convert(poster)
        self.assertTrue(ctx.exception.transient)
        self.assertEqual(ctx.exception.attempts, MAX_RETRIES + 1)
        self.assertEqual(len(poster.calls), MAX_RETRIES + 1)
        self.assertEqual(self.sleeper.naps, [BACKOFF_SECONDS] * MAX_RETRIES)

    def test_non_transient_raises_at_first_try(self):
        """AC: non-transient raises at first try (no retry, no backoff)."""
        poster = Poster([urllib.error.HTTPError("url", 400, "Bad Request: invalid picture_description_api", None, None)])
        with self.assertRaises(DoclingError) as ctx:
            self._convert(poster)
        self.assertFalse(ctx.exception.transient)
        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(len(poster.calls), 1)
        self.assertEqual(self.sleeper.naps, [])
        self.assertIsInstance(ctx.exception.__cause__, urllib.error.HTTPError)

    def test_missing_md_content_is_a_hard_error_not_a_retry(self):
        poster = Poster([{"document": {}}])
        with self.assertRaises(DoclingError) as ctx:
            self._convert(poster)
        self.assertFalse(ctx.exception.transient)
        self.assertEqual(len(poster.calls), 1)
        self.assertEqual(self.sleeper.naps, [])

    def test_non_object_response_fails_clean(self):
        poster = Poster([["not", "an", "object"]])
        with self.assertRaises(DoclingError) as ctx:
            self._convert(poster)
        self.assertFalse(ctx.exception.transient)
        self.assertIn("not a JSON object", str(ctx.exception))

    def test_max_retries_overridable_for_tests_downstream(self):
        poster = Poster([urllib.error.URLError("timed out")] * 2)
        with self.assertRaises(DoclingError) as ctx:
            self._convert(poster, max_retries=1)
        self.assertEqual(len(poster.calls), 2)
        self.assertEqual(self.sleeper.naps, [BACKOFF_SECONDS])


if __name__ == "__main__":
    unittest.main()

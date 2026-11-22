"""Seam: pipeline.syllabus_clean — LLM assist + deterministic validator (D6, ticket school-prep-agent-u1k)

u1k AC: "Mock-LLM unit test round-trips validator" — every test below runs the
FULL clean() seam with an injected mock chat (no network, no GPU), then asserts
the validator's verdict, the quarantine behaviour ("invalid output is
quarantined not applied"), and the version recording (prompt + model travel
with the result, DESIGN D6).

Fixtures are grounded in the POC debris shape that motivated the ticket
(~/sandbox/school-prep-harness civics/chapter-1.md): OCR glyph damage, glued
words, embedded sub-headings, exam-instruction prose.
"""
import json
import unittest

from pipeline.config import resolve_config
from pipeline import syllabus_clean
from pipeline.syllabus_clean import clean, prompt_version, validate


# POC debris (civics ch.1 syllabus block, condensed): damaged, fragmented, mixed prose
SOURCE = (
    "## 1 CHAPTER\n"
    "## The Union Legislature\n"
    "### Syllabus\n"
    "Meaning of the Federal Setup in India (i) Lok Sabha — term, composition, "
    "qualifications for membership. Parliameņtary procedures: a brief idea of sessions, "
    "quorum, question hour, adjournment and noconfidence motion.\n"
    "(ii)Rajyα Sabha - composition,  qualifications for membership, election, term, Presiding Officer.\n"
    "Powers and functions of Union Parliament — legislative, financial, judicial.\n"
    "[The events, however need to be mentioned.]\n"
)
# what a well-behaved LLM should return (grounded, within band, no headings)
GOOD = [
    "Lok Sabha — term, composition, qualifications for membership",
    "Sessions, quorum, question hour, adjournment and no-confidence motion",
    "Rajya Sabha — composition, qualifications for membership, election, term, Presiding Officer",
]


class MockChat:
    """The injectable seam recorded every call (url, model, messages, timeout)."""

    def __init__(self, reply: object):
        self.reply = reply
        self.calls: list[tuple] = []

    def __call__(self, url, model, messages, timeout):
        self.calls.append((url, model, len(messages), timeout))
        return self.reply


class ValidatorRoundTripTest(unittest.TestCase):
    """AC 1 — mock-LLM unit test round-trips the validator."""

    def setUp(self):
        self.cfg = resolve_config({})
        self.captured = [
            "Rajyα Sabha - composition,  qualifications for membership, election, term, Presiding Officer"
        ]  # n=1 -> band 1..3

    def test_valid_output_is_applied_and_versioned(self):
        c = MockChat(json.dumps(GOOD))
        res = clean(self.captured, SOURCE, cfg=self.cfg, chat=c)
        self.assertTrue(res.applied)
        self.assertEqual(list(res.items), GOOD)
        self.assertEqual(res.model, self.cfg.llm_model)
        self.assertEqual(res.prompt, "clean-syllabus/v1")
        self.assertEqual(len(c.calls), 1)  # exactly one chat call (u1k: ONE OLLAMA call)
        url, model, n_msgs, timeout = c.calls[0]
        self.assertEqual(url, self.cfg.ollama_url)  # base URL; the adapter appends /api/chat
        self.assertEqual(model, self.cfg.llm_model)
        self.assertEqual(n_msgs, 2)  # system (prompt v1) + user (source + captured)

    def test_non_strict_json_is_rejected(self):
        res = clean(self.captured, SOURCE, cfg=self.cfg, chat=MockChat('```json\n' + json.dumps(GOOD[:2]) + '\n```'))
        self.assertFalse(res.applied)
        self.assertEqual(res.items, ())
        self.assertTrue(any("strict-JSON" in v for v in res.violations))
        self.assertIsNotNone(res.raw)  # quarantine evidence retained

    def test_json_object_instead_of_array_is_rejected(self):
        res = clean(self.captured, SOURCE, cfg=self.cfg, chat=MockChat('{"topics": []}'))
        self.assertFalse(res.applied)
        self.assertTrue(any("expected an array" in v for v in res.violations))

    def test_empty_or_structural_items_are_rejected(self):
        res = clean(
            self.captured, SOURCE, cfg=self.cfg,
            chat=MockChat(json.dumps(["", "# Union Legislature", "Lok " "Sabha\nterm"])),
        )
        self.assertFalse(res.applied)
        self.assertTrue(any("empty" in v for v in res.violations))
        self.assertTrue(any("heading syntax" in v for v in res.violations))
        self.assertTrue(any("multi-line" in v for v in res.violations))

    def test_count_out_of_band_is_rejected_even_when_grounded(self):
        # 9 grounded items vs 1 captured -> outside 50%..3x (u1k contract)
        res = clean(
            self.captured, SOURCE, cfg=self.cfg,
            chat=MockChat(json.dumps(["Sessions", "Quorum", "Question hour", "Adjournment",
                                     "No-confidence motion", "Presiding Officer",
                                     "Membership", "Election", "Federal Setup"])),
        )
        self.assertFalse(res.applied)
        self.assertTrue(any(v.startswith("count:") for v in res.violations))

    def test_invented_item_fails_grounding_and_quarantines(self):
        # "Nuclear fusion" is a real chemistry topic; it is NOT in this source
        res = clean(
            self.captured, SOURCE, cfg=self.cfg,
            chat=MockChat(json.dumps(GOOD[:2] + ["Nuclear fusion and radioactivity"])),
        )
        self.assertFalse(res.applied)
        self.assertTrue(any(v.startswith("grounding:") for v in res.violations))

    def test_llm_outage_is_rejected_not_fatal(self):
        def explode(url, model, messages, timeout):
            raise ConnectionRefusedError("connection refused")

        res = clean(self.captured, SOURCE, cfg=self.cfg, chat=explode)
        self.assertFalse(res.applied)
        self.assertEqual(res.items, ())
        self.assertTrue(any("llm-call failed" in v for v in res.violations))

    def test_empty_answer_quarantines_when_captured_nonempty(self):
        res = clean(self.captured, SOURCE, cfg=self.cfg, chat=MockChat("[]"))
        self.assertFalse(res.applied)
        self.assertTrue(any(v.startswith("count:") for v in res.violations))

    def test_empty_capture_band_is_1_to_15(self):
        ok = clean([], SOURCE, cfg=self.cfg, chat=MockChat(json.dumps(GOOD[:2])))
        self.assertTrue(ok.applied)  # 2 items in 1..15, grounded
        nothing = clean([], SOURCE, cfg=self.cfg, chat=MockChat("[]"))
        self.assertFalse(nothing.applied)  # 0 outside 1..15 — give-up quarantines
        self.assertTrue(any(v.startswith("count:") for v in nothing.violations))
        many = clean(
            [], SOURCE, cfg=self.cfg,
            chat=MockChat(json.dumps(
                ["Sessions", "Quorum", "Question", "Hour", "Adjournment", "Motion",
                 "Officer", "Membership", "Election", "Federal", "Setup", "India",
                 "Parliament", "Financial", "Judicial", "Legislative", "Union"])),
        )
        self.assertFalse(many.applied)  # 17 items > 15
        self.assertTrue(any(v.startswith("count:") for v in many.violations))


class GroundingTest(unittest.TestCase):
    def test_ocr_glyph_variant_is_grounded(self):
        self.assertTrue(syllabus_clean._grounded("Rajya Sabha", "Rajyα Sabha - composition"))

    def test_invention_is_not_grounded(self):
        self.assertFalse(syllabus_clean._grounded("Nuclear fusion", SOURCE))

    def test_exact_phrase_is_grounded(self):
        self.assertTrue(
            syllabus_clean._grounded(
                "Lok Sabha — term, composition, qualifications for membership", SOURCE
            )
        )


class PromptVersionTest(unittest.TestCase):
    def test_default_prompt_records_v1(self):
        self.assertEqual(prompt_version(syllabus_clean.DEFAULT_PROMPT), "clean-syllabus/v1")
        self.assertTrue(syllabus_clean.DEFAULT_PROMPT.is_file())

    def test_bumping_the_file_flips_the_version_with_no_code_change(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "clean-syllabus" / "v2.md"
            p.parent.mkdir()
            p.write_text("v2 prompt body", encoding="utf-8")
            # version is derived from the path; a v2.md anywhere mirrors the scheme
            self.assertEqual(prompt_version(p).rsplit("/", 1)[-1], "v2")


if __name__ == "__main__":
    unittest.main()

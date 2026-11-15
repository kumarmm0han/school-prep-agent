"""Seam: pipeline.syllabus.extract_head_list(md_body) -> (items, confidence)
(ticket school-prep-agent-5x7: DESIGN S5 'Chapter head-list -> syllabus[]').

Contract: first list-like block after the chapter title heading, before the first
content heading. Low-confidence flag = handoff to the LLM clean-pass ticket (u1k).
Fixtures grounded in POC output (school-prep-harness civics/history chapters).
"""
import unittest

from pipeline.syllabus import extract_head_list, slugify


class ExtractHeadListTest(unittest.TestCase):
    def test_bullet_block_is_captured_high_confidence(self):
        body = (
            "## 3 CHAPTER\n"
            "## Chemical Reactions\n"
            "### Syllabus\n"
            "#### Reactions and Equations\n"
            "- Reactions & their types\n"
            "- Balancing of equations\n"
            "- Exothermic & endothermic reactions\n"
        )
        items, conf = extract_head_list(body)
        self.assertEqual(conf, "high")
        self.assertEqual(
            items,
            ["Reactions & their types", "Balancing of equations", "Exothermic & endothermic reactions"],
        )

    def test_numbered_and_enumerated_markers_count_as_list_like(self):
        body = (
            "## 5 CHAPTER\n"
            "## Acids, Bases and Salts\n"
            "### Syllabus\n"
            "1. Preparation and properties of acids\n"
            "(ii) Neutralization\n"
            "(iii) pH scale\n"
        )
        items, conf = extract_head_list(body)
        self.assertEqual(items, ["Preparation and properties of acids", "Neutralization", "pH scale"])
        self.assertEqual(conf, "high")

    def test_stops_at_next_content_heading(self):
        body = (
            "## 5 CHAPTER\n"
            "## Acids, Bases and Salts\n"
            "### Syllabus\n"
            "- Acids\n"
            "- Bases\n"
            "### Theory of Neutralization\n"
            "- distractor item after the content heading must NOT be captured\n"
        )
        items, conf = extract_head_list(body)
        self.assertEqual(items, ["Acids", "Bases"])
        self.assertEqual(conf, "high")

    def test_prose_only_syllabus_is_low_confidence(self):
        # POC history/chapter-8 shape: syllabus is a single prose sentence, no markers
        body = (
            "## 8 CHAPTER\n"
            "## Forward Bloc and The INA\n"
            "### Syllabus\n"
            "Forward Bloc (Objectives) and INA (objectives and contribution of Subhas Chandra Bose).\n"
            "Subhas Chandia Bose was born on 23rd January, 1897...\n"
        )
        items, conf = extract_head_list(body)
        self.assertEqual(conf, "low")
        self.assertEqual(items, [])  # no silent guess: the LLM clean pass (u1k) owns this

    def test_single_item_is_below_the_confidence_floor(self):
        body = "## 6 CHAPTER\n## Electrolysis\n### Syllabus\n- Conductance of electrolytes\n"
        items, conf = extract_head_list(body)
        self.assertEqual(items, ["Conductance of electrolytes"])
        self.assertEqual(conf, "low")

    def test_no_headings_no_block_is_low_confidence(self):
        items, conf = extract_head_list("Just prose.\nMore prose.\n")
        self.assertEqual((items, conf), ([], "low"))


class SlugTest(unittest.TestCase):
    def test_slug_is_deterministic_and_stable(self):
        self.assertEqual(slugify("Chemical Reactions"), "chemical-reactions")
        self.assertEqual(slugify("  Forward Bloc  & The INA "), "forward-bloc-the-ina")
        self.assertEqual(slugify(slugify("pH scale!")), slugify("pH scale!"))

    def test_slug_handles_ocr_noise(self):
        self.assertEqual(slugify("The Union Exccutive"), "the-union-exccutive")  # deterministic, not 'fixed'


if __name__ == "__main__":
    unittest.main()

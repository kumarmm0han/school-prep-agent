"""Seam: pipeline.syllabus.extract_head_list(md_body) -> (items, confidence)
(ticket school-prep-agent-5x7: DESIGN S5 'Chapter head-list -> syllabus[]').

Contract: first list-like block after the chapter title heading, before the first
content heading. Low-confidence flag = handoff to the LLM clean-pass ticket (u1k).
Fixtures grounded in POC output (school-prep-harness civics/history chapters).
"""
import unittest

from pipeline.syllabus import extract_head_list, head_region, slugify


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


class HeadRegionTest(unittest.TestCase):
    """The clean pass (u1k) LLM context: deterministic boundaries, POC debris shapes."""

    def test_title_chain_without_blank_stays_inside(self):
        body = (
            "## 3 CHAPTER\n"
            "## Chemical Reactions\n"
            "### Syllabus\n"
            "#### Reactions and Equations\n"
            "- Reactions & their types\n"
            "- Balancing of equations\n"
        )
        region = head_region(body)
        self.assertTrue(region.startswith("## 3 CHAPTER"))
        self.assertIn("## Chemical Reactions", region)  # title h2 (no blank line before) stays in
        self.assertIn("- Balancing of equations", region)

    def test_thematic_break_ends_the_region(self):
        # POC civics/chapter-1 shape: `---` then the content `##` heading
        body = (
            "## 1 CHAPTER\n"
            "### Syllabus\n"
            "Meaning of the Federal Setup in India (i) Lok Sabha — term, composition.\n"
            "(ii)Rajyα Sabha - composition, qualifications for membership.\n"
            "\n"
            "---\n"
            "\n"
            "## FEDERAL SETUP IN INDIA\n"
            "Content body must not leak into the head region.\n"
        )
        region = head_region(body)
        self.assertIn("Rajyα Sabha", region)
        self.assertNotIn("FEDERAL SETUP IN INDIA", region)
        self.assertNotIn("---", region)

    def test_blank_preceded_h2_after_content_ends_the_region(self):
        body = (
            "## 2 CHAPTER\n"
            "### Syllabus\n"
            "- First topic\n"
            "\n"
            "## Real Content Heading\n"
            "Body prose.\n"
        )
        region = head_region(body)
        self.assertIn("- First topic", region)
        self.assertNotIn("Real Content Heading", region)

    def test_poc_title_chain_with_blanks_stays_inside(self):
        # THE 2026-11-21 regression: the civics ch.1 debris splits its title
        # chain with blank lines; an earlier rule (blank-preceded h2) collapsed
        # the region to one line. All of it is title/syllabus area until the `---`.
        body = (
            "## I. THE UNION LEGISLATURE\n"
            "\n"
            "<!-- image -->\n"
            "\n"
            "## 1 CHAPTER\n"
            "\n"
            "##  The Union Parliament\n"
            "\n"
            "### Syllabus\n"
            "\n"
            "#### 1. The Union Legislature\n"
            "\n"
            "Meaning of the Federal Setup in India (i) Lok Sabha — term, composition.\n"
            "\n"
            "(ii)Rajyα Sabha - composition, qualifications for membership.\n"
            "\n"
            "---\n"
            "\n"
            "## FEDERAL SETUP IN INDIA\n"
            "Body prose must not leak in.\n"
        )
        region = head_region(body)
        self.assertIn("## I. THE UNION LEGISLATURE", region)
        self.assertIn("## 1 CHAPTER", region)
        self.assertIn("Lok Sabha", region)
        self.assertIn("Rajyα Sabha", region)
        self.assertNotIn("FEDERAL SETUP IN INDIA", region)
        self.assertNotIn("---", region)

    def test_image_placeholder_is_not_content(self):
        # `<!-- image -->` residue between title headings must not end the region
        body = (
            "## 3 CHAPTER\n"
            "\n"
            "<!-- image -->\n"
            "\n"
            "### Syllabus\n"
            "\n"
            "- Only topic\n"
            "\n"
            "## Body starts\n"
        )
        region = head_region(body)
        self.assertIn("### Syllabus", region)
        self.assertIn("- Only topic", region)
        self.assertNotIn("Body starts", region)

    def test_syllabus_marker_heading_is_never_a_boundary(self):
        body = (
            "## 4 CHAPTER\n"
            "Intro prose before the syllabus marker.\n"
            "### Syllabus\n"
            "- Alpha topic\n"
            "- Beta topic\n"
            "## Body starts\n"
        )
        region = head_region(body)
        self.assertIn("Intro prose", region)  # pre-marker prose stays in context
        self.assertIn("- Beta topic", region)
        self.assertNotIn("Body starts", region)

    def test_no_headings_gives_empty_region(self):
        self.assertEqual(head_region("Just prose.\nMore prose.\n"), "")


if __name__ == "__main__":
    unittest.main()

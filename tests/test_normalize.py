"""Seam: pipeline.normalize.normalize(md, *, chapter) -> str  (ticket school-prep-agent-1qm)

Contract sources: DESIGN.md S4.1 (body rules), S5 step 3, D2, Gate A (j99).
Fixture debris is grounded in the POC output (~/sandbox/school-prep-harness/civics/chapter-1.md):
skewed heading levels, '<!-- image -->' placeholders, OCR-residue text.
"""
import unittest

from pipeline.normalize import normalize


class ImageRefRewriteTest(unittest.TestCase):
    def test_bare_refs_get_contract_paths_in_order_of_appearance(self):
        src = "## T\n\n![figure](document.png)\ntext\n\n![chart](./assets/x-0002.jpg)\n"
        out = normalize(src, chapter=3)
        self.assertIn("![figure](img/ch3-001.png)", out)
        self.assertIn("![chart](img/ch3-002.jpg)", out)  # original extension preserved

    def test_unknown_extension_defaults_to_png(self):
        self.assertIn("![x](img/ch5-001.png)", normalize("![x](data:whatever-naked)", chapter=5))

    def test_already_conformed_refs_keep_their_number(self):
        src = "![a](img/ch9-004.png)\n\n![b](/tmp/other.png)\n"
        out = normalize(src, chapter=9)
        self.assertIn("![a](img/ch9-004.png)", out)
        self.assertIn("![b](img/ch9-005.png)", out)  # sequences after the max existing, stable re-runs

    def test_rewrite_is_idempotent(self):
        src = "![a](/tmp/one.png)\n\n![b](/tmp/two.png)\n"
        once = normalize(src, chapter=2)
        self.assertEqual(normalize(once, chapter=2), once)


class ImageStructureTest(unittest.TestCase):
    def test_caption_after_image_is_kept_exactly_after_one_blank_line(self):
        # DESIGN S4.1: caption is first-class text and must be kept
        src = "![g](img/ch1-001.png)\n\n\n\n\nApparatus: a beaker over a flame, labels A and B.\n"
        self.assertEqual(normalize(src, chapter=1), "![g](img/ch1-001.png)\n\nApparatus: a beaker over a flame, labels A and B.\n")

    def test_caption_glued_to_image_gets_the_separating_blank_line(self):
        src = "![g](img/ch1-001.png)\nCaption line directly after.\n"
        self.assertEqual(normalize(src, chapter=1), "![g](img/ch1-001.png)\n\nCaption line directly after.\n")

    def test_three_plus_blank_lines_compress_to_one(self):
        src = "## T\na\n\n\n\n\n\nb\n"
        self.assertEqual(normalize(src, chapter=1), "## T\na\n\nb\n")

    def test_structure_is_idempotent(self):
        src = "![g](img/ch1-001.png)\n\n\n\ncaption\n"
        once = normalize(src, chapter=1)
        self.assertEqual(normalize(once, chapter=1), once)

    def test_consecutive_images_each_get_their_separating_blank(self):
        # spec review (c)1: the second image must NOT be glued to its own caption,
        # even when it itself follows a blank line
        src = "![a](img/ch1-001.png)\n\n![b](/tmp/b.png)\ncaption for b\n"
        out = normalize(src, chapter=1)
        self.assertIn("![a](img/ch1-001.png)\n\n![b](img/ch1-002.png)\n\ncaption for b", out)

    def test_inline_image_mid_sentence_is_renumbered_not_structured(self):
        # spec review (a)2: the AC's "inline images" fixture shape — a ref embedded in prose
        src = "## T\nSee ![inline](/tmp/i.png) for the setup.\n"
        out = normalize(src, chapter=6)
        self.assertEqual(out, "## T\nSee ![inline](img/ch6-001.png) for the setup.\n")


class ResidueStripTest(unittest.TestCase):
    def test_placeholder_image_comments_are_removed(self):
        # POC debris: civics/chapter-1.md carries bare "<!-- image -->" placeholder lines
        src = "## T\ntext\n\n<!-- image -->\nmore text\n"
        out = normalize(src, chapter=1)
        self.assertNotIn("<!-- image -->", out)
        self.assertEqual(out, "## T\ntext\n\nmore text\n")

    def test_inline_html_tags_stripped_inner_text_kept(self):
        src = "Quorum means <sup>two-thirds</sup> of members. Line<br>break.\n"
        out = normalize(src, chapter=1)
        self.assertNotIn("<sup>", out)
        self.assertIn("two-thirds", out)
        self.assertIn("Linebreak", out)

    def test_replacement_char_and_zero_width_stripped(self):
        src = "noconfidence \ufffd motion\u200b\n"
        self.assertEqual(normalize(src, chapter=1), "noconfidence  motion\n")

    def test_residue_stripping_idempotent(self):
        src = "a <sup>b</sup> \ufffd c\n\n<!-- image -->"
        once = normalize(src, chapter=1)
        self.assertEqual(normalize(once, chapter=1), once)

    def test_math_markup_is_not_stripped(self):
        # D2: "LaTeX math where docling emits it" — residue stripping must not shred
        # math markup (spec review c2); the residue denylist is the decision point
        src = "Rate law: <msub>v</msub> = k[A]<msup>2</msup>, cf. footnote <sup>1</sup>\n"
        out = normalize(src, chapter=1)
        self.assertIn("<msub>v</msub> = k[A]<msup>2</msup>", out)  # math structure preserved
        self.assertIn("footnote 1", out)  # residue <sup> in the same line IS stripped


class CompositePocDebrisTest(unittest.TestCase):
    """One realistic docling-style chapter fragment (civics ch.1 debris shape):
    placeholder image comment on line 1, skewed 3/4/5 heading levels, the
    Parliamentary/Rajya OCR prose, inline residue chars, one image + caption.
    Expected output is written from the DESIGN S4.1 contract by hand — not by re-running
    the implementation on the input."""

    SRC = (
        "<!-- image -->\n"
        "\n"
        "#####  The Union Parliament\n"
        "\n"
        "### Syllabus\n"
        "\n"
        "#### 1. The Union Legislature\n"
        "\n"
        "Parliamentary procedures: a brief idea of sessions, quorum, question hour, adjournment and no\u200bconfidence motion. Speaker \ufffd election and functions.\n"
        "\n"
        "(ii)Rajya Sabha - composition, qualifications for membership.\n"
        "\n"
        "\n"
        "![Lok Sabha](/docling-out/tmp1/doc.png)\n"
        "\n"
        "\n"
        "A photograph of the Parliament building with the Ashoka Stupa.\n"
    )

    EXPECTED = (
        "####  The Union Parliament\n"
        "\n"
        "## Syllabus\n"
        "\n"
        "### 1. The Union Legislature\n"
        "\n"
        "Parliamentary procedures: a brief idea of sessions, quorum, question hour, adjournment and noconfidence motion. Speaker  election and functions.\n"
        "\n"
        "(ii)Rajya Sabha - composition, qualifications for membership.\n"
        "\n"
        "![Lok Sabha](img/ch4-001.png)\n"
        "\n"
        "A photograph of the Parliament building with the Ashoka Stupa.\n"
    )

    def test_debris_transforms_to_contract(self):
        self.assertEqual(normalize(self.SRC, chapter=4), self.EXPECTED)

    def test_clean_output_is_a_fixed_point(self):
        self.assertEqual(normalize(self.EXPECTED, chapter=4), self.EXPECTED)


class HeadingLevelTest(unittest.TestCase):
    def test_skewed_levels_shift_so_top_level_is_double_hash(self):
        # POC debris shape: civics chapters whose top headings are ####/#####
        src = "#### Top Section\nSome text\n\n##### Sub note\nBody.\n"
        self.assertEqual(normalize(src, chapter=7), "## Top Section\nSome text\n\n### Sub note\nBody.\n")

    def test_well_levelled_document_unchanged(self):
        src = "## Top\nx\n\n### Sub\ny\n"
        self.assertEqual(normalize(src, chapter=1), src)

    def test_single_hash_escalates_down_to_double(self):
        self.assertEqual(normalize("# Sole Top\ntext\n", chapter=1), "## Sole Top\ntext\n")

    def test_non_heading_lines_never_touched(self):
        body = "code-like line starting with #### is not a heading if indented? no — plain text # has no blank-line rule"
        src = f"## T\n{body}\n"
        self.assertEqual(normalize(src, chapter=1), src)  # the named property: body line byte-identical


if __name__ == "__main__":
    unittest.main()

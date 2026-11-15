"""Seam: pipeline.gates.gate_a(md_text, frontmatter, book_dir) -> list[str]
(ticket school-prep-agent-j99: DESIGN S5 step 4, S6.4, Q9 extended invariants).

The engine is pure: it returns a list of human-readable violations (empty == pass).
One failing fixture per invariant, each asserting the RIGHT message.
"""
import unittest

from pipeline.gates import gate_a

PASS_MD = (
    "## Chapter One\n"
    "Intro prose.\n"
    "\n"
    "![figure](img/ch7-001.png)\n"
    "\n"
    "A diagram of the apparatus with labelled steps.\n"
)


class GateAInvariantTest(unittest.TestCase):
    def _fm(self, **over):
        fm = {
            "subject": "Chemistry",
            "board": "ICSE",
            "chapter": 7,
            "title": "Chemical Reactions",
            "syllabus": ["Reactions & their types", "Balancing equations"],
            "tags": ["reactions"],
        }
        fm.update(over)
        return fm

    def test_well_formed_chapter_passes(self):
        self.assertEqual(gate_a(PASS_MD, self._fm(), None), [])

    # ---- chapter-record mapping (spec review a)2: violations => qa_failed) ----
    def test_clean_chapter_maps_to_pass_record(self):
        from pipeline.gates import evaluate_chapter

        rec = evaluate_chapter(7, PASS_MD, self._fm(), None,
                               timings={"convert_s": 10.0}, models={"vlm": "qwen3-vl:8b"}, docling_version="1.26.0")
        self.assertEqual(rec["status"], "pass")
        self.assertNotIn("violations", rec)
        self.assertEqual(rec["timings"], {"convert_s": 10.0})
        self.assertEqual(rec["docling_version"], "1.26.0")

    def test_violations_map_to_qa_failed_with_violations(self):
        from pipeline.gates import evaluate_chapter

        rec = evaluate_chapter(2, "## T\n![fig](img/ch2-001.png)\n", self._fm(), None)
        self.assertEqual(rec["status"], "qa_failed")
        self.assertTrue(any("caption" in x.lower() for x in rec["violations"]), rec)

    def test_skip_maps_to_skipped_without_rerunning_gates(self):
        from pipeline.gates import evaluate_chapter

        rec = evaluate_chapter(3, "   \n", self._fm(), None, skip_reason="idempotent: provenance matches")
        self.assertEqual(rec["status"], "skipped")
        self.assertEqual(rec["skip_reason"], "idempotent: provenance matches")

    def test_fail_status_is_distinct_from_qa_failed(self):
        # spec review a)3: the record vocabulary must keep them apart
        from pipeline.report import VALID_STATUSES, summary_counts

        self.assertNotEqual(VALID_STATUSES.index("fail"), VALID_STATUSES.index("qa_failed"))
        counts = summary_counts([{"chapter": 1, "status": "fail"}, {"chapter": 2, "status": "qa_failed"}])
        self.assertEqual(counts, {"fail": 1, "qa_failed": 1})


    def test_run_exit_code_rule(self):
        from pipeline.report import run_exit_code

        self.assertEqual(run_exit_code([{"chapter": 1, "status": "pass"}, {"chapter": 2, "status": "skipped"}]), 0)
        self.assertEqual(run_exit_code([{"chapter": 1, "status": "pass"}, {"chapter": 2, "status": "qa_failed"}]), 1)
        self.assertEqual(run_exit_code([{"chapter": 1, "status": "fail"}]), 1)

    def test_empty_body_caught(self):
        v = gate_a("   \n", self._fm(), None)
        self.assertTrue(any("non-empty" in x for x in v), v)

    def test_no_level_two_heading_caught(self):
        v = gate_a("### only deeper\nprose\n", self._fm(), None)
        self.assertTrue(any("level-2" in x or "## " in x for x in v), v)

    def test_image_without_caption_caught(self):
        v = gate_a("## T\n![fig](img/ch7-001.png)\n", self._fm(), None)
        self.assertTrue(any("caption" in x.lower() for x in v), v)

    def test_inline_image_ref_caught(self):
        # spec review (c)2: a ref embedded in a prose line is exempted by "standalone
        # line only" logic — S5.4 says EVERY image ref has a caption line
        v = gate_a("## T\nSee ![fig](img/ch7-001.png) here for details.\n", self._fm(), None)
        self.assertTrue(any("caption" in x.lower() or "inline" in x.lower() for x in v), v)

    def test_replacement_char_caught(self):
        v = gate_a("## T\nbody \ufffd here\n", self._fm(), None)
        self.assertTrue(any("U+FFFD" in x or "FFFD" in x for x in v), v)

    def test_empty_syllabus_caught(self):
        v = gate_a(PASS_MD, self._fm(syllabus=[]), None)
        self.assertTrue(any("syllabus" in x.lower() for x in v), v)

    # ---- extended invariants (Q9) ----
    def test_syllabus_count_below_floor_caught(self):
        v = gate_a("## T\nprose\n", self._fm(syllabus=["Only one item"]), None)
        self.assertTrue(any("syllabus" in x.lower() and ("2" in x or "fewer" in x or "count" in x.lower()) for x in v), v)

    def test_syllabus_count_above_ceiling_caught(self):
        v = gate_a("## T\nprose\n", self._fm(syllabus=[f"item-{i}" for i in range(16)]), None)
        self.assertTrue(any("syllabus" in x.lower() for x in v), v)

    def test_heading_hierarchy_violation_caught(self):
        v = gate_a("### deep before top\n## top later\nprose\n", self._fm(), None)
        self.assertTrue(any("heading" in x.lower() for x in v), v)

    def test_level_jump_catches_skewed_structure(self):
        # spec review (c)1: ## -> #### is the non-uniform skew signal (POC debris shape)
        v = gate_a("## A\nintro\n\n#### Jumpy\nbody\n", self._fm(), None)
        self.assertTrue(any("heading" in x.lower() for x in v), v)

    def test_sibling_sections_are_well_formed(self):
        # legitimate layout: two ## sections each with one ### subsection — must pass
        self.assertEqual(
            gate_a("## One\nintro\n\n### Sub\nbody\n\n## Two\nmore\n\n### Sub2\nbody\n", self._fm(), None),
            [],
        )

    def test_level_one_heading_caught(self):
        v = gate_a("# top-level\n## real top\nbody\n", self._fm(), None)
        self.assertTrue(any("heading" in x.lower() for x in v), v)

    def test_placeholder_residue_caught(self):
        v = gate_a("## T\nTODO fix this\nprose\n\nFigure: image\n", self._fm(), None)
        self.assertTrue(any("placeholder" in x.lower() or "residue" in x.lower() for x in v), v)

    def test_blob_missing_caught_when_book_dir_given(self, ):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            book = Path(d) / "book"
            img = book / "img"
            img.mkdir(parents=True)
            # PASS_MD references img/ch7-001.png which we do NOT create
            v = gate_a(PASS_MD, self._fm(), book)
            self.assertTrue(any("blob" in x.lower() or "not found" in x.lower() or "exists" in x.lower() for x in v), v)

    def test_blob_present_passes_when_book_dir_given(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            book = Path(d) / "book"
            img = book / "img"
            img.mkdir(parents=True)
            (img / "ch7-001.png").write_bytes(b"\x89PNG")
            v = gate_a(PASS_MD, self._fm(), book)
            self.assertFalse(any("blob" in x.lower() for x in v), v)


if __name__ == "__main__":
    unittest.main()

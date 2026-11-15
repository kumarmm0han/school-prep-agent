"""Seam: pipeline.frontmatter.assemble/parse (ticket school-prep-agent-5x7, DESIGN S4.1 + D3).

AC (ticket): chap-1..3 fixtures produce valid front matter; non-empty canonical syllabus;
provenance sha256 EQUALS the actual file hash; ambiguous input handled via the syllabus
module's low-confidence flag (covered in test_syllabus).
"""
import hashlib
import unittest

import yaml

from pipeline.frontmatter import assemble, parse_frontmatter


class AssembleTest(unittest.TestCase):
    def _inputs(self, **over):
        base = dict(
            subject="Chemistry", board="ICSE", class_=10, chapter=7,
            title="Chemical Reactions",
            syllabus=["Reactions & their types", "Balancing of equations"],
            source_path=None,  # provenance-from-file is exercised separately with a real temp file
            docling_version="1.26.0", pipeline="standard", vlm_model="qwen3-vl:8b",
            pages=12, converted_at="2026-11-15T12:00:00Z",
        )
        base.update(over)
        return base

    def test_full_contract_round_trips(self):
        md = assemble(**self._inputs(section="I. Chemical Reactions"))
        data, body = parse_frontmatter(md)
        self.assertEqual(data["subject"], "Chemistry")
        self.assertEqual(data["board"], "ICSE")
        self.assertEqual(data["class"], 10)
        self.assertEqual(data["section"], "I. Chemical Reactions")
        self.assertEqual(data["chapter"], 7)
        self.assertEqual(data["title"], "Chemical Reactions")
        self.assertEqual(data["syllabus"], ["Reactions & their types", "Balancing of equations"])
        self.assertEqual(data["file"], "chapter-7.md")
        self.assertEqual(body, "")  # assemble emits front matter only; the body is the caller's

    def test_sha256_matches_the_actual_file_hash(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / "Selina-Concise-Chemistry-10-chap-1.pdf"
            blob = b"%PDF-1.4 fake chapter 1 bytes"
            pdf.write_bytes(blob)
            expected = hashlib.sha256(blob).hexdigest()

            md = assemble(**self._inputs(chapter=1, source_path=pdf, title="Chemical Reactions"))
            data, _ = parse_frontmatter(md)
            self.assertEqual(data["provenance"]["sha256"], expected)
            self.assertEqual(data["provenance"]["source"], "Selina-Concise-Chemistry-10-chap-1.pdf")

    def test_section_none_is_omitted_not_null(self):
        data, _ = parse_frontmatter(assemble(**self._inputs(section=None)))
        self.assertNotIn("section", data)

    def test_tags_default_to_deterministic_title_slugs(self):
        data, _ = parse_frontmatter(assemble(**self._inputs(title="Forward Bloc and The INA")))
        self.assertEqual(data["tags"], ["forward-bloc-and-the-ina"])

    def test_explicit_tags_win_over_slug_default(self):
        data, _ = parse_frontmatter(
            assemble(**self._inputs(tags=["reactions", "balancing"]))
        )
        self.assertEqual(data["tags"], ["reactions", "balancing"])

    def test_assembly_is_deterministic(self):
        a = assemble(**self._inputs())
        b = assemble(**self._inputs())
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()

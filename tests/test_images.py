"""Seam: image blob extraction + shared imgseq contract (ticket school-prep-agent-529).

ACs under test:
  - a response document with N images yields exactly N files under img/ whose names
    match the refs rewritten by normalize 1:1
  - re-run is idempotent (same files, zero rewrites)
  - a response without images yields no files and unchanged refs
  - seq numbering shared with the normalizer (helper imported by both)
Fail-loud clause (529): a ref whose blob is absent/undecodable is left unwritten and
Gate A's blob-existence check (j99) then flags the chapter — never a silent drop.
Plus the docling-serve client's optional image_export_mode (DESIGN S5 step 3:
"extract image blobs ... if embedded" requires requesting embedded mode).
"""
import base64
import unittest
from pathlib import Path

from pipeline import gates, images, imgseq, normalize
from pipeline.config import resolve_config
from pipeline.docling_client import build_form

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()
JPG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 16).decode()

MD_EMBEDDED = (
    "## Chapter Five\n\n"
    "Intro prose.\n\n"
    f"![fig](data:image/png;base64,{PNG})\n\n"
    "Apparatus: a beaker over a flame, labels A and B.\n\n"
    "## Analysis\n\n"
    f"![chart](data:image/jpeg;base64,{JPG})\n\n"
    "Chart of the equilibrium shift.\n"
)


class ImgseqContractTest(unittest.TestCase):
    """The shared helper is imported by BOTH normalize (rewrite) and images (extraction)."""

    def test_memoized_per_distinct_source(self):
        # the same source ref twice is ONE file, not two (extraction can't fork)
        m = imgseq.assign(4, "![a](/tmp/same.png)\n\n![b](/tmp/same.png)\n")
        self.assertEqual(m, {"/tmp/same.png": "img/ch4-001.png"})

    def test_new_ref_continues_after_highest_conformed(self):
        m = imgseq.assign(5, "![a](img/ch5-010.png)\n\n![b](/tmp/x.png)\n")
        self.assertEqual(m, {"img/ch5-010.png": "img/ch5-010.png", "/tmp/x.png": "img/ch5-011.png"})

    def test_extension_mime_for_data_uris_else_trailing_ext_else_png(self):
        self.assertEqual(imgseq.extension_of("data:image/jpeg;base64,AAA"), "jpg")
        self.assertEqual(imgseq.extension_of("data:image/webp;base64,AAA"), "webp")
        self.assertEqual(imgseq.extension_of("data:whatever-naked"), "png")  # 1qm rule preserved
        self.assertEqual(imgseq.extension_of("x/y/z.gif"), "gif")

    def test_rewrite_is_idempotent(self):
        once = imgseq.rewrite("![a](/tmp/one.png)\n\n![b](/tmp/two.png)\n", 2)
        self.assertEqual(imgseq.rewrite(once, 2), once)


class ExtractTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.book_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_n_images_yield_exactly_n_files_matching_rewritten_refs_1_1(self):
        files = images.extract(MD_EMBEDDED, 5, self.book_dir)
        self.assertEqual([p.relative_to(self.book_dir).as_posix() for p in files],
                         ["img/ch5-001.png", "img/ch5-002.jpg"])
        # the names match what normalize rewrites the refs to, 1:1 (shared contract)
        normalized = normalize.normalize(MD_EMBEDDED, chapter=5)
        refs = imgseq.iter_ref_paths(normalized)
        self.assertEqual(refs, ["img/ch5-001.png", "img/ch5-002.jpg"])
        self.assertEqual(set(refs), {p.relative_to(self.book_dir).as_posix() for p in files})
        # and every written file matches the rewritten ref set
        for p in files:
            self.assertTrue(p.is_file())
            self.assertGreater(p.stat().st_size, 0)

    def test_re_run_is_idempotent_zero_rewrites(self):
        images.extract(MD_EMBEDDED, 5, self.book_dir)
        before = {p: p.read_bytes() for p in self.book_dir.rglob("*") if p.is_file()}
        again = images.extract(MD_EMBEDDED, 5, self.book_dir)
        self.assertEqual(again, [])  # zero rewrites
        after = {p: p.read_bytes() for p in self.book_dir.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_no_images_yields_no_files_and_unchanged_refs(self):
        md = "## T\n\nProse only, no figures at all.\n"
        files = images.extract(md, 7, self.book_dir)
        self.assertEqual(files, [])
        self.assertFalse((self.book_dir / "img").exists())
        self.assertEqual(imgseq.iter_ref_paths(normalize.normalize(md, chapter=7)), [])

    def test_ref_without_blob_is_left_unwritten_and_gate_a_flags_it(self):
        # fail-loud, never a silent drop (529): undecodable payload -> no file, no crash,
        # and Gate A's blob-existence check (j99) fails the chapter
        bad = "## T\n\n![ghost](data:image/png;base64,!!!not-base64!!!)\n\ncaption line\n"
        files = images.extract(bad, 2, self.book_dir)
        self.assertEqual(files, [])
        normalized = normalize.normalize(bad, chapter=2)
        self.assertIn("img/ch2-001.png", normalized)  # ref rewritten to the contract path
        violations = gates.gate_a(normalized, {"syllabus": ["a", "b"]}, self.book_dir)
        self.assertTrue(any("image blob" in v for v in violations), violations)


class ClientImageModeTest(unittest.TestCase):
    """The pipeline needs embedded mode (DESIGN S5 step 3); the s3c frozen form is the default."""

    def setUp(self):
        self.cfg = resolve_config({})

    def test_default_form_is_the_frozen_set_without_image_export_mode(self):
        form = build_form(self.cfg)
        self.assertNotIn("image_export_mode", form)
        self.assertEqual(
            set(form),
            {"to_format", "force_ocr", "do_table_structure", "include_images",
             "pipeline", "do_picture_description", "picture_description_api"},
        )

    def test_embedded_mode_is_requestable(self):
        self.assertEqual(build_form(self.cfg, image_export_mode="embedded")["image_export_mode"], "embedded")

    def test_invalid_mode_rejected_naming_the_supported_set(self):
        with self.assertRaises(ValueError) as ctx:
            build_form(self.cfg, image_export_mode="base64")
        self.assertIn("embedded", str(ctx.exception))
        self.assertIn("placeholder", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

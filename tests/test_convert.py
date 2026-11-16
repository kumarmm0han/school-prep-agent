"""Seam: convert orchestrator ENGINE (ticket school-prep-agent-agp; DESIGN S5, D4).

Written AC-first — the ticket's acceptance criteria are the test names' shape:
  AC1  a two-chapter batch with one FORCED failure still writes BOTH records and exits non-zero
  AC2  re-run with no changes makes ZERO docling requests
  AC3  --force re-converts
  AC4  chap-00 never yields chapter-0.md
plus the engine behaviours those ACs rest on (isolation D4, skip-condition detail,
--chapter selection, qa_failed syllabus handoff, provenance wiring).

The docling seam is the s3c `poster` injection (no network); reports go to a tmp dir.
"""
import hashlib
import json
import unittest

from pipeline import convert
from pipeline.config import resolve_config
from pipeline.frontmatter import parse_frontmatter

MD_OK = (
    "## Chapter One: Basic Concepts\n\n"
    "### Syllabus\n\n"
    "- Atom, molecule and ion\n"
    "- Chemical formulae\n\n"
    "- Balanced chemical equations\n\n"
    "### Body\n\n"
    "Prose about the mole, atoms and molecules.\n"
)
PAYLOAD_OK = {"document": {"md_content": MD_OK}, "status": "success", "errors": []}

MD_NO_SYLLABUS = "## T\n\nJust prose. No head-list anywhere in this one.\n"


class Poster:
    """s3c poster seam: routes keyed on a filename substring; records every call."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[str] = []
        self.form_log: list[dict] = []

    def __call__(self, url, form, file_name, file_bytes, timeout):
        self.calls.append(file_name)
        self.form_log.append(dict(form))
        for key, outcome in self.routes.items():
            if key in file_name:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"no poster route for {file_name}")


class Sleeper:
    def __init__(self):
        self.naps: list[float] = []

    def __call__(self, seconds):
        self.naps.append(seconds)


class ConvertEngineTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.book = __import__("pathlib").Path(root) / "books/chemistry/ICSE-10thGrade"
        self.book.mkdir(parents=True)
        # chap-00 (index material, plq) is present in the book dir to guard AC4
        (self.book / "Selina-Concise-Chemistry-10-chap-00.pdf").write_bytes(b"%PDF-1.4 zero")
        (self.book / "Selina-Concise-Chemistry-10-chap-1.pdf").write_bytes(b"%PDF-1.4 one")
        (self.book / "Selina-Concise-Chemistry-10-chap-2.pdf").write_bytes(b"%PDF-1.4 two")
        self.reports = __import__("pathlib").Path(root) / "reports"
        self.cfg = resolve_config({})

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *cli, poster, stamp, **kw):
        return convert.run(
            ["--book-dir", str(self.book), *cli],
            poster=poster,
            sleeper=Sleeper(),
            reports_dir=self.reports,
            stamp=stamp,
            **kw,
        )

    def records(self, stamp):
        lines = (self.reports / f"convert-{stamp}.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    # ---------------------------------------------------------------- AC 1
    def test_ac1_batch_of_two_with_forced_failure_writes_both_records_exits_nonzero(self):
        poster = Poster(
            {
                "chap-1.pdf": PAYLOAD_OK,
                "chap-2.pdf": ValueError("server rejected: invalid option (non-transient)"),  # forced failure
            }
        )
        code = self.cli(poster=poster, stamp="AC1")
        recs = self.records("AC1")
        self.assertEqual(code, 1)  # non-zero exit (any chapter failed)
        self.assertEqual([(r["chapter"], r["status"]) for r in recs], [(1, "pass"), (2, "fail")])
        self.assertTrue((self.book / "chapter-1.md").is_file())  # winner's artifact written
        self.assertFalse((self.book / "chapter-2.md").exists())  # loser's not — nothing to trust
        self.assertIn("invalid option", recs[1]["error"])  # root cause carried through the client wrap
        self.assertIn("transient=False", recs[1]["error"])
        # batch continued through the failure (D4): the .status file (written LAST) exists
        status = json.loads((self.reports / "convert-AC1.status").read_text(encoding="utf-8"))
        self.assertEqual(status["exit_code"], 1)
        self.assertEqual(status["chapters"], {"1": "pass", "2": "fail"})
        self.assertEqual(poster.calls, [f for f in poster.calls if "chap-" in f])  # sanity
        self.assertEqual(len(poster.calls), 2)

    # ---------------------------------------------------------------- AC 2
    def test_ac2_re_run_with_no_changes_makes_zero_docling_requests(self):
        ok = Poster({"chap-1.pdf": PAYLOAD_OK, "chap-2.pdf": PAYLOAD_OK})
        self.assertEqual(self.cli(poster=ok, stamp="AC2a"), 0)
        self.assertEqual(len(ok.calls), 2)
        again = Poster({})  # any request is a test failure (AssertionError)
        code = self.cli(poster=again, stamp="AC2b")
        self.assertEqual(code, 0)
        self.assertEqual(again.calls, [])  # ZERO docling requests
        self.assertEqual([(r["chapter"], r["status"]) for r in self.records("AC2b")],
                         [(1, "skipped"), (2, "skipped")])
        self.assertIn("up-to-date", self.records("AC2b")[0]["skip_reason"])

    # ---------------------------------------------------------------- AC 3
    def test_ac3_force_reconverts(self):
        ok = Poster({"chap-1.pdf": PAYLOAD_OK, "chap-2.pdf": PAYLOAD_OK})
        self.assertEqual(self.cli(poster=ok, stamp="AC3a"), 0)
        forced = Poster({"chap-1.pdf": PAYLOAD_OK, "chap-2.pdf": PAYLOAD_OK})
        code = self.cli("--force", poster=forced, stamp="AC3b")
        self.assertEqual(code, 0)
        self.assertEqual(len(forced.calls), 2)  # re-converted despite being up to date
        self.assertEqual([(r["chapter"], r["status"]) for r in self.records("AC3b")],
                         [(1, "pass"), (2, "pass")])

    # ---------------------------------------------------------------- AC 4
    def test_ac4_chap_00_never_yields_chapter_0(self):
        poster = Poster({"chap-1.pdf": PAYLOAD_OK, "chap-2.pdf": PAYLOAD_OK})
        self.cli(poster=poster, stamp="AC4")
        self.assertFalse((self.book / "chapter-0.md").exists())
        self.assertEqual([r["chapter"] for r in self.records("AC4")], [1, 2])
        self.assertFalse(any("chap-00" in c for c in poster.calls))

    # ------------------------------------------------------------ engine detail
    def test_successful_chapter_carrys_provenance_matching_the_source(self):
        poster = Poster({"chap-1.pdf": PAYLOAD_OK})
        self.cli("--chapter", "1", poster=poster, stamp="PROV")
        data, body = parse_frontmatter((self.book / "chapter-1.md").read_text(encoding="utf-8"))
        pdf = self.book / "Selina-Concise-Chemistry-10-chap-1.pdf"
        self.assertEqual(data["provenance"]["sha256"], hashlib.sha256(pdf.read_bytes()).hexdigest())
        self.assertEqual(data["provenance"]["source"], pdf.name)
        self.assertEqual(data["syllabus"], ["Atom, molecule and ion", "Chemical formulae",
                                            "Balanced chemical equations"])
        self.assertEqual(data["title"], "Chapter One: Basic Concepts")
        # ADR-0005 frozen contract reaches the wire: OCR + tables, picture-free
        form = poster.form_log[0]
        self.assertEqual(form["include_images"], "false")
        self.assertNotIn("do_picture_description", form)
        self.assertNotIn("picture_description_api", form)

    def test_selecting_a_single_chapter_only_converts_that_one(self):
        poster = Poster({"chap-2.pdf": PAYLOAD_OK})
        code = self.cli("--chapter", "2", poster=poster, stamp="ONE")
        self.assertEqual(code, 0)
        self.assertEqual(poster.calls, ["Selina-Concise-Chemistry-10-chap-2.pdf"])

    def test_unknown_chapter_is_actionable_not_silent(self):
        poster = Poster({})
        code = self.cli("--chapter", "99", poster=poster, stamp="MISS")
        self.assertEqual(code, 2)
        self.assertEqual(poster.calls, [])  # nothing was attempted
        self.assertFalse((self.reports / "convert-MISS.jsonl").exists())  # no misleading report

    def test_stale_source_reconverts(self):
        ok = Poster({"chap-1.pdf": PAYLOAD_OK})
        self.cli("--chapter", "1", poster=ok, stamp="STALE-a")
        (self.book / "Selina-Concise-Chemistry-10-chap-1.pdf").write_bytes(b"%PDF-1.4 one REV2")
        again = Poster({"chap-1.pdf": PAYLOAD_OK})
        self.cli("--chapter", "1", poster=again, stamp="STALE-b")
        self.assertEqual(len(again.calls), 1)  # provenance.sha256 no longer matches -> re-convert

    def test_missing_syllabus_is_qa_failed_and_waits_for_the_clean_pass(self):
        poster = Poster({"chap-1.pdf": {"document": {"md_content": MD_NO_SYLLABUS}}})
        code = self.cli("--chapter", "1", poster=poster, stamp="NOSYL")
        recs = self.records("NOSYL")
        self.assertEqual(code, 1)
        self.assertEqual(recs[0]["status"], "qa_failed")
        self.assertTrue(any("syllabus" in v for v in recs[0]["violations"]))
        # body written for inspection (u1k handoff), and NOT up-to-date (must re-convert after a fix)
        self.assertTrue((self.book / "chapter-1.md").is_file())
        self.assertFalse(convert.is_up_to_date(self.book / "chapter-1.md",
                                               self.book / "Selina-Concise-Chemistry-10-chap-1.pdf"))

    def test_book_meta_from_the_design_layout(self):
        self.assertEqual(convert.book_meta(self.book), ("Chemistry", "ICSE", 10))

    def test_discover_chapters_sorted_and_zero_excluded(self):
        nums = [n for n, _p in convert.discover_chapters(self.book)]
        self.assertEqual(nums, [1, 2])

    def test_usage_error_without_book_dir(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
            convert.run([], poster=Poster({}), sleeper=Sleeper(), reports_dir=self.reports, stamp="U")
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("convert:", buf.getvalue() or "")  # argparse names the verb


if __name__ == "__main__":
    unittest.main()

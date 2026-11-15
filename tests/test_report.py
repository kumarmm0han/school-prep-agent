"""Seam: pipeline.report (DESIGN D4 j99 + Q11 detached-run contract).
records -> reports/convert-<stamp>.jsonl + console summary + convert-<stamp>.status
ticket: school-prep-agent-j99
"""
import json
import unittest

from pipeline import report


class ReportWriterTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.td = tempfile.TemporaryDirectory()
        self.reports = Path(self.td.name)  # TemporaryDirectory() already created the dir

    def tearDown(self):
        self.td.cleanup()

    RECORDS = [
        {"chapter": 1, "status": "pass", "title": "Chemical Reactions", "timings": {"convert_s": 42.1},
         "models": {"vlm": "qwen3-vl:8b"}, "docling_version": "1.26.0"},
        {"chapter": 2, "status": "qa_failed", "violations": ["GATE-A caption: image ref on line 9 has no caption line following it"]},
        {"chapter": 3, "status": "skipped"},
    ]

    def test_jsonl_written_with_exact_name_and_order(self):
        p = report.write_run_report(self.RECORDS, self.reports, "20261115T060000Z")
        self.assertEqual(p.name, "convert-20261115T060000Z.jsonl")
        lines = p.read_text().splitlines()
        self.assertEqual([json.loads(l)["chapter"] for l in lines], [1, 2, 3])
        self.assertEqual(json.loads(lines[1])["violations"][0].startswith("GATE-A"), True)

    def test_summary_counts_and_per_chapter_lines(self):
        s = report.render_summary(self.RECORDS)
        self.assertIn("1 pass", s)
        self.assertIn("1 qa_failed", s)
        self.assertIn("1 skipped", s)
        self.assertIn("ch 2", s)
        self.assertIn("GATE-A caption", s)  # violations surface in the human summary

    def test_fail_and_qa_failed_bucket_separately(self):
        # spec review a)3: both buckets coexist distinctly in the human summary
        s = report.render_summary([
            {"chapter": 1, "status": "fail"},
            {"chapter": 2, "status": "qa_failed", "violations": ["GATE-A syllabus: 0 items"]},
        ])
        self.assertIn("1 fail", s)
        self.assertIn("1 qa_failed", s)

    def test_status_file_records_exit_and_counts(self):
        p = report.write_status_file(self.RECORDS, 1, self.reports, "20261115T060000Z")
        self.assertEqual(p.name, "convert-20261115T060000Z.status")
        data = json.loads(p.read_text())
        self.assertEqual(data["exit_code"], 1)
        self.assertEqual(data["counts"], {"pass": 1, "qa_failed": 1, "skipped": 1})
        self.assertIn("20261115T060000Z", data["stamp"])

    def test_latest_status_picks_newest_and_survives_relogin(self):
        report.write_status_file(self.RECORDS, 1, self.reports, "20261114T100000Z")
        report.write_status_file([{"chapter": 9, "status": "pass"}], 0, self.reports, "20261115T020000Z")
        latest = report.latest_status(self.reports)
        self.assertEqual(latest["stamp"], "20261115T020000Z")
        self.assertEqual(latest["exit_code"], 0)

    def test_latest_status_none_when_no_reports(self):
        self.assertIsNone(report.latest_status(self.reports))

    def test_detached_run_survives_parent_exit(self):
        # j99 AC (Q11): "run detached via setsid+nohup, kill the parent session, run must
        # continue with logs intact." The bash launcher IS the parent — it exits
        # immediately; the orphaned python run must still finish and write .status.
        import shlex
        import subprocess
        import time
        from pathlib import Path

        repo = Path(__file__).resolve().parents[1]
        stamp = f"KILL{int(time.time())}Z"
        code = (
            "import time; time.sleep(2)\n"
            "from pipeline import report\n"
            "recs = [{'chapter': 1, 'status': 'pass'}, {'chapter': 2, 'status': 'qa_failed', "
            "'violations': ['GATE-A caption: demo']}, {'chapter': 3, 'status': 'skipped'}]\n"
            f"report.write_run_report(recs, {str(self.reports)!r}, {stamp!r})\n"
            f"report.write_status_file(recs, 1, {str(self.reports)!r}, {stamp!r})\n"
            f"open({str(self.reports / 'kill.log')!r}, 'a').write('run finished\\n')\n"
        )
        launcher = subprocess.Popen(
            ["bash", "-c", f"setsid nohup python3 -c {shlex.quote(code)} > {str(self.reports / 'kill.log')} 2> /tmp/opencode/child_stderr.log < /dev/null & exit 0"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        launcher.wait()  # PARENT SESSION IS NOW DEAD — the run must continue on its own

        status_file = self.reports / f"convert-{stamp}.status"
        deadline = time.time() + 30
        while not status_file.exists() and time.time() < deadline:
            time.sleep(0.2)
        self.assertTrue(status_file.exists(), "detached run did not finish after parent exit")
        latest = report.latest_status(self.reports)
        self.assertEqual(latest["stamp"], stamp)
        self.assertEqual(latest["exit_code"], 1)
        self.assertIn("run finished", (self.reports / "kill.log").read_text())  # logs intact

    def test_status_cli_returns_recorded_exit_code(self):
        import io
        from contextlib import redirect_stdout
        from pipeline import status as status_cli

        report.write_status_file(self.RECORDS, 1, self.reports, "20261115T060000Z")
        out = io.StringIO()
        with redirect_stdout(out):
            rc = status_cli.run(["--latest"], reports_dir=self.reports)
        self.assertEqual(rc, 1)  # surfaces the recorded run's exit code
        self.assertIn("ch 2", out.getvalue())

    def test_status_cli_without_reports_is_nonzero(self):
        from pipeline import status as status_cli

        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            rc = status_cli.run(["--latest"], reports_dir=self.reports)
        self.assertNotEqual(rc, 0)
        self.assertIn("no run report", out.getvalue().lower())


if __name__ == "__main__":
    unittest.main()

import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


SKILL_DIR = pathlib.Path(__file__).resolve().parents[1]
LEXICON_PATH = SKILL_DIR / "slop.json"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SKILL_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


humanizer = load_module("humanize")
detector = load_module("detect")
with LEXICON_PATH.open(encoding="utf-8") as lexicon_file:
    LEXICON = json.load(lexicon_file)


class HumanizeTests(unittest.TestCase):
    def test_removes_invisible_characters_and_normalizes_typography(self):
        draft = "A\u200b\u00a0robust plan — ready… ‘now’"

        cleaned, report = humanizer.humanize(draft, LEXICON)

        self.assertEqual(cleaned, "A solid plan, ready... 'now'\n")
        self.assertTrue(report["invisible"])
        self.assertTrue(report["typographic"])
        self.assertTrue(report["lexical"])

    def test_does_not_rewrite_urls(self):
        url = "https://example.com/robust?next=leverage"

        cleaned, _ = humanizer.humanize(f"Leverage this link: {url}", LEXICON)

        self.assertIn(url, cleaned)
        self.assertEqual(cleaned, f"Use this link: {url}\n")

    def test_flags_structural_tells_without_rewriting_them(self):
        draft = "It's not just a plan, it's a strategy."

        cleaned, report = humanizer.humanize(draft, LEXICON)

        self.assertEqual(cleaned, draft + "\n")
        self.assertTrue(report["structures"])

    def test_cli_emits_valid_json(self):
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["humanize.py", "--json"]), \
                patch.object(sys, "stdin", io.StringIO("A robust plan.")), \
                contextlib.redirect_stdout(stdout):
            humanizer.main()

        self.assertEqual(json.loads(stdout.getvalue())["text"], "A solid plan.\n")

    def test_cli_reports_missing_input_without_traceback(self):
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["humanize.py", "missing-draft.txt"]), \
                contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit) as raised:
            humanizer.main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("could not read input or lexicon", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


class DetectorTests(unittest.TestCase):
    def test_all_checks_return_bounded_scores(self):
        results, overall, verdict = detector.run("Short draft.", LEXICON)

        self.assertEqual(set(results), set(detector.CHECKS))
        self.assertTrue(all(0 <= score <= 100 for score, _ in results.values()))
        self.assertTrue(0 <= overall <= 100)
        self.assertIn(verdict, {"PASS", "REVIEW", "FLAGGED"})

    def test_empty_text_has_safe_fingerprint_score(self):
        score, detail = detector.check_fingerprint("")

        self.assertEqual(score, 100)
        self.assertIn("0 invisible", detail)

    def test_cli_json_has_expected_result_shape(self):
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["detect.py", "-", "--json"]), \
                patch.object(sys, "stdin", io.StringIO("A short draft.")), \
                contextlib.redirect_stdout(stdout):
            detector.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(set(payload["checks"]), set(detector.CHECKS))
        self.assertIn("human_score", payload)
        self.assertIn(payload["verdict"], {"PASS", "REVIEW", "FLAGGED"})

    def test_cli_reports_invalid_lexicon_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lexicon_path = pathlib.Path(temp_dir) / "slop.json"
            lexicon_path.write_text("{", encoding="utf-8")
            stderr = io.StringIO()
            with patch.object(
                sys, "argv", ["detect.py", "--lexicon", str(lexicon_path)]
            ), contextlib.redirect_stderr(stderr), self.assertRaises(
                SystemExit
            ) as raised:
                detector.main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("could not read input or lexicon", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

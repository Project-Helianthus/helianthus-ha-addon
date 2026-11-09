"""Exercise the readability ratchet and its Ruff integration."""

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "readability", ROOT / "scripts/check_readability.py"
)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class ReadabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=ROOT / ".tmp" if (ROOT / ".tmp").exists() else None
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(ROOT / "ruff.toml", self.root / "ruff.toml")

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def test_ratchet_identity_and_count(self):
        key = ("tests/a.py", "old", "C901")
        baseline = {key: 12}
        self.assertFalse(GUARD.compare_findings({key: 11}, baseline))
        self.assertFalse(GUARD.compare_findings({}, baseline))
        self.assertTrue(GUARD.compare_findings({key: 13}, baseline))
        for changed in (
            ("tests/b.py", "old", "C901"),
            ("tests/a.py", "new", "C901"),
            ("tests/a.py", "old", "PLR0915"),
        ):
            self.assertTrue(GUARD.compare_findings({changed: 12}, baseline))

    def test_parser_rejects_invalid_rows_and_metadata(self):
        row = {"path": "tests/a.py", "symbol": "f", "rule": "C901", "count": 11}
        base = {
            "schema_version": 1,
            "ruff_version": GUARD.RUFF_VERSION,
            "generation": "measured",
            "findings": [row],
        }
        self.assertEqual(len(GUARD.read_baseline(json.dumps(base))), 1)
        for patch in (
            {"path": "tests/*.py"},
            {"symbol": ""},
            {"rule": "N123"},
            {"count": 0},
        ):
            invalid = dict(base, findings=[dict(row, **patch)])
            with self.assertRaises(ValueError):
                GUARD.read_baseline(json.dumps(invalid))
        for invalid in (dict(base, findings=[row, row]), dict(base, ruff_version="0")):
            with self.assertRaises(ValueError):
                GUARD.read_baseline(json.dumps(invalid))
        for text in ('{"schema_version": 1, "schema_version": 1}', "not json"):
            with self.assertRaises(ValueError):
                GUARD.read_baseline(text)

    def test_shipped_helper_and_new_function_are_checked(self):
        path = "helianthus/rootfs/usr/share/helianthus/helper.py"
        complex_function = (
            "def complex_function(value):\n"
            + "".join(
                f"    if value == {index}:\n        return {index}\n"
                for index in range(11)
            )
            + "    return None\n"
        )
        self.write(path, complex_function)
        findings = GUARD.run_ruff(self.root)
        self.assertIn((path, "complex_function", "C901"), findings)
        self.assertTrue(GUARD.compare_findings(findings, {}))
        grown = complex_function.replace(
            "    return None\n",
            "    if value == 99:\n        return 99\n    return None\n",
        )
        self.write(path, grown)
        self.assertTrue(GUARD.compare_findings(GUARD.run_ruff(self.root), findings))
        self.write(
            path,
            complex_function.replace("    if value == 10:\n        return 10\n", ""),
        )
        self.assertFalse(GUARD.compare_findings(GUARD.run_ruff(self.root), findings))
        self.write(
            path,
            complex_function
            + complex_function.replace("complex_function", "another_function"),
        )
        newer = GUARD.run_ruff(self.root)
        self.assertTrue(GUARD.compare_findings(newer, findings))
        self.write("new_file.py", complex_function)
        self.assertTrue(GUARD.compare_findings(GUARD.run_ruff(self.root), newer))

    def test_other_lint_and_invalid_python_fail(self):
        self.write("script.py", "import os\n")
        with self.assertRaisesRegex(ValueError, "non-readability lint failure"):
            GUARD.run_ruff(self.root)
        self.write("script.py", "def broken(:\n")
        with self.assertRaises(ValueError):
            GUARD.run_ruff(self.root)

    def test_version_mismatch_fails(self):
        class Result:
            returncode = 0
            stdout = "ruff 0.0.0"

        with self.assertRaisesRegex(ValueError, "version mismatch"):
            GUARD.run_ruff(self.root, runner=lambda *args, **kwargs: Result())


if __name__ == "__main__":
    unittest.main()

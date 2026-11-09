#!/usr/bin/env python3
"""Check cached Ruff findings against a reviewed, symbol-based debt ceiling."""

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUFF_VERSION = "0.15.10"
EXCLUDED_DIRS = {".git", ".tmp", ".venv-ci", ".ruff_cache", "__pycache__"}
READABILITY_RULES = {
    "N801",
    "N802",
    "N803",
    "N804",
    "N805",
    "N806",
    "N807",
    "N811",
    "N812",
    "N813",
    "N814",
    "N815",
    "N816",
    "N817",
    "N818",
    "N999",
    "C901",
    "PLR0915",
}


def unique_object(pairs):
    """Reject duplicate JSON object keys rather than silently taking the last."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def load_json(text):
    return json.loads(text, object_pairs_hook=unique_object)


def record_key(record):
    if not isinstance(record, dict) or set(record) != {
        "path",
        "symbol",
        "rule",
        "count",
    }:
        raise ValueError("invalid finding record")
    path, symbol, rule = (record[field] for field in ("path", "symbol", "rule"))
    if not all(isinstance(value, str) and value for value in (path, symbol, rule)):
        raise ValueError("empty finding identity")
    if (
        Path(path).is_absolute()
        or ".." in Path(path).parts
        or Path(path).as_posix() != path
        or "\\" in path
        or any(part in EXCLUDED_DIRS for part in Path(path).parts)
        or any(char in path for char in "*?[]")
        or not path.endswith(".py")
    ):
        raise ValueError("finding path must be a relative Python input")
    if rule not in READABILITY_RULES:
        raise ValueError("invalid rule")
    if type(record["count"]) is not int or record["count"] < 1:
        raise ValueError("invalid observed count")
    return path, symbol, rule


def read_baseline(text):
    baseline = load_json(text)
    if (
        not isinstance(baseline, dict)
        or set(baseline) != {"schema_version", "ruff_version", "generation", "findings"}
        or type(baseline["schema_version"]) is not int
        or baseline["schema_version"] != 1
        or baseline["ruff_version"] != RUFF_VERSION
        or not isinstance(baseline["generation"], str)
        or not baseline["generation"]
        or not isinstance(baseline["findings"], list)
    ):
        raise ValueError("invalid baseline metadata")
    result = {}
    for record in baseline["findings"]:
        key = record_key(record)
        if key in result:
            raise ValueError("duplicate baseline record")
        result[key] = record["count"]
    return result


def compare_findings(current, baseline):
    errors = []
    for key, count in sorted(current.items()):
        if key not in baseline:
            errors.append(f"new finding: {key} ({count})")
        elif count > baseline[key]:
            errors.append(f"grown finding: {key} ({baseline[key]} -> {count})")
    return errors


@lru_cache(maxsize=1)
def lexical_scopes(source):
    scopes = []

    def visit(node, parents):
        for child in ast.iter_child_nodes(node):
            scope = parents
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = parents + [child.name]
                scopes.append(
                    (child.lineno, child.end_lineno, len(scope), ".".join(scope))
                )
            visit(child, scope)

    visit(ast.parse(source), [])
    return scopes


def symbol_at(source, row, column):
    """Use lexical ownership and identifier, so line movement keeps identity."""
    owners = [
        (depth, name)
        for start, end, depth, name in lexical_scopes(source)
        if start <= row <= end
    ]
    owner = max(owners, default=(0, "<module>"))[1]
    line = source.splitlines()[row - 1]
    identifier = re.match(r"[A-Za-z_][A-Za-z_0-9]*", line[column - 1 :])
    return owner, identifier.group() if identifier else "<expression>"


def validate_rule(rule, path):
    if rule not in READABILITY_RULES:
        raise ValueError(f"non-readability lint failure: {path}: {rule}")


def collect_findings(text, root):
    diagnostics = load_json(text)
    if not isinstance(diagnostics, list):
        raise ValueError("Ruff output must be an array")
    result = Counter()
    sources = {}
    for item in diagnostics:
        if not isinstance(item, dict):
            raise ValueError("invalid Ruff diagnostic")
        path = Path(item["filename"]).resolve().relative_to(root.resolve()).as_posix()
        if path not in sources:
            sources[path] = (root / path).read_text(encoding="utf-8")
        location = item["location"]
        row, column = location["row"], location["column"]
        if type(row) is not int or type(column) is not int or min(row, column) < 1:
            raise ValueError("invalid Ruff location")
        rule = item["code"]
        if not isinstance(rule, str):
            raise ValueError("missing Ruff rule")
        validate_rule(rule, path)
        owner, identifier = symbol_at(sources[path], row, column)
        symbol = owner if rule in {"C901", "PLR0915"} else owner + ":" + identifier
        count = 1
        if rule in {"C901", "PLR0915"}:
            measured = re.search(r"\((\d+) > (\d+)\)", item["message"])
            if measured is None:
                raise ValueError("missing Ruff measured count")
            count = int(measured[1])
        record = dict(path=path, symbol=symbol, rule=rule, count=count)
        key = record_key(record)
        if rule in {"C901", "PLR0915"} and key in result:
            raise ValueError("ambiguous duplicate measured symbol")
        result[key] += count
    return dict(result)


def python_inputs(root):
    """Include all repository Python, excluding local and hidden directories."""
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if not any(part in EXCLUDED_DIRS for part in p.relative_to(root).parts)
    )


def run_ruff(root, runner=subprocess.run):
    version = runner(["ruff", "--version"], capture_output=True, text=True, timeout=30)
    if version.returncode or version.stdout.strip() != "ruff " + RUFF_VERSION:
        raise ValueError("cached Ruff version mismatch or tool failure")
    result = runner(
        [
            "ruff",
            "check",
            "--no-cache",
            "--no-respect-gitignore",
            "--output-format=json",
            "--config",
            str(root / "ruff.toml"),
            *python_inputs(root),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise ValueError("Ruff failed: " + result.stderr.strip())
    findings = collect_findings(result.stdout, root)
    if bool(findings) != bool(result.returncode):
        raise ValueError("Ruff status and findings disagree")
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        import unittest

        suite = unittest.defaultTestLoader.discover(
            str(ROOT / "tests"), pattern="test_readability_gate.py"
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.testsRun and result.wasSuccessful() else 1
    try:
        baseline = read_baseline(
            (ROOT / "scripts/readability-baseline.json").read_text()
        )
        current = run_ruff(ROOT)
        errors = compare_findings(current, baseline)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.TimeoutExpired,
        SyntaxError,
    ) as exc:
        print(f"readability check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Readability check passed: {len(current)} reviewed finding records")
    return 0


if __name__ == "__main__":
    sys.exit(main())

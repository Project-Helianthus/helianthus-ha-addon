"""Synthetic packaging metadata only; no release or hardware qualification."""

import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_release_cohort.py"


def run_guard(tmp_path, addon="0.7.0", explorer="v0.7.1", gateway=None,
              declared=None, dockerfile=None, test_explorer="v0.7.1", build_args=None):
    config = tmp_path / "config.json"
    docker = tmp_path / "Dockerfile"
    workflow = tmp_path / "test-image.yml"
    source = yaml.safe_load((ROOT / ".github/workflows/test-image.yml").read_text(encoding="utf-8"))
    for step in source["jobs"]["build"]["steps"]:
        if step.get("uses", "").startswith("docker/build-push-action@"):
            args = step["with"]["build-args"].splitlines()
            args = [line for line in args if not line.startswith("VRCEXPLORER_VERSION=")]
            if test_explorer is not None:
                args.append(f"VRCEXPLORER_VERSION={test_explorer}")
            step["with"]["build-args"] = "\n".join(args) if build_args is None else build_args
    workflow.write_text(yaml.safe_dump(source), encoding="utf-8")
    config.write_text(json.dumps({"version": addon}), encoding="utf-8")
    docker.write_text(dockerfile if dockerfile is not None else (
        f"ARG VRCEXPLORER_VERSION={explorer}\n"
        "FROM synthetic\n"
        f"ARG EBUSGATEWAY_VERSION={gateway or 'opaque-test-pin'}\n"
        f"ARG VRCEXPLORER_VERSION={explorer}\n"
    ), encoding="utf-8")
    before = (config.read_bytes(), docker.read_bytes(), workflow.read_bytes())
    command = [sys.executable, str(SCRIPT), "--addon-config", str(config),
               "--dockerfile", str(docker), "--test-image-workflow", str(workflow)]
    if declared is not None:
        command.extend(["--gateway-release-version", declared])
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert (config.read_bytes(), docker.read_bytes(), workflow.read_bytes()) == before
    return result


@pytest.mark.parametrize("declared", ["0.7.0", "v0.7.9", "v0.7.0-rc.1"])
def test_matching_declared_cohorts(tmp_path, declared):
    result = run_guard(tmp_path, declared=declared)
    assert result.returncode == 0, result.stdout
    assert "declared add-on, Explorer and gateway" in result.stdout
    assert "release readiness remain unverified" in result.stdout


@pytest.mark.parametrize("explorer", ["v0.6.9", "v0.8.0", "latest", "", "v0.70.0"])
def test_explorer_mismatch_or_unknown_fails(tmp_path, explorer):
    result = run_guard(tmp_path, explorer=explorer, declared="0.7.0")
    assert result.returncode == 1
    assert "FAIL:" in result.stdout


@pytest.mark.parametrize("test_explorer", [
    "v0.6.1", "v0.8.0", "latest", "", "${{ inputs.explorer }}",
    "v0.7.1\nVRCEXPLORER_VERSION=v0.6.1",
])
def test_test_image_explorer_override_conflict_or_unknown_fails(tmp_path, test_explorer):
    result = run_guard(tmp_path, declared="0.7.0", test_explorer=test_explorer)
    assert result.returncode == 1
    assert "FAIL:" in result.stdout


@pytest.mark.parametrize("test_explorer", ["v0.7.9", "v0.7.0-rc.1", None])
def test_test_image_matching_override_or_dockerfile_default_passes(tmp_path, test_explorer):
    result = run_guard(tmp_path, declared="0.7.0", test_explorer=test_explorer)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("build_args,code", [
    ('"VRCEXPLORER_VERSION=v0.6.1"', 1),
    ('"VRCEXPLORER_VERSION=v0.7.9"', 0),
    ('"VRCEXPLORER_VERSION=latest"', 1),
    ('"VRCEXPLORER_VERSION="', 1),
    ('VRCEXPLORER_VERSION=v0.7.1\n"VRCEXPLORER_VERSION=v0.6.1"', 1),
    ('\r\n"OTHER=first\r\nsecond"\r\n"VRCEXPLORER_VERSION=v0.6.1"\r\n', 1),
    ('"OTHER=first,second"\n"VRCEXPLORER_VERSION=v0.7.1"', 0),
    ('OTHER=first,VRCEXPLORER_VERSION=v0.6.1', 0),
    ('"VRCEXPLORER_VERSION=v0.7.1",suffix', 1),
    ('"OTHER=some ""quoted"" text"\n"VRCEXPLORER_VERSION=v0.6.1"', 1),
    ('"VRCEXPLORER_VERSION=v0.6.1', 1),
    ("${{ inputs.build_args }}", 1),
    ("OTHER=x\n${{ inputs.extra_build_args }}\nVRCEXPLORER_VERSION=v0.7.1", 1),
    ("VRCEXPLORER_VERSION=${{ inputs.explorer }}", 1),
    ("BUILD_FROM=${{ matrix.base }}\nVRCEXPLORER_VERSION=v0.7.1", 0),
])
def test_test_image_csv_build_arguments(tmp_path, build_args, code):
    result = run_guard(tmp_path, declared="0.7.0", build_args=build_args)
    assert result.returncode == code, result.stdout
    if code:
        assert "FAIL:" in result.stdout


def test_legacy_test_image_override_remains_unchanged(tmp_path):
    result = run_guard(tmp_path, addon="0.6.58", explorer="v0.6.1", test_explorer="v0.6.1")
    assert result.returncode == 0, result.stdout
    assert "NOT_APPLICABLE" in result.stdout


@pytest.mark.parametrize("declared", ["0.6.9", "v0.8.0", "latest", "", "opaque-test-pin"])
def test_explicit_gateway_conflict_or_invalid_release_fails(tmp_path, declared):
    result = run_guard(tmp_path, declared=declared)
    assert result.returncode == 1
    assert "FAIL:" in result.stdout


def test_opaque_gateway_pin_is_unverified(tmp_path):
    result = run_guard(tmp_path)
    assert result.returncode == 0
    assert "UNVERIFIED: gateway release metadata unavailable" in result.stdout
    assert "declared add-on, Explorer and gateway" not in result.stdout


@pytest.mark.parametrize("gateway,code", [("v0.7.2", 0), ("v0.6.9", 1)])
def test_gateway_release_pin_is_checked(tmp_path, gateway, code):
    result = run_guard(tmp_path, gateway=gateway)
    assert result.returncode == code


def test_declaration_cannot_hide_a_conflicting_release_pin(tmp_path):
    result = run_guard(tmp_path, gateway="v0.6.9", declared="0.7.0")
    assert result.returncode == 1
    assert "gateway release pin cohort differs" in result.stdout


@pytest.mark.parametrize("explorer", ["v0.5.1", "v0.6.1"])
def test_legacy_packaging_is_not_reclassified(tmp_path, explorer):
    result = run_guard(tmp_path, addon="0.6.58", explorer=explorer)
    assert result.returncode == 0
    assert "NOT_APPLICABLE" in result.stdout
    assert "CONSISTENT:" not in result.stdout


@pytest.mark.parametrize("declaration", [
    "", "ARG VRCEXPLORER_VERSION", "ARG VRCEXPLORER_VERSION=v0.6.1",
    "ARG VRCEXPLORER_VERSION=${RELEASE}",
    "ARG VRCEXPLORER_VERSION=v0.7.0#invalid",
    "ARG VRCEXPLORER_VERSION=v0.7.0 # note",
])
def test_missing_or_conflicting_explorer_defaults_fail(tmp_path, declaration):
    dockerfile = f"ARG EBUSGATEWAY_VERSION=opaque-test-pin\n{declaration}\n"
    if declaration:
        dockerfile += "ARG VRCEXPLORER_VERSION=v0.7.0\n"
    result = run_guard(tmp_path, dockerfile=dockerfile)
    assert result.returncode == 1


@pytest.mark.parametrize("name", ["VRCEXPLORER_VERSION", "EBUSGATEWAY_VERSION"])
@pytest.mark.parametrize("later_version,code", [("v0.7.0", 0), ("v0.6.9", 1)])
@pytest.mark.parametrize("continuation", ["\\\n", "\\\r\n", "\\\n# stage default\n\n"])
def test_continued_stage_defaults_are_checked(tmp_path, name, later_version, code, continuation):
    dockerfile = (
        "ARG VRCEXPLORER_VERSION=v0.7.0\n"
        "ARG EBUSGATEWAY_VERSION=v0.7.0\n"
        "FROM synthetic\n"
        f"ARG {continuation}    {name}={later_version}\n"
    )
    result = run_guard(tmp_path, dockerfile=dockerfile)
    assert result.returncode == code, result.stdout
    if code:
        assert f"{name} must have one consistent nonempty default" in result.stdout
    else:
        assert "CONSISTENT: declared add-on, Explorer and gateway" in result.stdout


@pytest.mark.parametrize("addon", [None, 7, "", "0.7", "0.7.0oops"])
def test_invalid_addon_version_fails(tmp_path, addon):
    assert run_guard(tmp_path, addon=addon).returncode == 1


def test_cli_reports_bad_json_and_missing_files(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{", encoding="utf-8")
    for path in [config, tmp_path / "missing.json"]:
        result = subprocess.run([sys.executable, str(SCRIPT), "--addon-config", str(path)],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 1
        assert "FAIL:" in result.stdout


def test_help_documents_usage_and_evidence_limits():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    for text in ["--gateway-release-version", "UNVERIFIED", "exact-BOM", "Pi success", "release readiness"]:
        assert text in result.stdout


def test_required_gate_registers_guard_and_tests_once():
    gate = (ROOT / "scripts/ci_local.sh").read_text(encoding="utf-8")
    assert gate.count("python3 scripts/check_release_cohort.py\n") == 1
    assert gate.count("tests/test_release_cohort.py") == 1
    assert "python3 -m pytest -q tests/test_release_cohort.py\n" in gate


def test_pr_workflow_enforces_release_cohort():
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["syntax-checks"]
    steps = [step for step in job["steps"] if step.get("name") == "Validate release cohort"]
    assert len(steps) == 1
    step = steps[0]
    for scope in (job, step):
        assert "if" not in scope
        assert not scope.get("continue-on-error", False)
    assert step["shell"] == "bash"
    commands = [line.strip() for line in step["run"].splitlines()]
    expected = [
        "set -euo pipefail",
        "python3 -m pip install --quiet --user -r requirements-ci.txt",
        "python3 scripts/check_release_cohort.py",
        "python3 -m pytest -q tests/test_release_cohort.py",
    ]
    assert commands == expected

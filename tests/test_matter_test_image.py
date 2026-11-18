"""Opt-in Matter test image; official builds stay on the profile without Matter.

Synthetic only: the Dockerfile and workflows are parsed, the plan runs in
process, and the start-up wrapper runs against the stubbed harness of the
Portal wiring tests with a recording gateway substitute.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "helianthus/Dockerfile"
BUILD_WORKFLOW = ROOT / ".github/workflows/build.yml"
TEST_WORKFLOW = ROOT / ".github/workflows/test-image.yml"
PLAN_SCRIPT = ROOT / "scripts/test_image_plan.py"
BOM = ROOT / "helianthus/bom.json"
CONFIG = ROOT / "helianthus/config.json"
SHA = "80cdb40082bc74d9b676d293c4554586f2588138"
RUN_ID = "123456789"
LIBRARY_FLAG = "matter-library-enabled"
STORE_FLAG = "matter-endpoint-store"
STORE_PATH = "/data/matter-endpoint-store"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan_module = _load("test_image_plan_for_matter", PLAN_SCRIPT)


def _builder_stage() -> str:
    match = re.search(r"^FROM [^\n]* AS builder\n(.*?)(?=^FROM )", DOCKERFILE.read_text(encoding="utf-8"), re.M | re.S)
    assert match, "the Dockerfile has no gateway builder stage"
    return match.group(1)


def _gateway_tags_defaults(stage: str) -> list[str]:
    return re.findall(r"^ARG GATEWAY_TAGS=(\S*)$", stage, re.M)


# Dockerfile


def test_builder_arg_defaults_to_the_profile_without_matter() -> None:
    assert _gateway_tags_defaults(_builder_stage()) == ["nomatter"]
    # Only the builder declares it; no other stage can change the gateway profile.
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert len(re.findall(r"^ARG GATEWAY_TAGS\b", text, re.M)) == 1


# Official build


def test_official_build_workflow_leaves_the_profile_arg_unset() -> None:
    build = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "GATEWAY_TAGS" not in build
    assert "include_matter" not in build and "test-matter-" not in build


def test_bom_and_catalog_name_no_matter() -> None:
    assert "matter" not in BOM.read_text(encoding="utf-8")
    assert "matter_" not in CONFIG.read_text(encoding="utf-8")
    assert "matter-endpoint" not in CONFIG.read_text(encoding="utf-8")


# Plan


def test_plan_is_unchanged_without_the_matter_input() -> None:
    default = plan_module.plan(SHA, "second-site", RUN_ID)
    explicit = plan_module.plan(SHA, "second-site", RUN_ID, include_matter=False)
    assert default == explicit
    assert default["tag"] == "test-second-site-80cdb400"
    assert all("matter" not in tag for tag in [default["tag"], *default["arch_tags"]])


@pytest.mark.parametrize("label", ["second-site", "lab-2"])
def test_plan_emits_a_matter_test_tag_only_when_asked(label: str) -> None:
    result = plan_module.plan(SHA, label, RUN_ID, include_matter=True)
    assert result["tag"] == f"test-matter-{label}-80cdb400"
    assert result["arch_tags"] == [
        f"test-matter-{label}-80cdb400-amd64-r{RUN_ID}",
        f"test-matter-{label}-80cdb400-aarch64-r{RUN_ID}",
    ]
    assert result["manifest_tags"] == [result["tag"]]
    assert result["manifest_sources"] == result["arch_tags"]
    assert result["build_version"] == result["tag"]
    for tag in [result["tag"], *result["arch_tags"]]:
        assert tag.startswith("test-matter-")
        assert tag != "latest" and not re.match(r"^v?\d+\.\d+\.\d+", tag)


def test_plan_varies_every_input_of_the_matter_tag() -> None:
    base = plan_module.plan(SHA, "second-site", RUN_ID, include_matter=True)
    other_sha = "1" * 40
    assert plan_module.plan(other_sha, "second-site", RUN_ID, include_matter=True)["tag"] == "test-matter-second-site-11111111"
    assert plan_module.plan(SHA, "lab", RUN_ID, include_matter=True)["tag"] == "test-matter-lab-80cdb400"
    assert plan_module.plan(SHA, "second-site", "7", include_matter=True)["arch_tags"][0].endswith("-r7")
    assert plan_module.plan(SHA, "second-site", RUN_ID, include_matter=False)["tag"] != base["tag"]


@pytest.mark.parametrize(
    "tags",
    [
        ["test-second-site-80cdb400"],
        ["test-matter-second-site-80cdb400", "test-second-site-80cdb400-amd64-r1"],
        ["latest"],
        ["0.7.0"],
        ["test-matter"],
    ],
)
def test_a_matter_image_tag_without_the_matter_prefix_is_refused(tags: list[str]) -> None:
    with pytest.raises(ValueError):
        plan_module.check_tags(tags, include_matter=True)


def test_the_tag_guard_accepts_only_its_own_profile() -> None:
    plan_module.check_tags(["test-matter-lab-80cdb400"], include_matter=True)
    plan_module.check_tags(["test-lab-80cdb400"], include_matter=False)
    with pytest.raises(ValueError):
        plan_module.check_tags(["test-matter-lab-80cdb400"], include_matter=False)


def test_an_image_without_matter_cannot_carry_the_matter_prefix() -> None:
    with pytest.raises(ValueError):
        plan_module.plan(SHA, "matter-lab", RUN_ID, include_matter=False)


@pytest.mark.parametrize("value", ["true", "false"])
def test_cli_accepts_the_workflow_boolean(value: str) -> None:
    out = subprocess.run(
        [sys.executable, str(PLAN_SCRIPT), "plan", "--gateway-sha", SHA, "--run-id", RUN_ID, "--include-matter", value],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    prefix = "test-matter-" if value == "true" else "test-"
    assert f"tag={prefix}second-site-80cdb400" in out


@pytest.mark.parametrize("value", ["", "yes", "True", "1"])
def test_cli_refuses_other_matter_values(value: str) -> None:
    result = subprocess.run(
        [sys.executable, str(PLAN_SCRIPT), "plan", "--gateway-sha", SHA, "--run-id", RUN_ID, "--include-matter", value],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


# Test-image workflow


def _test_workflow() -> dict:
    return yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_declares_the_matter_input_off_by_default() -> None:
    inputs = _test_workflow()[True]["workflow_dispatch"]["inputs"]
    assert inputs["include_matter"]["type"] == "boolean"
    assert inputs["include_matter"]["default"] is False
    assert inputs["include_matter"].get("required", False) is False


def test_workflow_hands_the_input_to_the_plan() -> None:
    plan_step = next(step for step in _test_workflow()["jobs"]["plan"]["steps"] if step.get("id") == "plan")
    assert plan_step["env"]["INCLUDE_MATTER"] == "${{ inputs.include_matter }}"
    assert '--include-matter "${INCLUDE_MATTER}"' in plan_step["run"]


def _push_steps() -> list[dict]:
    steps = _test_workflow()["jobs"]["build"]["steps"]
    return [step for step in steps if str(step.get("uses", "")).startswith("docker/build-push-action")]


def _build_args(step: dict) -> list[str]:
    return [line.strip() for line in step["with"]["build-args"].splitlines() if line.strip()]


def test_workflow_passes_the_default_profile_only_for_a_matter_image() -> None:
    official, matter = _push_steps()
    # Exactly one of the two runs for a dispatch.
    assert official["if"] == "${{ !inputs.include_matter }}"
    assert matter["if"] == "${{ inputs.include_matter }}"
    assert not [line for line in _build_args(official) if "GATEWAY_TAGS" in line]
    assert [line for line in _build_args(matter) if "GATEWAY_TAGS" in line] == ["GATEWAY_TAGS=default"]
    assert "nomatter" not in TEST_WORKFLOW.read_text(encoding="utf-8")
    # Every build argument is a literal name, as the release-cohort guard requires.
    for step in (official, matter):
        assert all("${{" not in line.split("=", 1)[0] for line in _build_args(step))


def test_both_build_steps_differ_only_in_the_profile() -> None:
    official, matter = _push_steps()
    assert _build_args(official) == [
        "BUILD_VERSION=${{ needs.plan.outputs.build_version }}",
        "EBUSGATEWAY_VERSION=${{ inputs.gateway_sha }}",
        "VRCEXPLORER_VERSION=v0.6.1",
        "BUILD_FROM=${{ matrix.base }}",
    ]
    assert _build_args(matter) == [*_build_args(official), "GATEWAY_TAGS=default"]
    for key in ("context", "push", "platforms", "tags", "labels", "secrets"):
        assert official["with"][key] == matter["with"][key], key
    assert official["with"]["context"] == "./helianthus"


def test_workflow_never_reads_the_catalog_or_bom() -> None:
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
    body = workflow.split("\non:", 1)[1]
    assert "config.json" not in body and "bom.json" not in body
    assert ":latest" not in workflow


# Start-up wrapper


portal_wiring = _load("portal_wiring_for_matter", ROOT / "tests/test_portal_ingress_wiring.py")

FAKE_GATEWAY_WITH_EXTRA = portal_wiring.FAKE_GATEWAY.replace(
    'hidden = set(json.loads(os.environ["TEST_HELP_HIDDEN"]))',
    'hidden = set(json.loads(os.environ["TEST_HELP_HIDDEN"]))\n'
    '    flags = list(flags) + json.loads(os.environ.get("MATTER_PROBE_HELP_EXTRA", "[]"))',
)


def _wrapper_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]) -> tuple[list[str], Path]:
    assert FAKE_GATEWAY_WITH_EXTRA != portal_wiring.FAKE_GATEWAY
    monkeypatch.setattr(portal_wiring, "FAKE_GATEWAY", FAKE_GATEWAY_WITH_EXTRA)
    monkeypatch.setenv("MATTER_PROBE_HELP_EXTRA", portal_wiring.json.dumps(extra))
    run = portal_wiring._run(tmp_path, {"adapter_direct_address": portal_wiring.ADAPTER})
    assert run["result"].returncode == 0, run["result"].stderr
    assert len(run["runtime"]) == 1
    return run["runtime"][0], run["data"]


def test_official_binary_gains_no_matter_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv, data = _wrapper_argv(tmp_path, monkeypatch, [])
    transport = ("adapter-direct", "tcp", f"adapter-direct://{portal_wiring.ADAPTER}")
    assert argv == portal_wiring._expected_argv(data, transport)
    assert not [arg for arg in argv if arg.startswith("-matter")]


def test_a_matter_binary_receives_both_flags_and_the_data_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argv, data = _wrapper_argv(tmp_path, monkeypatch, [LIBRARY_FLAG, STORE_FLAG])
    transport = ("adapter-direct", "tcp", f"adapter-direct://{portal_wiring.ADAPTER}")
    base = portal_wiring._expected_argv(data, transport)
    matter = [arg for arg in argv if arg not in base]
    store = str(data / "matter-endpoint-store")
    assert matter == [f"-{LIBRARY_FLAG}=true", f"-{STORE_FLAG}", store]
    assert argv.count(f"-{STORE_FLAG}") == 1 and argv[argv.index(f"-{STORE_FLAG}") + 1] == store
    assert [arg for arg in argv if arg not in matter] == base


@pytest.mark.parametrize("present", [[LIBRARY_FLAG], [STORE_FLAG]], ids=["library-only", "store-only"])
def test_a_binary_with_one_matter_flag_receives_neither(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, present: list[str]
) -> None:
    argv, data = _wrapper_argv(tmp_path, monkeypatch, present)
    transport = ("adapter-direct", "tcp", f"adapter-direct://{portal_wiring.ADAPTER}")
    assert argv == portal_wiring._expected_argv(data, transport)
    assert not [arg for arg in argv if arg.startswith("-matter")]


def test_wrapper_store_path_is_under_the_add_on_data_directory() -> None:
    run = (ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run").read_text(encoding="utf-8")
    assert f'"{STORE_PATH}"' in run
    # No add-on option drives Matter: the probe of the packaged binary decides.
    assert not re.search(r"bashio::config\s+['\"]?[a-z_]*matter", run)
    assert "include_matter" not in run

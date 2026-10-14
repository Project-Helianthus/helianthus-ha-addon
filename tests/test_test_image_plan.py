import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/test_image_plan.py"
SHA = "80cdb40082bc74d9b676d293c4554586f2588138"
RUN = "123456789"

spec = importlib.util.spec_from_file_location("test_image_plan", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_tags_are_test_only() -> None:
    result = module.plan(SHA, "second-site", RUN)
    assert result["tag"] == "test-second-site-80cdb400"
    assert result["arch_tags"] == [
        "test-second-site-80cdb400-amd64-r123456789",
        "test-second-site-80cdb400-aarch64-r123456789",
    ]
    assert result["manifest_tags"] == ["test-second-site-80cdb400"]
    assert result["manifest_sources"] == result["arch_tags"]
    for tag in [*result["arch_tags"], *result["manifest_tags"]]:
        assert tag.startswith("test-")
        assert tag != "latest"
        assert not re.match(r"^v?\d+\.\d+\.\d+", tag)


def test_architectures_match_declared_config() -> None:
    config = json.loads((ROOT / "helianthus/config.json").read_text(encoding="utf-8"))
    assert sorted(module.ARCHES) == sorted(config["arch"])


@pytest.mark.parametrize("sha", ["", "80cdb400", SHA.upper(), SHA[:-1] + "g", SHA + "0", "main", SHA + "\n", " " + SHA, SHA + " ", SHA + "\r"])
def test_rejects_bad_sha(sha: str) -> None:
    with pytest.raises(ValueError):
        module.plan(sha, "second-site", RUN)


@pytest.mark.parametrize("label", ["", "Second", "a b", "-x", "a/b", "x" * 32, "latest:1", "second-site\n", "second-site ", " second-site"])
def test_rejects_bad_label(label: str) -> None:
    with pytest.raises(ValueError):
        module.plan(SHA, label, RUN)


def test_cli_outputs_github_output_lines() -> None:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", "--gateway-sha", SHA, "--run-id", RUN],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    assert "tag=test-second-site-80cdb400" in out
    assert "manifest_sources=test-second-site-80cdb400-amd64-r123456789 test-second-site-80cdb400-aarch64-r123456789" in out


def test_cli_fails_on_bad_input() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", "--gateway-sha", "abc", "--run-id", RUN], capture_output=True, text=True
    )
    assert result.returncode == 1


def test_workflow_publishes_only_planned_tags_and_is_dispatch_only() -> None:
    workflow = (ROOT / ".github/workflows/test-image.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    import yaml

    triggers = yaml.safe_load(workflow)[True]  # YAML parses the key `on` as True
    assert list(triggers) == ["workflow_dispatch"]
    assert triggers["workflow_dispatch"]["inputs"]["gateway_sha"]["required"] is True
    assert triggers["workflow_dispatch"]["inputs"]["test_label"]["default"] == "second-site"
    assert ":latest" not in workflow and "latest-" not in workflow
    assert "scripts/test_image_plan.py plan" in workflow
    assert "EBUSGATEWAY_VERSION=${{ inputs.gateway_sha }}" in workflow
    assert "jq" not in workflow


def test_stable_build_workflow_untouched_by_test_inputs() -> None:
    build = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    assert "gateway_sha" not in build
    assert "test_image_plan" not in build and "io.helianthus.test-image" not in build


def _workflow() -> dict:
    import yaml

    return yaml.safe_load((ROOT / ".github/workflows/test-image.yml").read_text(encoding="utf-8"))


def test_workflow_matrix_is_exactly_the_declared_architectures() -> None:
    matrix = _workflow()["jobs"]["build"]["strategy"]["matrix"]["include"]
    assert [entry["arch"] for entry in matrix] == list(module.ARCHES)
    assert {entry["platform"] for entry in matrix} == {"linux/amd64", "linux/arm64"}


def test_workflow_build_tags_are_exactly_the_planned_arch_tags() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    pushes = [step for step in steps if str(step.get("uses", "")).startswith("docker/build-push-action")]
    assert len(pushes) == 1
    tags = [line.strip() for line in pushes[0]["with"]["tags"].splitlines() if line.strip()]
    assert tags == [
        "${{ env.IMAGE_NAME }}:${{ needs.plan.outputs.tag }}-${{ matrix.arch }}-r${{ github.run_id }}"
    ]
    assert pushes[0]["with"]["push"] is True


def test_workflow_manifest_destination_and_sources_come_only_from_the_plan() -> None:
    jobs = _workflow()["jobs"]
    steps = jobs["manifest"]["steps"]
    runs = [step["run"] for step in steps if "run" in step]
    assert len(runs) == 1
    run = runs[0]
    assert run.count("imagetools create") == 1
    assert '-t "${IMAGE_NAME}:${TAG}" "${refs[@]}"' in run
    env = next(step for step in steps if "run" in step)["env"]
    assert env["TAG"] == "${{ needs.plan.outputs.tag }}"
    assert env["SOURCES"] == "${{ needs.plan.outputs.manifest_sources }}"
    assert 'refs+=("${IMAGE_NAME}:${source}")' in run
    for forbidden in ("0.6.", "version", "latest"):
        assert forbidden not in run


def test_workflow_serializes_identical_dispatches_and_labels_the_run() -> None:
    workflow = _workflow()
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] is False
    group = concurrency["group"]
    assert "${{ inputs.test_label }}" in group and "${{ inputs.gateway_sha }}" in group
    steps = workflow["jobs"]["build"]["steps"]
    push = next(step for step in steps if str(step.get("uses", "")).startswith("docker/build-push-action"))
    assert "io.helianthus.workflow-run=${{ github.run_id }}" in push["with"]["labels"]
    manifest = next(step for step in workflow["jobs"]["manifest"]["steps"] if "run" in step)
    assert manifest["env"]["RUN_ID"] == "${{ github.run_id }}"
    assert 'index:io.helianthus.workflow-run=${RUN_ID}' in manifest["run"]


@pytest.mark.parametrize("bad_run", ["", "12a", "-1", "1 ", "1\n", "1" * 21])
def test_rejects_bad_run_id(bad_run: str) -> None:
    with pytest.raises(ValueError):
        module.plan(SHA, "second-site", bad_run)


@pytest.mark.parametrize(
    "case",
    [
        # (description, run that published amd64, run that published aarch64, run assembling the manifest)
        ("partial rerun of the same run keeps one run id", "10", "10", "10"),
        ("run B publishes while run A is partly failed", "10", "11", "10"),
        ("run B publishes while run A is partly failed (B manifest)", "10", "11", "11"),
    ],
)
def test_manifest_never_mixes_runs(case) -> None:
    _, amd64_run, aarch64_run, manifest_run = case
    published = {
        "amd64": module.plan(SHA, "second-site", amd64_run)["arch_tags"][0],
        "aarch64": module.plan(SHA, "second-site", aarch64_run)["arch_tags"][1],
    }
    sources = module.plan(SHA, "second-site", manifest_run)["manifest_sources"]
    # The manifest assembles tags that carry its own run id; an image from another
    # run lives under a different tag, so a missing image fails the manifest
    # (imagetools create cannot find the source) instead of being replaced silently.
    assert all(source.endswith(f"-r{manifest_run}") for source in sources)
    available = set(published.values())
    mixed = [source for source in sources if source not in available]
    if amd64_run == aarch64_run == manifest_run:
        assert not mixed
    else:
        assert mixed  # incomplete run: the manifest step fails, it never mixes runs

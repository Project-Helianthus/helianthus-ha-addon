"""Synthetic candidate metadata only; no release, tag, build or hardware qualification."""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_candidate_metadata as ccm  # noqa: E402
import check_release_cohort as k25  # noqa: E402


SCRIPT = ROOT / "scripts/check_candidate_metadata.py"
CONTRACT = ROOT / "docs/candidate-metadata-contract.md"
ADDON = "https://github.com/Project-Helianthus/helianthus-ha-addon"
GATEWAY = "https://github.com/Project-Helianthus/helianthus-ebusgateway"
EXPLORER = "https://github.com/Project-Helianthus/helianthus-vrc-explorer"
INTEGRATION = "https://github.com/synthetic-org/synthetic-ha-integration"
NATIVE = "https://github.com/synthetic-org/synthetic-native-family-library"
ARCHES = ["aarch64", "amd64", "armv7", "armhf", "i386"]
ASSOCIATION = "association-synthetic-ready"
EVIDENCE = "docs/synthetic-evidence.md"
# Computed, never embedded: a commit-like and a digest-like fragment.
COMMIT_LIKE = hashlib.sha1(b"synthetic commit").hexdigest()
DIGEST_LIKE = hashlib.sha256(b"synthetic digest").hexdigest()
IPV4_LIKE = ".".join(["192", "0", "2", "10"])
DATE_LIKE = "".join(["2026", "10", "23"])
TIMESTAMP_LIKE = DATE_LIKE + "".join(["04", "12", "47"])
LETTERS_LIKE = "abcdef" * 2
HEXLIKE = re.compile(r"[0-9A-Fa-f]{7,}")


# ---------------------------------------------------------------- fixtures

def ref(path: str, repository: str = ADDON) -> dict:
    return {"repository": repository, "path": path}


def component(name: str, label: str | None, artifact: str, public_ref: dict | None) -> dict:
    return {"name": name, "release_label": label, "artifact_id": artifact, "public_ref": public_ref}


def ready_metadata() -> dict:
    """A synthetic candidate whose every public prerequisite is satisfied."""
    return {
        "format": "helianthus-candidate-metadata/1",
        "bundle_id": "bundle-synthetic-ready",
        "association_id": ASSOCIATION,
        "kind": "candidate",
        "cohort": "0.7",
        "components": {
            "addon": component("helianthus-ha-addon", "0.7.0", "artifact-addon-ready", ref("RELEASE_COHORT.md")),
            "gateway": component("helianthus-ebusgateway", "v0.7.0", "artifact-gateway-ready",
                                 ref("README.md", GATEWAY)),
            "explorer": component("helianthus-vrc-explorer", "v0.7.1", "artifact-explorer-ready",
                                  ref("README.md", EXPLORER)),
            "ha_integration": component("synthetic-ha-integration", "v0.9.4", "artifact-integration-ready",
                                        ref("README.md", INTEGRATION)),
            "native_dependencies": [
                component("synthetic-native-family-library", "v1.2.3", "artifact-native-ready",
                          ref("README.md", NATIVE)),
            ],
        },
        "architectures": list(ARCHES),
        "output_binding": {
            "status": "bound",
            "association_id": ASSOCIATION,
            "artifact_ids": [f"output-{arch}-ready" for arch in ARCHES],
            "evidence_ref": ref(EVIDENCE),
        },
        "exact_bom": {"status": "verified", "association_id": ASSOCIATION,
                      "attestation_id": "attestation-synthetic-ready"},
        "acceptance": {key: {"status": "accepted", "association_id": ASSOCIATION, "evidence_ref": ref(EVIDENCE)}
                       for key in ccm.ACCEPTANCE_KEYS},
        "disposition": "ready-for-review",
    }


def receipt_for(meta: dict, review: str = "missing", gates: str = "missing", **checks: str) -> dict:
    """A synthetic private receipt matching meta, all readiness checks satisfied."""
    values = {name: "satisfied" for name in ccm.READINESS_CHECKS}
    values.update(checks)
    return {
        "format": "helianthus-candidate-verification/1",
        "bundle_id": meta["bundle_id"],
        "association_id": meta["association_id"],
        "attestation_id": meta["exact_bom"]["attestation_id"] if values["exact_bom"] == "satisfied" else None,
        "components": copy.deepcopy(meta["components"]),
        "expected_architectures": list(ARCHES),
        "bound_architectures": list(ARCHES),
        "expected_output_ids": list(meta["output_binding"]["artifact_ids"]),
        "bound_output_ids": list(meta["output_binding"]["artifact_ids"]),
        "checks": {**values, "acceptance": {key: "satisfied" for key in ccm.ACCEPTANCE_KEYS},
                   "independent_review": review, "required_gates": gates},
    }


def set_build_args(workflow: dict, **values: str | None) -> None:
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if not str(step.get("uses", "")).startswith("docker/build-push-action@"):
                continue
            lines = step["with"]["build-args"].splitlines()
            for name, value in values.items():
                lines = [line for line in lines if not line.startswith(name + "=")]
                if value is not None:
                    lines.append(f"{name}={value}")
            step["with"]["build-args"] = "\n".join(lines) + "\n"


def make_package(tmp_path: Path, version: str = "0.7.0", explorer: str = "v0.7.1",
                 gateway_pin: str = "opaque-test-pin", build_args: dict | None = None,
                 test_explorer: str = "v0.7.1", freeze: dict | None = None, build_edit=None,
                 name: str = "pkg") -> Path:
    """Derive a synthetic 0.7 package from this checkout's real packaging files."""
    package = tmp_path / name
    (package / "helianthus").mkdir(parents=True)
    (package / ".github/workflows").mkdir(parents=True)
    (package / "docs").mkdir()
    config = json.loads((ROOT / "helianthus/config.json").read_text(encoding="utf-8"))
    config["version"] = version
    (package / "helianthus/config.json").write_text(json.dumps(config), encoding="utf-8")
    dockerfile = (ROOT / "helianthus/Dockerfile").read_text(encoding="utf-8")
    dockerfile = re.sub(r"^ARG VRCEXPLORER_VERSION=\S+$", f"ARG VRCEXPLORER_VERSION={explorer}", dockerfile, flags=re.M)
    dockerfile = re.sub(r"^ARG EBUSGATEWAY_VERSION=\S+$", f"ARG EBUSGATEWAY_VERSION={gateway_pin}", dockerfile, flags=re.M)
    (package / "helianthus/Dockerfile").write_text(dockerfile, encoding="utf-8")
    build = yaml.safe_load((ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8"))
    set_build_args(build, **{"EBUSGATEWAY_VERSION": gateway_pin, "VRCEXPLORER_VERSION": explorer, **(build_args or {})})
    if build_edit is not None:
        build_edit(build)
    (package / ".github/workflows/build.yml").write_text(yaml.safe_dump(build), encoding="utf-8")
    test_image = yaml.safe_load((ROOT / ".github/workflows/test-image.yml").read_text(encoding="utf-8"))
    set_build_args(test_image, VRCEXPLORER_VERSION=test_explorer)
    (package / ".github/workflows/test-image.yml").write_text(yaml.safe_dump(test_image), encoding="utf-8")
    bom = {"format": "helianthus-addon-bom/1",
           "freeze": freeze if freeze is not None else {"owner": "INT-16", "status": "frozen"}}
    (package / "helianthus/bom.json").write_text(json.dumps(bom), encoding="utf-8")
    (package / "RELEASE_COHORT.md").write_text("synthetic\n", encoding="utf-8")
    (package / EVIDENCE).write_text("synthetic\n", encoding="utf-8")
    return package


def snapshot(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def run(tmp_path: Path, meta: dict | None, receipt: dict | None = None, package: Path | None = None,
        meta_text: str | bytes | None = None, receipt_text: str | None = None,
        context: Path | None = None) -> ccm.Outcome:
    if package is None:
        package = tmp_path / "pkg" if (tmp_path / "pkg").is_dir() else make_package(tmp_path)
    metadata = tmp_path / "metadata.json"
    raw = meta_text if meta_text is not None else json.dumps(meta)
    metadata.write_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    if receipt is not None or receipt_text is not None:
        context = context or tmp_path / "private" / "receipt.json"
        context.parent.mkdir(exist_ok=True)
        context.write_text(receipt_text if receipt_text is not None else json.dumps(receipt), encoding="utf-8")
    before = snapshot(tmp_path)
    outcome = ccm.validate(metadata, package, context)
    assert snapshot(tmp_path) == before, "the validator must not write anything"
    text = "\n".join(outcome.lines)
    assert str(tmp_path) not in text
    assert not any(ccm._hex_like(run) for run in HEXLIKE.findall(text)), text
    assert outcome.lines[-1] == ccm.NOTE
    return outcome


def first(outcome: ccm.Outcome) -> str:
    return outcome.lines[0]


def text(outcome: ccm.Outcome) -> str:
    return "\n".join(outcome.lines)


def setpath(doc: dict, path: tuple, value) -> dict:
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return doc


def delpath(doc: dict, path: tuple) -> dict:
    target = doc
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return doc


def dumps_with_duplicate(value, target: tuple, here: tuple = ()) -> str:
    if isinstance(value, dict):
        items = [f"{json.dumps(key)}: {dumps_with_duplicate(item, target, here + (key,))}" for key, item in value.items()]
        if here == target:
            items.insert(0, items[0])
        return "{" + ", ".join(items) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(dumps_with_duplicate(item, target, here + (index,))
                               for index, item in enumerate(value)) + "]"
    return json.dumps(value)


def contract_example() -> dict:
    match = re.search(r"```json\n(.*?)\n```", CONTRACT.read_text(encoding="utf-8"), re.S)
    assert match, "the M44 contract must keep its synthetic example"
    return json.loads(match[1])


# ------------------------------------------------- contract and ready case

def test_contract_example_is_valid_not_ready_in_public_only_mode(tmp_path):
    package = make_package(tmp_path, version="0.7.0-rc.1", explorer="v0.7.0-rc.1", test_explorer="v0.7.0-rc.1",
                           freeze={"owner": "INT-16", "status": "unfrozen"})
    outcome = run(tmp_path, contract_example(), package=package)
    assert outcome.exit_code == 0
    assert first(outcome) == "VALID: not-ready"
    assert outcome.disposition == "not-ready"
    for reason in [
        "NOT_READY: kind is preparatory",
        "NOT_READY: components.ha_integration.release_label is unavailable",
        "NOT_READY: output_binding is unbound",
        "NOT_READY: exact_bom is unverified",
        "NOT_READY: acceptance.Portal is pending",
        "NOT_READY: architectures differ from the set the build workflow publishes",
        "NOT_READY: helianthus/bom.json is not frozen by INT-16",
        "NOT_READY: private verification context not supplied",
    ]:
        assert reason in text(outcome)
    assert "IDENTITY: bundle_id bundle-synthetic-alpha, association_id association-synthetic-alpha" in text(outcome)
    assert "ARTIFACT: components.native_dependencies[0] artifact-native-alpha" in text(outcome)


def test_synthetic_ready_case_is_structural_verification_only(tmp_path):
    meta = ready_metadata()
    outcome = run(tmp_path, meta, receipt_for(meta))
    assert outcome.exit_code == 0, text(outcome)
    assert first(outcome) == "VALID: ready-for-review"
    assert outcome.disposition == "ready-for-review"
    assert "NOT_READY" not in text(outcome)
    assert "PENDING: verification check independent_review is missing" in text(outcome)
    assert "PENDING: verification check required_gates is missing" in text(outcome)
    for where, artifact in [("components.addon", "artifact-addon-ready"),
                            ("components.gateway", "artifact-gateway-ready"),
                            ("components.explorer", "artifact-explorer-ready"),
                            ("components.ha_integration", "artifact-integration-ready"),
                            ("components.native_dependencies[0]", "artifact-native-ready")]:
        assert f"ARTIFACT: {where} {artifact}" in outcome.lines
    assert "OUTPUT: output-armhf-ready" in outcome.lines
    assert "ATTESTATION: attestation-synthetic-ready" in outcome.lines
    assert "K25: CONSISTENT: declared add-on, Explorer and gateway release cohorts are 0.7" in outcome.lines
    assert "Structural verification only" in outcome.lines[-1]
    assert "neither a release, a tag nor hardware qualification" in outcome.lines[-1]


@pytest.mark.parametrize("review,gates,claim,code,prefix", [
    ("satisfied", "satisfied", "accepted-candidate", 0, "VALID: accepted-candidate"),
    ("satisfied", "satisfied", "ready-for-review", 1, "DISPOSITION_MISMATCH: claimed ready-for-review, derived accepted-candidate"),
    ("missing", "satisfied", "accepted-candidate", 2, "PRIVATE_EVIDENCE_REQUIRED: claimed accepted-candidate"),
    ("satisfied", "missing", "accepted-candidate", 2, "PRIVATE_EVIDENCE_REQUIRED: claimed accepted-candidate"),
    ("mismatch", "satisfied", "ready-for-review", 1, "EVIDENCE_MISMATCH: verification check independent_review"),
    ("satisfied", "mismatch", "not-ready", 1, "EVIDENCE_MISMATCH: verification check required_gates"),
])
def test_accepted_candidate_needs_independent_review_and_gates(tmp_path, review, gates, claim, code, prefix):
    meta = setpath(ready_metadata(), ("disposition",), claim)
    outcome = run(tmp_path, meta, receipt_for(meta, review=review, gates=gates))
    assert outcome.exit_code == code, text(outcome)
    assert first(outcome).startswith(prefix)


@pytest.mark.parametrize("claim,code,prefix", [
    ("ready-for-review", 2, "PRIVATE_EVIDENCE_REQUIRED: claimed ready-for-review"),
    ("accepted-candidate", 2, "PRIVATE_EVIDENCE_REQUIRED: claimed accepted-candidate"),
    ("not-ready", 0, "VALID: not-ready"),
])
def test_public_only_mode_never_promotes(tmp_path, claim, code, prefix):
    meta = setpath(ready_metadata(), ("disposition",), claim)
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == code
    assert first(outcome).startswith(prefix)
    assert outcome.disposition == "not-ready"
    assert "NOT_READY: private verification context not supplied" in text(outcome)


def test_full_receipt_with_not_ready_claim_is_a_disposition_mismatch(tmp_path):
    meta = setpath(ready_metadata(), ("disposition",), "not-ready")
    outcome = run(tmp_path, meta, receipt_for(meta))
    assert outcome.exit_code == 1
    assert first(outcome) == "DISPOSITION_MISMATCH: claimed not-ready, derived ready-for-review"


# --------------------------------------------- missing components fail closed

@pytest.mark.parametrize("key", ccm.COMPONENTS_FIELDS)
def test_missing_component_fails_closed(tmp_path, key):
    meta = delpath(ready_metadata(), ("components", key))
    outcome = run(tmp_path, meta, receipt_for(ready_metadata()))
    assert outcome.exit_code == 1
    assert first(outcome) == f"INVALID_DOCUMENT: metadata: components is missing {key}"
    assert outcome.disposition is None


@pytest.mark.parametrize("field", ccm.COMPONENT_FIELDS)
@pytest.mark.parametrize("where", [("components", "addon"), ("components", "native_dependencies", 0)])
def test_missing_component_field_fails_closed(tmp_path, where, field):
    meta = delpath(ready_metadata(), where + (field,))
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata: components.")
    assert f"is missing {field}" in first(outcome)


@pytest.mark.parametrize("value", [[], None, {}, "synthetic"])
def test_native_dependencies_must_be_a_nonempty_component_array(tmp_path, value):
    outcome = run(tmp_path, setpath(ready_metadata(), ("components", "native_dependencies"), value))
    assert outcome.exit_code == 1
    assert "components.native_dependencies must be a nonempty array" in first(outcome)


@pytest.mark.parametrize("path", [(field,) for field in ccm.METADATA_FIELDS]
                         + [("acceptance", key) for key in ccm.ACCEPTANCE_KEYS]
                         + [("output_binding", "evidence_ref"), ("exact_bom", "attestation_id"),
                            ("acceptance", "naming", "evidence_ref"), ("components", "gateway", "public_ref")])
def test_missing_required_or_nullable_field_fails_closed(tmp_path, path):
    outcome = run(tmp_path, delpath(ready_metadata(), path))
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata:")
    assert f"is missing {path[-1]}" in first(outcome)


# ---------------------------------------------------- mismatched cohorts

@pytest.mark.parametrize("cohort", ["0.6", "0.8", "0.7.0", "v0.7", 0.7, None])
def test_metadata_cohort_other_than_0_7_is_unsupported(tmp_path, cohort):
    outcome = run(tmp_path, setpath(ready_metadata(), ("cohort",), cohort))
    assert outcome.exit_code == 1
    assert first(outcome) == "INVALID_DOCUMENT: metadata: cohort must be the literal 0.7; other cohorts are unsupported"


@pytest.mark.parametrize("package_kwargs,metadata_edit,message", [
    ({"version": "0.6.58"}, {("components", "addon", "release_label"): None},
     "METADATA_CONFLICT: provisioned add-on version is outside the 0.7 cohort"),
    ({"explorer": "v0.6.1", "test_explorer": "v0.6.1"}, {("components", "explorer", "release_label"): None},
     "METADATA_CONFLICT: K25 cohort guard failed: Explorer release cohort differs from add-on 0.7"),
    ({"test_explorer": "v0.6.1"}, {},
     "METADATA_CONFLICT: K25 cohort guard failed: test-image Explorer override cohort differs from add-on 0.7"),
    ({"build_args": {"VRCEXPLORER_VERSION": "v0.6.1"}}, {("components", "explorer", "release_label"): None},
     "METADATA_CONFLICT: effective Explorer release for published outputs is outside the 0.7 cohort"),
    ({"build_args": {"EBUSGATEWAY_VERSION": "v0.6.9"}}, {},
     "METADATA_CONFLICT: effective gateway release pin is outside the 0.7 cohort"),
    ({"gateway_pin": "v0.6.9"}, {},
     "METADATA_CONFLICT: K25 cohort guard failed: gateway release pin cohort differs from add-on 0.7"),
    ({}, {("components", "gateway", "release_label"): "v0.6.9"},
     "METADATA_CONFLICT: components.gateway.release_label is outside the 0.7 cohort"),
    ({}, {("components", "explorer", "release_label"): "v0.8.0"},
     "METADATA_CONFLICT: components.explorer.release_label is outside the 0.7 cohort"),
    ({}, {("components", "addon", "release_label"): "0.6.58"},
     "METADATA_CONFLICT: components.addon.release_label is outside the 0.7 cohort"),
    ({}, {("components", "addon", "release_label"): "0.7.1"},
     "METADATA_CONFLICT: components.addon.release_label differs from the helianthus/config.json version"),
    ({}, {("components", "addon", "release_label"): "v0.7.0"},
     "METADATA_CONFLICT: components.addon.release_label differs from the helianthus/config.json version"),
    ({}, {("components", "explorer", "release_label"): "v0.7.2"},
     "METADATA_CONFLICT: components.explorer.release_label differs from the effective VRCEXPLORER_VERSION"),
    ({"build_args": {"EBUSGATEWAY_VERSION": "v0.7.5"}}, {},
     "METADATA_CONFLICT: components.gateway.release_label differs from the effective gateway release pin"),
    ({"build_args": {"BUILD_VERSION": "0.7.9"}}, {},
     "METADATA_CONFLICT: build workflow BUILD_VERSION differs from components.addon.release_label"),
    ({"build_args": {"VRCEXPLORER_VERSION": "${{ inputs.explorer }}"}}, {},
     "METADATA_CONFLICT: build workflow VRCEXPLORER_VERSION is not a literal"),
])
def test_mismatched_cohort_or_release_identity_fails_closed(tmp_path, package_kwargs, metadata_edit, message):
    meta = ready_metadata()
    for path, value in metadata_edit.items():
        setpath(meta, path, value)
    meta["disposition"] = "not-ready"
    outcome = run(tmp_path, meta, receipt_for(meta), package=make_package(tmp_path, **package_kwargs))
    assert outcome.exit_code == 1, text(outcome)
    assert message in outcome.lines, text(outcome)
    assert outcome.disposition is None


def test_conflicting_explorer_override_records_in_build_workflow_fail(tmp_path):
    def edit(workflow):
        step = next(step for step in workflow["jobs"]["build"]["steps"]
                    if str(step.get("uses", "")).startswith("docker/build-push-action@"))
        step["with"]["build-args"] += "VRCEXPLORER_VERSION=v0.7.9\n"
    outcome = run(tmp_path, ready_metadata(), receipt_for(ready_metadata()),
                  package=make_package(tmp_path, build_edit=edit))
    assert outcome.exit_code == 1
    assert "METADATA_CONFLICT: build workflow declares conflicting VRCEXPLORER_VERSION values" in outcome.lines


def test_build_step_without_override_uses_the_dockerfile_default(tmp_path):
    def add_second_build(workflow):
        steps = workflow["jobs"]["build"]["steps"]
        step = copy.deepcopy(next(step for step in steps
                                  if str(step.get("uses", "")).startswith("docker/build-push-action@")))
        step["with"]["build-args"] = "\n".join(line for line in step["with"]["build-args"].splitlines()
                                               if not line.startswith("VRCEXPLORER_VERSION="))
        steps.append(step)
    package = make_package(tmp_path, explorer="v0.7.1", build_args={"VRCEXPLORER_VERSION": "v0.7.2"},
                           build_edit=add_second_build)
    meta = setpath(ready_metadata(), ("components", "explorer", "release_label"), "v0.7.2")
    outcome = run(tmp_path, meta, receipt_for(meta), package=package)
    assert outcome.exit_code == 1
    assert "METADATA_CONFLICT: build workflow declares conflicting VRCEXPLORER_VERSION values" in outcome.lines


def test_calendar_release_labels_are_not_capture_times(tmp_path):
    meta = setpath(ready_metadata(), ("components", "ha_integration", "release_label"), "2026.10.1")
    outcome = run(tmp_path, meta, receipt_for(meta))
    assert outcome.exit_code == 0, text(outcome)


def test_build_version_not_tied_to_config_version_is_not_ready(tmp_path):
    meta = ready_metadata()
    package = make_package(tmp_path, build_args={"BUILD_VERSION": "${{ inputs.version }}"})
    outcome = run(tmp_path, meta, receipt_for(meta), package=package)
    assert outcome.exit_code == 1
    assert first(outcome) == "DISPOSITION_MISMATCH: claimed ready-for-review, derived not-ready"
    assert ("NOT_READY: build workflow BUILD_VERSION cannot be tied to the helianthus/config.json version offline"
            in outcome.lines)


def test_opaque_gateway_pin_without_label_is_unverified_not_ready(tmp_path):
    meta = setpath(ready_metadata(), ("components", "gateway", "release_label"), None)
    meta["disposition"] = "not-ready"
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == 0
    assert "NOT_READY: components.gateway.release_label is unavailable" in outcome.lines
    assert any(line.startswith("K25: UNVERIFIED: gateway release metadata unavailable") for line in outcome.lines)


# ------------------------------------------ changed artifact identity

def _change_association(meta: dict) -> None:
    new = "association-synthetic-changed"
    meta["association_id"] = new
    meta["output_binding"]["association_id"] = new
    meta["exact_bom"]["association_id"] = new
    for entry in meta["acceptance"].values():
        entry["association_id"] = new


def _add_native(meta: dict) -> None:
    meta["components"]["native_dependencies"].append(
        component("synthetic-transitive-library", "v2.0.0", "artifact-transitive-ready", ref("README.md", NATIVE)))


def _replace_output(meta: dict) -> None:
    meta["output_binding"]["artifact_ids"][0] = "output-aarch64-rebuilt"


IDENTITY_CHANGES = {
    # field: (public mutation, receipt evidence the validator compares against)
    "bundle_id": (lambda meta: setpath(meta, ("bundle_id",), "bundle-synthetic-changed"),
                  "EVIDENCE_MISMATCH: verification context bundle_id differs from the metadata"),
    "association_id": (_change_association,
                       "EVIDENCE_MISMATCH: verification context association_id differs from the metadata"),
    "addon.artifact_id": (lambda meta: setpath(meta, ("components", "addon", "artifact_id"), "artifact-addon-rebuilt"),
                          "EVIDENCE_MISMATCH: verification context components.addon differs from the metadata"),
    "gateway.artifact_id": (lambda meta: setpath(meta, ("components", "gateway", "artifact_id"), "artifact-gateway-rebuilt"),
                            "EVIDENCE_MISMATCH: verification context components.gateway differs from the metadata"),
    "explorer.artifact_id": (lambda meta: setpath(meta, ("components", "explorer", "artifact_id"), "artifact-explorer-rebuilt"),
                             "EVIDENCE_MISMATCH: verification context components.explorer differs from the metadata"),
    "ha_integration.artifact_id": (lambda meta: setpath(meta, ("components", "ha_integration", "artifact_id"),
                                                        "artifact-integration-rebuilt"),
                                   "EVIDENCE_MISMATCH: verification context components.ha_integration differs from the metadata"),
    "native.artifact_id": (lambda meta: setpath(meta, ("components", "native_dependencies", 0, "artifact_id"),
                                                "artifact-native-rebuilt"),
                           "EVIDENCE_MISMATCH: verification context components.native_dependencies differs from the metadata"),
    "native.added": (_add_native,
                     "EVIDENCE_MISMATCH: verification context components.native_dependencies differs from the metadata"),
    "gateway.release_label": (lambda meta: setpath(meta, ("components", "gateway", "release_label"), "v0.7.3"),
                              "EVIDENCE_MISMATCH: verification context components.gateway differs from the metadata"),
    "ha_integration.name": (lambda meta: setpath(meta, ("components", "ha_integration", "name"), "synthetic-ha-fork"),
                            "EVIDENCE_MISMATCH: verification context components.ha_integration differs from the metadata"),
    "explorer.public_ref": (lambda meta: setpath(meta, ("components", "explorer", "public_ref", "path"), "CHANGELOG.md"),
                            "EVIDENCE_MISMATCH: verification context components.explorer differs from the metadata"),
    "output_binding.artifact_ids": (_replace_output,
                                    "EVIDENCE_MISMATCH: output_binding.artifact_ids lists outputs outside expected_output_ids"),
    "exact_bom.attestation_id": (lambda meta: setpath(meta, ("exact_bom", "attestation_id"), "attestation-synthetic-other"),
                                 "EVIDENCE_MISMATCH: exact_bom is satisfied with an attestation_id that differs from the metadata"),
}


@pytest.mark.parametrize("field", list(IDENTITY_CHANGES))
@pytest.mark.parametrize("claim", ["not-ready", "ready-for-review"])
def test_changed_artifact_identity_fails_closed(tmp_path, field, claim):
    original = ready_metadata()
    receipt = receipt_for(original)
    changed = copy.deepcopy(original)
    mutate, message = IDENTITY_CHANGES[field]
    mutate(changed)
    changed["disposition"] = claim
    outcome = run(tmp_path, changed, receipt)
    assert outcome.exit_code == 1, text(outcome)
    assert message in outcome.lines, text(outcome)
    assert outcome.disposition is None


def test_reused_label_with_new_artifact_is_never_ready_without_new_evidence(tmp_path):
    meta = setpath(ready_metadata(), ("components", "gateway", "artifact_id"), "artifact-gateway-rebuilt")
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == 2
    assert first(outcome).startswith("PRIVATE_EVIDENCE_REQUIRED")


# ---------------------------------------------- strict parsing and schema

@pytest.mark.parametrize("target", [
    (), ("components",), ("components", "addon"), ("components", "addon", "public_ref"),
    ("components", "native_dependencies", 0), ("output_binding",), ("exact_bom",), ("acceptance",),
    ("acceptance", "Portal"),
])
def test_duplicate_keys_are_rejected_at_every_depth(tmp_path, target):
    outcome = run(tmp_path, None, meta_text=dumps_with_duplicate(ready_metadata(), target))
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata: duplicate key ")


@pytest.mark.parametrize("target", [(), ("checks",), ("checks", "acceptance"), ("components", "gateway")])
def test_receipt_duplicate_keys_are_rejected(tmp_path, target):
    meta = ready_metadata()
    outcome = run(tmp_path, meta, receipt_text=dumps_with_duplicate(receipt_for(meta), target))
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: verification context: duplicate key ")


@pytest.mark.parametrize("path", [(), ("components",), ("components", "explorer"), ("components", "addon", "public_ref"),
                                  ("output_binding",), ("exact_bom",), ("acceptance",), ("acceptance", "INT-13")])
def test_unknown_fields_are_rejected(tmp_path, path):
    meta = ready_metadata()
    target = meta
    for key in path:
        target = target[key]
    target["extension"] = "synthetic"
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == 1
    assert "has unknown field(s) extension" in first(outcome)


def test_unknown_field_names_with_restricted_data_are_redacted(tmp_path):
    meta = ready_metadata()
    meta[COMMIT_LIKE] = "synthetic"
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == 1
    assert first(outcome) == "INVALID_DOCUMENT: metadata: document has unknown field(s) <redacted>"


@pytest.mark.parametrize("path,value", [
    (("kind",), True), (("kind",), "release"), (("format",), "helianthus-candidate-metadata/1 "),
    (("format",), "helianthus-candidate-metadata/2"), (("bundle_id",), 7), (("architectures",), "amd64"),
    (("architectures",), []), (("architectures",), ["amd64", "amd64"]), (("architectures",), ["arm64"]),
    (("components", "addon", "release_label"), 0.7), (("components", "addon", "public_ref"), []),
    (("components", "addon"), None), (("disposition",), None), (("disposition",), "accepted"),
    (("output_binding", "artifact_ids"), None), (("output_binding", "status"), "complete"),
    (("acceptance", "identity", "status"), "waived"), (("exact_bom", "status"), True),
])
def test_wrong_types_and_enum_values_are_invalid(tmp_path, path, value):
    outcome = run(tmp_path, setpath(ready_metadata(), path, value))
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata:")


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b"{", "{\"format\": NaN}".encode(),
                                 b"\xff\xfe{}", "﻿{}".encode("utf-8"), b"[" * 100000])
def test_malformed_metadata_documents_are_invalid(tmp_path, raw):
    outcome = run(tmp_path, None, meta_text=raw)
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata:")
    assert not any(line.startswith("IDENTITY") for line in outcome.lines)


@pytest.mark.parametrize("value", [
    "Artifact-addon", "artifact", "artifact--addon", "artifact-addon-", "-artifact-addon", "artifact_addon",
    "z" * 79 + "-b", "artifact-addon\n", f"artifact-{COMMIT_LIKE[:7]}", f"artifact-{COMMIT_LIKE}",
    f"artifact-{DIGEST_LIKE[:12]}", "artifact-2026-10-23", f"artifact-{DATE_LIKE}", f"artifact-{LETTERS_LIKE}",
])
def test_opaque_ids_reject_bad_syntax_and_embedded_coordinates(tmp_path, value):
    outcome = run(tmp_path, setpath(ready_metadata(), ("components", "addon", "artifact_id"), value))
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata: components.addon.artifact_id")


def test_opaque_id_length_limit_is_inclusive(tmp_path):
    value = "z" * 78 + "-b"
    assert len(value) == 80
    meta = setpath(ready_metadata(), ("components", "addon", "artifact_id"), value)
    outcome = run(tmp_path, meta, receipt_for(meta))
    assert outcome.exit_code == 0, text(outcome)


@pytest.mark.parametrize("label", [
    "latest", "main", "0.7", "release-0.7", "v0.7.0 ", f"v0.7.0-0.{TIMESTAMP_LIKE}-{COMMIT_LIKE[:12]}",
    f"0.7.0+{COMMIT_LIKE[:7]}", f"v0.7.0+build.{DATE_LIKE}",
])
def test_release_labels_reject_mutable_pins_and_pseudoversions(tmp_path, label):
    outcome = run(tmp_path, setpath(ready_metadata(), ("components", "native_dependencies", 0, "release_label"), label))
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata: components.native_dependencies[0].release_label")


@pytest.mark.parametrize("repository", [
    "http://github.com/Project-Helianthus/helianthus-ha-addon", ADDON + "/", ADDON + ".git",
    "https://token@github.com/Project-Helianthus/helianthus-ha-addon", ADDON + "?ref=main", ADDON + "#readme",
    ADDON + "/tree/main", ADDON + "/blob/main/README.md", "https://gitlab.com/Project-Helianthus/helianthus-ha-addon",
    "https://github.com/Project-Helianthus", f"https://github.com/synthetic-org/{COMMIT_LIKE[:10]}",
    "https://github.com/synthetic-org/..",
])
def test_public_ref_repository_must_be_canonical(tmp_path, repository):
    outcome = run(tmp_path, setpath(ready_metadata(), ("components", "addon", "public_ref", "repository"), repository))
    assert outcome.exit_code == 1
    assert first(outcome) == ("INVALID_DOCUMENT: metadata: components.addon.public_ref.repository must be a "
                              "canonical public GitHub repository URL")


@pytest.mark.parametrize("path", [
    "", "/RELEASE_COHORT.md", "docs//evidence.md", "docs/./evidence.md", "docs/../evidence.md", "docs\\evidence.md",
    "docs/%2e%2e/evidence.md", "docs/evidence.md?plain=1", "docs/evidence.md#top", "docs/", "docs/evidence notes.md",
    f"evidence/{COMMIT_LIKE[:8]}.md", f"evidence/{IPV4_LIKE}.md", "evidence/2026-10-23.md",
])
def test_public_ref_path_must_be_clean_and_unrestricted(tmp_path, path):
    outcome = run(tmp_path, setpath(ready_metadata(), ("output_binding", "evidence_ref", "path"), path))
    assert outcome.exit_code == 1
    assert first(outcome) == ("INVALID_DOCUMENT: metadata: output_binding.evidence_ref.path must be a clean "
                              "repository-relative file path")


@pytest.mark.parametrize("name", ["", "has space", "/abs/path", "a..b", "name@host", f"host-{IPV4_LIKE}",
                                  f"library-{COMMIT_LIKE[:9]}", "github.com//org"])
def test_component_names_must_be_public_names(tmp_path, name):
    outcome = run(tmp_path, setpath(ready_metadata(), ("components", "ha_integration", "name"), name))
    assert outcome.exit_code == 1
    assert first(outcome) == "INVALID_DOCUMENT: metadata: components.ha_integration.name must be a public package or dependency name"


@pytest.mark.parametrize("path", [("output_binding", "association_id"), ("exact_bom", "association_id")]
                         + [("acceptance", key, "association_id") for key in ccm.ACCEPTANCE_KEYS])
def test_mismatched_associations_are_invalid(tmp_path, path):
    outcome = run(tmp_path, setpath(ready_metadata(), path, "association-synthetic-stale"))
    assert outcome.exit_code == 1
    assert first(outcome) == f"INVALID_DOCUMENT: metadata: {'.'.join(path)} must equal the current association_id"


@pytest.mark.parametrize("edits", [
    {("output_binding", "evidence_ref"): None},
    {("output_binding", "status"): "unbound"},
    {("output_binding", "status"): "partial", ("output_binding", "artifact_ids"): []},
    {("output_binding", "artifact_ids"): []},
    {("output_binding", "artifact_ids"): ["output-amd64-ready", "output-amd64-ready"]},
    {("exact_bom", "attestation_id"): None},
    {("exact_bom", "status"): "unverified"},
    {("exact_bom", "status"): "mismatch"},
    {("acceptance", "INT-14", "evidence_ref"): None},
    {("components", "native_dependencies"): [
        component("synthetic-native-family-library", None, "artifact-native-one", None),
        component("synthetic-native-family-library", None, "artifact-native-two", None)]},
    {("components", "gateway", "artifact_id"): "artifact-addon-ready"},
    {("components", "native_dependencies", 0, "artifact_id"): "artifact-explorer-ready"},
])
def test_inconsistent_status_or_duplicate_inventory_is_invalid(tmp_path, edits):
    meta = ready_metadata()
    for path, value in edits.items():
        setpath(meta, path, value)
    outcome = run(tmp_path, meta)
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: metadata:")


# ------------------------------------- not-ready derivation and promotion

@pytest.mark.parametrize("edits,reason", [
    ({("kind",): "preparatory"}, "kind is preparatory; preparation alone never means accepted"),
    ({("components", "ha_integration", "release_label"): None}, "components.ha_integration.release_label is unavailable"),
    ({("components", "native_dependencies", 0, "public_ref"): None},
     "components.native_dependencies[0].public_ref is unavailable"),
    ({("architectures",): ["aarch64", "amd64"]},
     "architectures differ from the set the build workflow publishes under the version tag"),
    ({("acceptance", "INT-12", "status"): "rejected"}, "acceptance.INT-12 is rejected"),
    ({("acceptance", "identity", "status"): "pending"}, "acceptance.identity is pending"),
    ({("components", "addon", "public_ref", "path"): "docs/absent.md"},
     "components.addon.public_ref does not exist in the provisioned package"),
])
def test_public_prerequisites_block_promotion_definitely(tmp_path, edits, reason):
    meta = ready_metadata()
    for path, value in edits.items():
        setpath(meta, path, value)
    checks = {"public_references": "missing"} if "public_ref" in reason else {}
    receipt = receipt_for(meta, review="satisfied", gates="satisfied", **checks)
    receipt["expected_architectures"] = receipt["bound_architectures"] = list(ARCHES)
    if "architectures" in reason:
        receipt["checks"]["output_binding"] = receipt["checks"]["exact_bom"] = "missing"
        receipt["attestation_id"] = None
    for key, entry in meta["acceptance"].items():
        if entry["status"] != "accepted":
            receipt["checks"]["acceptance"][key] = "missing"
    for claim, code, prefix in [("ready-for-review", 1, "DISPOSITION_MISMATCH"),
                                ("accepted-candidate", 1, "DISPOSITION_MISMATCH"),
                                ("not-ready", 0, "VALID: not-ready")]:
        meta["disposition"] = claim
        outcome = run(tmp_path, meta, receipt)
        assert outcome.exit_code == code, text(outcome)
        assert first(outcome).startswith(prefix)
        assert f"NOT_READY: {reason}" in outcome.lines


@pytest.mark.parametrize("freeze", [{"owner": "INT-16", "status": "unfrozen"}, {"owner": "INT-15", "status": "frozen"},
                                    None])
def test_candidate_needs_bom_frozen_by_int16(tmp_path, freeze):
    meta = ready_metadata()
    package = make_package(tmp_path, freeze=freeze if freeze is not None else {})
    outcome = run(tmp_path, meta, receipt_for(meta), package=package)
    assert outcome.exit_code == 1
    assert first(outcome) == "DISPOSITION_MISMATCH: claimed ready-for-review, derived not-ready"
    assert "NOT_READY: helianthus/bom.json is not frozen by INT-16" in outcome.lines


@pytest.mark.parametrize("claim,code,prefix", [("ready-for-review", 1, "DISPOSITION_MISMATCH"),
                                               ("accepted-candidate", 1, "DISPOSITION_MISMATCH"),
                                               ("not-ready", 0, "VALID: not-ready")])
def test_preparatory_bundle_cannot_promote_itself(tmp_path, claim, code, prefix):
    meta = setpath(ready_metadata(), ("kind",), "preparatory")
    meta["disposition"] = claim
    outcome = run(tmp_path, meta, receipt_for(meta, review="satisfied", gates="satisfied"))
    assert outcome.exit_code == code
    assert first(outcome).startswith(prefix)


def test_partial_outputs_stay_not_ready(tmp_path):
    meta = ready_metadata()
    meta["output_binding"]["status"] = "partial"
    meta["output_binding"]["artifact_ids"] = meta["output_binding"]["artifact_ids"][:3]
    meta["disposition"] = "not-ready"
    receipt = receipt_for(ready_metadata(), output_binding="missing", exact_bom="missing")
    receipt["bound_output_ids"] = receipt["bound_output_ids"][:3]
    receipt["bound_architectures"] = ARCHES[:3]
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 0, text(outcome)
    assert "NOT_READY: output_binding is partial" in outcome.lines
    assert "NOT_READY: verification check output_binding is missing" in outcome.lines
    assert "NOT_READY: verification check exact_bom is missing" in outcome.lines
    meta["disposition"] = "ready-for-review"
    assert first(run(tmp_path, meta, receipt)).startswith("DISPOSITION_MISMATCH")


def test_build_workflow_matrix_and_manifest_must_agree(tmp_path):
    def drop_i386_from_manifest(workflow):
        for step in workflow["jobs"]["manifest"]["steps"]:
            if "imagetools create" in step.get("run", ""):
                step["run"] = re.sub(r'"\$\{IMAGE_NAME\}:\$\{\{ steps\.addon\.outputs\.version \}\}-i386"', "",
                                     step["run"])
    meta = setpath(ready_metadata(), ("disposition",), "not-ready")
    receipt = receipt_for(meta, output_binding="missing")
    outcome = run(tmp_path, meta, receipt, package=make_package(tmp_path, build_edit=drop_i386_from_manifest))
    assert outcome.exit_code == 0, text(outcome)
    assert "NOT_READY: build workflow matrix and version manifest members differ" in outcome.lines


# --------------------------------------------------- private receipt rules

@pytest.mark.parametrize("check", list(ccm.READINESS_CHECKS + ccm.PROMOTION_CHECKS)
                         + [f"acceptance.{key}" for key in ccm.ACCEPTANCE_KEYS])
def test_any_private_mismatch_fails_even_for_not_ready(tmp_path, check):
    meta = setpath(ready_metadata(), ("disposition",), "not-ready")
    receipt = receipt_for(meta)
    if check.startswith("acceptance."):
        receipt["checks"]["acceptance"][check.split(".", 1)[1]] = "mismatch"
    else:
        receipt["checks"][check] = "mismatch"
        if check == "exact_bom":
            receipt["attestation_id"] = None
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 1
    assert f"EVIDENCE_MISMATCH: verification check {check} reports a mismatch" in outcome.lines


@pytest.mark.parametrize("check", list(ccm.READINESS_CHECKS) + [f"acceptance.{key}" for key in ccm.ACCEPTANCE_KEYS])
def test_missing_private_check_requires_evidence_for_elevated_claims(tmp_path, check):
    meta = ready_metadata()
    receipt = receipt_for(meta)
    if check.startswith("acceptance."):
        receipt["checks"]["acceptance"][check.split(".", 1)[1]] = "missing"
    else:
        receipt["checks"][check] = "missing"
        if check == "exact_bom":
            receipt["attestation_id"] = None
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 2
    assert first(outcome).startswith("PRIVATE_EVIDENCE_REQUIRED: claimed ready-for-review")
    assert f"NOT_READY: verification check {check} is missing" in outcome.lines
    meta["disposition"] = "not-ready"
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 0
    assert first(outcome) == "VALID: not-ready"


@pytest.mark.parametrize("edit,message", [
    (lambda meta, receipt: setpath(meta, ("acceptance", "Portal", "status"), "pending"),
     "EVIDENCE_MISMATCH: acceptance.Portal is satisfied while the metadata status is pending"),
    (lambda meta, receipt: setpath(meta, ("acceptance", "naming", "status"), "rejected"),
     "EVIDENCE_MISMATCH: acceptance.naming is satisfied while the metadata status is rejected"),
    (lambda meta, receipt: (setpath(meta, ("exact_bom", "status"), "unverified"),
                            setpath(meta, ("exact_bom", "attestation_id"), None)),
     "EVIDENCE_MISMATCH: exact_bom is satisfied with an attestation_id that differs from the metadata"),
    (lambda meta, receipt: setpath(meta, ("output_binding", "status"), "partial"),
     "EVIDENCE_MISMATCH: output_binding is satisfied while the metadata output_binding is not bound"),
    (lambda meta, receipt: setpath(receipt, ("bound_output_ids",), receipt["bound_output_ids"][:4]),
     "EVIDENCE_MISMATCH: output_binding is satisfied with an incomplete or different output inventory"),
    (lambda meta, receipt: setpath(receipt, ("bound_architectures",), ARCHES[:4]),
     "EVIDENCE_MISMATCH: output_binding is satisfied with an incomplete or different architecture inventory"),
    (lambda meta, receipt: (setpath(receipt, ("expected_output_ids",), []), setpath(receipt, ("bound_output_ids",), [])),
     "EVIDENCE_MISMATCH: output_binding is satisfied with an incomplete or different output inventory"),
    (lambda meta, receipt: (setpath(receipt, ("expected_architectures",), []),
                            setpath(receipt, ("bound_architectures",), [])),
     "EVIDENCE_MISMATCH: output_binding is satisfied with an incomplete or different architecture inventory"),
    (lambda meta, receipt: (setpath(receipt, ("bound_output_ids",), receipt["bound_output_ids"][:4]),
                            setpath(receipt, ("checks", "output_binding"), "missing")),
     "EVIDENCE_MISMATCH: exact_bom is satisfied with an incomplete or different output or architecture inventory"),
    (lambda meta, receipt: (setpath(meta, ("architectures",), ARCHES[:2]),
                            setpath(receipt, ("checks", "output_binding"), "missing")),
     "EVIDENCE_MISMATCH: exact_bom is satisfied with an incomplete or different output or architecture inventory"),
    (lambda meta, receipt: (setpath(receipt, ("expected_output_ids",), []), setpath(receipt, ("bound_output_ids",), []),
                            setpath(receipt, ("checks", "output_binding"), "missing"),
                            setpath(receipt, ("checks", "exact_bom"), "missing"),
                            setpath(receipt, ("attestation_id",), None)),
     "EVIDENCE_MISMATCH: inventory is satisfied while the expected output or architecture inventory is empty"),
    (lambda meta, receipt: setpath(receipt, ("bound_output_ids",), receipt["bound_output_ids"] + ["output-extra-ready"]),
     "EVIDENCE_MISMATCH: bound_output_ids is not a subset of expected_output_ids"),
    (lambda meta, receipt: (setpath(receipt, ("expected_architectures",), ARCHES[:2]),
                            setpath(receipt, ("bound_architectures",), ARCHES)),
     "EVIDENCE_MISMATCH: bound_architectures is not a subset of expected_architectures"),
    (lambda meta, receipt: (setpath(receipt, ("expected_architectures",), ARCHES[:2]),
                            setpath(receipt, ("bound_architectures",), ARCHES[:2]),
                            setpath(receipt, ("checks", "output_binding"), "missing")),
     "EVIDENCE_MISMATCH: expected_architectures differs from the set the provisioned build workflow publishes"),
    (lambda meta, receipt: (setpath(meta, ("components", "gateway", "public_ref"), None),
                            setpath(receipt, ("components", "gateway", "public_ref"), None)),
     "EVIDENCE_MISMATCH: public_references is satisfied while a component public_ref is unavailable"),
    (lambda meta, receipt: (setpath(meta, ("acceptance", "INT-13", "evidence_ref", "path"), "docs/absent.md")),
     "EVIDENCE_MISMATCH: public_references is satisfied while a reference is absent from the provisioned package"),
])
def test_satisfied_checks_that_contradict_evidence_fail(tmp_path, edit, message):
    meta = ready_metadata()
    receipt = receipt_for(meta)
    edit(meta, receipt)
    meta["disposition"] = "not-ready"
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 1, text(outcome)
    assert message in outcome.lines, text(outcome)


@pytest.mark.parametrize("field", ccm.RECEIPT_FIELDS)
def test_receipt_missing_field_is_malformed_not_an_implicit_pass(tmp_path, field):
    meta = ready_metadata()
    outcome = run(tmp_path, meta, delpath(receipt_for(meta), (field,)))
    assert outcome.exit_code == 1
    assert first(outcome) == f"INVALID_DOCUMENT: verification context: document is missing {field}"


@pytest.mark.parametrize("edit", [
    lambda receipt: setpath(receipt, ("format",), "helianthus-candidate-metadata/1"),
    lambda receipt: setpath(receipt, ("checks", "inventory"), "ok"),
    lambda receipt: setpath(receipt, ("checks", "acceptance", "Portal"), True),
    lambda receipt: delpath(receipt, ("checks", "acceptance", "identity")),
    lambda receipt: setpath(receipt, ("checks", "extension"), "satisfied"),
    lambda receipt: setpath(receipt, ("expected_architectures",), ["amd64", "amd64"]),
    lambda receipt: setpath(receipt, ("expected_output_ids",), ["Output-amd64"]),
    lambda receipt: setpath(receipt, ("attestation_id",), None),
    lambda receipt: (setpath(receipt, ("checks", "exact_bom"), "missing")),
    lambda receipt: setpath(receipt, ("components", "addon", "release_label"), "latest"),
    lambda receipt: setpath(receipt, ("bundle_id",), f"bundle-{COMMIT_LIKE[:7]}"),
])
def test_receipt_schema_and_publication_rules_are_strict(tmp_path, edit):
    meta = ready_metadata()
    receipt = receipt_for(meta)
    edit(receipt)
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT: verification context:")


def test_receipt_for_another_bundle_is_a_mismatch(tmp_path):
    other = setpath(ready_metadata(), ("bundle_id",), "bundle-synthetic-other")
    meta = setpath(ready_metadata(), ("disposition",), "not-ready")
    outcome = run(tmp_path, meta, receipt_for(other))
    assert outcome.exit_code == 1
    assert "EVIDENCE_MISMATCH: verification context bundle_id differs from the metadata" in outcome.lines


def test_unreadable_receipt_is_unavailable_and_its_path_is_not_echoed(tmp_path):
    meta = ready_metadata()
    missing = tmp_path / "private-records" / "receipt-for-site.json"
    outcome = run(tmp_path, meta, context=missing)
    assert outcome.exit_code == 2
    assert first(outcome).startswith("INPUT_UNAVAILABLE: verification context cannot be read")
    assert "private-records" not in text(outcome) and "receipt-for-site" not in text(outcome)


def test_receipt_inside_the_checkout_is_not_trusted(tmp_path):
    meta = ready_metadata()
    package = make_package(tmp_path)
    outcome = run(tmp_path, meta, receipt_for(meta), package=package, context=package / "docs" / "receipt.json")
    assert outcome.exit_code == 2
    assert first(outcome) == "INPUT_UNAVAILABLE: verification context must be provisioned outside the package checkout"


def test_receipt_contents_are_never_echoed(tmp_path):
    meta = ready_metadata()
    receipt = receipt_for(meta)
    receipt["checks"]["inventory"] = COMMIT_LIKE
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 1
    assert COMMIT_LIKE not in text(outcome)


# ----------------------------------------------------- local inputs

@pytest.mark.parametrize("relative", [relative for _, relative, _ in ccm.PACKAGE_INPUTS])
def test_missing_packaging_input_is_unavailable(tmp_path, relative):
    package = make_package(tmp_path)
    (package / relative).unlink()
    outcome = run(tmp_path, ready_metadata(), package=package)
    assert outcome.exit_code == 2
    assert first(outcome) == f"INPUT_UNAVAILABLE: package input {relative} cannot be read (No such file or directory)"


@pytest.mark.parametrize("relative,content", [("helianthus/config.json", "{"), ("helianthus/bom.json", "[]"),
                                              (".github/workflows/build.yml", "jobs: ["),
                                              (".github/workflows/test-image.yml", "- list")])
def test_unparseable_packaging_input_is_unavailable(tmp_path, relative, content):
    package = make_package(tmp_path)
    (package / relative).write_text(content, encoding="utf-8")
    outcome = run(tmp_path, ready_metadata(), package=package)
    assert outcome.exit_code == 2
    assert first(outcome).startswith(f"INPUT_UNAVAILABLE: package input {relative}")


def test_missing_package_root_and_metadata_are_unavailable(tmp_path):
    outcome = run(tmp_path, ready_metadata(), package=tmp_path / "absent")
    assert outcome.exit_code == 2
    assert first(outcome) == "INPUT_UNAVAILABLE: package root is not a readable directory"
    package = make_package(tmp_path)
    outcome = ccm.validate(tmp_path / "absent.json", package)
    assert outcome.exit_code == 2
    assert outcome.lines[0] == "INPUT_UNAVAILABLE: metadata cannot be read (No such file or directory)"


def test_definite_invalidity_takes_precedence_over_unavailable_input(tmp_path):
    meta = delpath(ready_metadata(), ("components", "addon"))
    outcome = run(tmp_path, meta, package=tmp_path / "absent")
    assert outcome.exit_code == 1
    assert first(outcome).startswith("INVALID_DOCUMENT")
    assert "INPUT_UNAVAILABLE" not in text(outcome)


def test_real_package_with_exact_revisions_never_leaks_them(tmp_path):
    """The current checkout pins exact revisions in its Dockerfile and BOM; none may reach output."""
    outcome = run(tmp_path, contract_example(), package=ROOT)
    assert outcome.exit_code == 1, text(outcome)
    assert "METADATA_CONFLICT: provisioned add-on version is outside the 0.7 cohort" in outcome.lines
    pins = re.findall(r"[0-9a-f]{40}", (ROOT / "helianthus/Dockerfile").read_text(encoding="utf-8"))
    assert pins
    assert not any(pin[:7] in text(outcome) for pin in pins)
    assert str(ROOT) not in text(outcome)


# --------------------------------------- offline, read-only, K25 reuse

def test_validator_imports_no_network_process_or_publication_modules():
    allowed = {"__future__", "argparse", "csv", "dataclasses", "json", "pathlib", "re", "typing", "yaml",
               "check_release_cohort"}
    for script, extra in [(SCRIPT, set()), (ROOT / "scripts/check_release_cohort.py", {"io", "shlex"})]:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert imported <= allowed | extra, imported - allowed - extra
    writers = {"open", "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace", "rmdir", "touch",
               "chmod", "symlink_to", "hardlink_to", "expanduser", "home", "getenv"}
    for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            assert called not in writers, called


def test_validation_opens_no_socket_or_process(tmp_path, monkeypatch):
    package = make_package(tmp_path)

    def refuse(*args, **kwargs):
        raise AssertionError("network or process access attempted")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    meta = ready_metadata()
    assert run(tmp_path, meta, receipt_for(meta), package=package).exit_code == 0


def test_packaging_cohort_is_delegated_to_k25(tmp_path, monkeypatch):
    calls = []
    original = k25.check

    def spy(config, dockerfile, gateway_release, workflow):
        calls.append((config["version"], "ARG VRCEXPLORER_VERSION=v0.7.1" in dockerfile, gateway_release,
                      "build" in workflow["jobs"] and "plan" in workflow["jobs"]))
        return original(config, dockerfile, gateway_release, workflow)
    monkeypatch.setattr(ccm.k25, "check", spy)
    meta = ready_metadata()
    assert run(tmp_path, meta, receipt_for(meta)).exit_code == 0
    assert calls == [("0.7.0", True, "v0.7.0", True)]

    def failing(*args):
        raise ValueError("synthetic K25 failure")
    monkeypatch.setattr(ccm.k25, "check", failing)
    outcome = run(tmp_path, meta, receipt_for(meta))
    assert outcome.exit_code == 1
    assert "METADATA_CONFLICT: K25 cohort guard failed: synthetic K25 failure" in outcome.lines


def test_build_arguments_use_the_k25_record_reader(tmp_path, monkeypatch):
    def failing(build_args):
        raise csv.Error("synthetic CSV failure")
        yield  # pragma: no cover
    monkeypatch.setattr(ccm.k25, "build_arg_records", failing)
    outcome = run(tmp_path, ready_metadata())
    assert outcome.exit_code == 1
    assert "METADATA_CONFLICT: build workflow build-args are malformed CSV" in outcome.lines
    source = SCRIPT.read_text(encoding="utf-8")
    for duplicate in ["csv.reader", "def cohort", "def arg_default", "\nVERSION = re.compile"]:
        assert duplicate not in source


def test_required_gate_registers_tests_once():
    gate = (ROOT / "scripts/ci_local.sh").read_text(encoding="utf-8")
    assert gate.count("tests/test_candidate_metadata.py") == 1
    assert "python3 -m pytest -q tests/test_candidate_metadata.py\n" in gate


def test_k25_diagnostics_are_redacted(tmp_path, monkeypatch):
    assert ccm._redact(f"pin {COMMIT_LIKE} at {IPV4_LIKE}") == "pin <redacted> at <redacted>"

    def failing(*args):
        raise ValueError(f"pin {COMMIT_LIKE} differs")
    monkeypatch.setattr(ccm.k25, "check", failing)
    outcome = run(tmp_path, ready_metadata())
    assert "METADATA_CONFLICT: K25 cohort guard failed: pin <redacted> differs" in outcome.lines


# ------------------------------------------------- edge cases from review

@pytest.mark.parametrize("raw", ['{"format": 1' + "0" * 5000 + "}", '{"format": -1' + "0" * 5000 + "}"])
def test_oversized_integer_literals_are_invalid_not_a_traceback(tmp_path, raw):
    outcome = run(tmp_path, None, meta_text=raw)
    assert outcome.exit_code == 1
    assert first(outcome) == "INVALID_DOCUMENT: metadata: not JSON (unsupported literal)"
    meta = ready_metadata()
    outcome = run(tmp_path, meta, receipt_text=raw)
    assert first(outcome) == "INVALID_DOCUMENT: verification context: not JSON (unsupported literal)"


@pytest.mark.parametrize("path", [".git/config", "docs/.GIT/HEAD"])
def test_git_metadata_is_never_a_public_reference(tmp_path, path):
    outcome = run(tmp_path, setpath(ready_metadata(), ("acceptance", "Portal", "evidence_ref", "path"), path))
    assert outcome.exit_code == 1
    assert first(outcome) == ("INVALID_DOCUMENT: metadata: acceptance.Portal.evidence_ref.path must be a clean "
                              "repository-relative file path")


def test_local_references_match_exact_case_and_stay_inside_the_checkout(tmp_path):
    package = make_package(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (package / "docs" / "escape.md").symlink_to(outside)
    (package / "docs" / "inside.md").symlink_to(package / EVIDENCE)
    cases = [("release_cohort.md", True), ("docs/escape.md", True), ("docs", True), ("docs/inside.md", False),
             ("RELEASE_COHORT.md", False)]
    for path, absent in cases:
        meta = setpath(ready_metadata(), ("components", "addon", "public_ref", "path"), path)
        receipt = receipt_for(meta, public_references="missing")
        meta["disposition"] = "not-ready"
        outcome = run(tmp_path, meta, receipt, package=package)
        assert outcome.exit_code == 0, text(outcome)
        line = "NOT_READY: components.addon.public_ref does not exist in the provisioned package"
        assert (line in outcome.lines) is absent, path


def test_native_dependency_order_does_not_matter(tmp_path):
    meta = ready_metadata()
    _add_native(meta)
    receipt = receipt_for(meta)
    receipt["components"]["native_dependencies"].reverse()
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 0, text(outcome)
    assert "ARTIFACT: components.native_dependencies[1] artifact-transitive-ready" in outcome.lines


def test_conflicting_build_version_records_fail(tmp_path):
    def edit(workflow):
        step = next(step for step in workflow["jobs"]["build"]["steps"]
                    if str(step.get("uses", "")).startswith("docker/build-push-action@"))
        step["with"]["build-args"] += "BUILD_VERSION=0.7.0\n"
    outcome = run(tmp_path, ready_metadata(), receipt_for(ready_metadata()), package=make_package(tmp_path, build_edit=edit))
    assert outcome.exit_code == 1
    assert "METADATA_CONFLICT: build workflow declares conflicting BUILD_VERSION values" in outcome.lines


@pytest.mark.parametrize("where", ["metadata", "expected_output_ids", "bound_output_ids"])
def test_output_ids_cannot_substitute_for_component_entries(tmp_path, where):
    meta = ready_metadata()
    receipt = receipt_for(meta)
    if where == "metadata":
        meta["output_binding"]["artifact_ids"][0] = "artifact-integration-ready"
        expected = "INVALID_DOCUMENT: metadata: output_binding.artifact_ids must not reuse component artifact IDs"
    else:
        receipt[where].append("artifact-native-ready")
        expected = f"INVALID_DOCUMENT: verification context: {where} must not reuse component artifact IDs"
    outcome = run(tmp_path, meta, receipt)
    assert outcome.exit_code == 1
    assert expected in outcome.lines


# ------------------------------------------------------------- CLI

def test_cli_reports_and_exits(tmp_path):
    meta = ready_metadata()
    package = make_package(tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(meta), encoding="utf-8")
    receipt = tmp_path / "private" / "receipt.json"
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(receipt_for(meta)), encoding="utf-8")
    base = [sys.executable, str(SCRIPT), "--metadata", str(metadata), "--package-root", str(package)]
    result = subprocess.run(base + ["--verification-context", str(receipt)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "VALID: ready-for-review"
    result = subprocess.run(base, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert result.stdout.startswith("PRIVATE_EVIDENCE_REQUIRED")
    result = subprocess.run([sys.executable, str(SCRIPT), "--metadata", str(metadata)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "--package-root" in result.stderr


def test_help_documents_usage_and_limits():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    help_text = " ".join(result.stdout.split())
    for expected in ["--metadata", "--package-root", "--verification-context", "PRIVATE_EVIDENCE_REQUIRED",
                     "INPUT_UNAVAILABLE", "METADATA_CONFLICT", "EVIDENCE_MISMATCH", "DISPOSITION_MISMATCH",
                     "public-only", "never authenticated", "no fetch", "hardware qualification"]:
        assert expected in help_text, expected

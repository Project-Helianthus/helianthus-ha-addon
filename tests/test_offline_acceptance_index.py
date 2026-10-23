"""Synthetic manifests only; no execution, release, tag, deployment or hardware qualification."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_offline_acceptance_index as oai  # noqa: E402
import check_candidate_metadata as ccm  # noqa: E402


SCRIPT = ROOT / "scripts/build_offline_acceptance_index.py"
DOC = ROOT / "docs/offline-acceptance-index.md"
ADDON = "https://github.com/Project-Helianthus/helianthus-ha-addon"
GATEWAY = "https://github.com/Project-Helianthus/helianthus-ebusgateway"
EXPLORER = "https://github.com/Project-Helianthus/helianthus-vrc-explorer"
INTEGRATION = "https://github.com/synthetic-org/synthetic-ha-integration"
NATIVE = "https://github.com/synthetic-org/synthetic-native-family-library"
ARCHES = ["aarch64", "amd64", "armv7", "armhf", "i386"]
BUNDLE = "bundle-synthetic-index"
ASSOCIATION = "association-synthetic-index"
OTHER_BUNDLE = "bundle-synthetic-elsewhere"
OTHER_ASSOCIATION = "association-synthetic-earlier"
EVIDENCE = "docs/synthetic-evidence.md"
ARTIFACTS = {"addon": "artifact-addon-index", "gateway": "artifact-gateway-index",
             "explorer": "artifact-explorer-index", "ha_integration": "artifact-integration-index"}
RANGE = "transport-proxy-dual-client"
SINGLE = "adapter-direct-ad01"
# Computed, never embedded: a commit-like fragment that must never reach the index.
COMMIT_LIKE = hashlib.sha1(b"synthetic commit").hexdigest()
HEXLIKE = re.compile(r"[0-9A-Fa-f]{7,}")


# ---------------------------------------------------------------- fixtures

def ref(path: str, repository: str = ADDON) -> dict:
    return {"repository": repository, "path": path}


def component(name: str, label: str | None, artifact: str, public_ref: dict | None) -> dict:
    return {"name": name, "release_label": label, "artifact_id": artifact, "public_ref": public_ref}


def candidate_metadata() -> dict:
    """A synthetic candidate whose public prerequisites are met except acceptance, which is pending."""
    return {
        "format": "helianthus-candidate-metadata/1",
        "bundle_id": BUNDLE,
        "association_id": ASSOCIATION,
        "kind": "candidate",
        "cohort": "0.7",
        "components": {
            "addon": component("helianthus-ha-addon", "0.7.0", ARTIFACTS["addon"], ref("RELEASE_COHORT.md")),
            "gateway": component("helianthus-ebusgateway", "v0.7.0", ARTIFACTS["gateway"], ref("README.md", GATEWAY)),
            "explorer": component("helianthus-vrc-explorer", "v0.7.1", ARTIFACTS["explorer"],
                                  ref("README.md", EXPLORER)),
            "ha_integration": component("synthetic-ha-integration", "v0.9.4", ARTIFACTS["ha_integration"],
                                        ref("README.md", INTEGRATION)),
            "native_dependencies": [component("synthetic-native-family-library", "v1.2.3",
                                              "artifact-native-index", ref("README.md", NATIVE))],
        },
        "architectures": list(ARCHES),
        "output_binding": {"status": "bound", "association_id": ASSOCIATION,
                           "artifact_ids": [f"output-{arch}-index" for arch in ARCHES], "evidence_ref": ref(EVIDENCE)},
        "exact_bom": {"status": "verified", "association_id": ASSOCIATION,
                      "attestation_id": "attestation-synthetic-index"},
        "acceptance": {key: {"status": "pending", "association_id": ASSOCIATION, "evidence_ref": None}
                       for key in ccm.ACCEPTANCE_KEYS},
        "disposition": "not-ready",
    }


def results_doc(bundle: str = BUNDLE, association: str = ASSOCIATION, **overrides: dict | None) -> dict:
    """One passing result per software gate; overrides update or (with None) drop a gate's entry."""
    entries = {gate: {"gate": gate, "artifact_id": ARTIFACTS[key], "outcome": "pass", "omitted_checks": []}
               for gate, key in oai.SOFTWARE_GATES}
    for name, entry in overrides.items():
        gate = name.replace("_", "-")
        if entry is None:
            entries.pop(gate)
        else:
            entries[gate] = {**entries[gate], **entry}
    return {"format": oai.RESULTS_FORMAT, "bundle_id": bundle, "association_id": association,
            "results": list(entries.values())}


def record(gate: str) -> str:
    """The per-row evidence record of a physical gate, one file of its own."""
    return f"docs/records/{gate}.md"


def evidence_doc(environment: str = "live", bundle: str = BUNDLE, association: str = ASSOCIATION,
                 gates: tuple[str, ...] | None = None) -> dict:
    """Live operator evidence, reviewed row by row, with every case passing for the selected gates."""
    selected = gates if gates is not None else oai.PHYSICAL_GATE_IDS
    return {"format": oai.EVIDENCE_FORMAT, "bundle_id": bundle, "association_id": association,
            "environment": environment,
            "gates": [{"gate": gate, "independent_review": "satisfied", "evidence_ref": ref(record(gate)),
                       "cases": [{"case": case, "outcome": "pass"} for case in oai.CASES[gate]]}
                      for gate in selected]}


def without(*gates: str) -> tuple[str, ...]:
    return tuple(gate for gate in oai.PHYSICAL_GATE_IDS if gate not in gates)


def gate_entry(doc: dict, gate: str) -> dict:
    return next(entry for entry in doc["gates"] if entry["gate"] == gate)


REAL_BUILD = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
REAL_EXPLORER = re.search(r"^ +VRCEXPLORER_VERSION=(\S+)$", REAL_BUILD, re.M)[1]
EXPLORER_OCCURRENCE = re.compile(rf"(?<![\w.]){re.escape(REAL_EXPLORER)}(?![\w.])")


def make_worktree(tmp_path: Path, freeze: dict | None = None, build_edit=None) -> Path:
    """A synthetic 0.7 worktree derived from this checkout's packaging; only the release slots differ."""
    tree = tmp_path / "worktree"
    for directory in ("helianthus", ".github/workflows", "docs", "acceptance"):
        (tree / directory).mkdir(parents=True)
    config = json.loads((ROOT / "helianthus/config.json").read_text(encoding="utf-8"))
    config["version"] = "0.7.0"
    (tree / "helianthus/config.json").write_text(json.dumps(config), encoding="utf-8")
    dockerfile = (ROOT / "helianthus/Dockerfile").read_text(encoding="utf-8")
    dockerfile = re.sub(r"^ARG VRCEXPLORER_VERSION=\S+$", "ARG VRCEXPLORER_VERSION=v0.7.1", dockerfile, flags=re.M)
    dockerfile = re.sub(r"^ARG EBUSGATEWAY_VERSION=\S+$", "ARG EBUSGATEWAY_VERSION=opaque-test-pin", dockerfile,
                        flags=re.M)
    (tree / "helianthus/Dockerfile").write_text(dockerfile, encoding="utf-8")
    build = EXPLORER_OCCURRENCE.sub(lambda match: "v0.7.1", REAL_BUILD)
    build = re.sub(r"^( +EBUSGATEWAY_VERSION=)\S+$", lambda match: match[1] + "opaque-test-pin", build, flags=re.M)
    (tree / ".github/workflows/build.yml").write_text(build_edit(build) if build_edit else build, encoding="utf-8")
    test_image = yaml.safe_load((ROOT / ".github/workflows/test-image.yml").read_text(encoding="utf-8"))
    for job in test_image["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("docker/build-push-action@"):
                lines = [line for line in step["with"]["build-args"].splitlines()
                         if not line.startswith("VRCEXPLORER_VERSION=")]
                step["with"]["build-args"] = "\n".join(lines + ["VRCEXPLORER_VERSION=v0.7.1"]) + "\n"
    (tree / ".github/workflows/test-image.yml").write_text(yaml.safe_dump(test_image), encoding="utf-8")
    bom = {"format": "helianthus-addon-bom/1",
           "freeze": freeze if freeze is not None else {"owner": "INT-16", "status": "frozen"}}
    (tree / "helianthus/bom.json").write_text(json.dumps(bom), encoding="utf-8")
    (tree / "RELEASE_COHORT.md").write_text("synthetic\n", encoding="utf-8")
    (tree / EVIDENCE).write_text("synthetic\n", encoding="utf-8")
    (tree / "docs/records").mkdir()
    for gate in oai.PHYSICAL_GATE_IDS:
        (tree / record(gate)).write_text(f"synthetic record {gate}\n", encoding="utf-8")
    return tree


def snapshot(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def write(tree: Path, name: str, doc: dict | str | bytes) -> Path:
    return write_at(tree / "acceptance" / name, doc)


def write_at(path: Path, doc: dict | str | bytes) -> Path:
    raw = doc if isinstance(doc, (str, bytes)) else json.dumps(doc)
    path.write_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    return path


def check(index: oai.Index, tmp_path: Path) -> oai.Index:
    text = json.dumps(index.document)
    assert json.loads(text) == index.document
    assert str(tmp_path) not in text
    assert not HEXLIKE.search(text), text
    assert index.document["note"] == oai.NOTE
    assert index.document["format"] == oai.INDEX_FORMAT
    return index


def run(tmp_path: Path, meta: dict | None = None, results: tuple = (), evidence: tuple = (),
        tree: Path | None = None) -> oai.Index:
    """Write the documents inside the worktree, build the index and check it wrote and leaked nothing."""
    tree = tree or (tmp_path / "worktree" if (tmp_path / "worktree").is_dir() else make_worktree(tmp_path))
    metadata = write(tree, "metadata.json", meta if meta is not None else candidate_metadata())
    result_paths = [write(tree, f"results-{number}.json", doc) for number, doc in enumerate(results)]
    evidence_paths = [write(tree, f"evidence-{number}.json", doc) for number, doc in enumerate(evidence)]
    before = snapshot(tmp_path)
    index = oai.build_index(tree, metadata, result_paths, evidence_paths)
    assert snapshot(tmp_path) == before, "the index builder must not write anything"
    return check(index, tmp_path)


def complete(tmp_path: Path, meta: dict | None = None) -> oai.Index:
    return run(tmp_path, meta, results=(results_doc(),), evidence=(evidence_doc(),))


def rows(index: oai.Index) -> dict:
    return {row["gate"]: row for section in ("software", "physical") for row in index.document[section]["gates"]}


def row(index: oai.Index, gate: str) -> tuple[str, list[str]]:
    found = rows(index)[gate]
    return found["status"], found["reasons"]


def text(index: oai.Index) -> str:
    return json.dumps(index.document)


def listing_spy(monkeypatch, listed: list) -> None:
    """Record the identity of every directory listed, whether by path or by descriptor."""
    def record(original):
        def spy(path=".", *args, **kwargs):
            if isinstance(path, int):
                info = os.fstat(path)
                listed.append((info.st_dev, info.st_ino))
            else:
                info = os.stat(path)
                listed.append((info.st_dev, info.st_ino))
            return original(path, *args, **kwargs)
        return spy
    monkeypatch.setattr(os, "scandir", record(os.scandir))
    monkeypatch.setattr(os, "listdir", record(os.listdir))


def identity(path: Path) -> tuple:
    info = os.stat(path)
    return info.st_dev, info.st_ino


UNESTABLISHED = ("unverified", ["the candidate identity was not established"])


# --------------------------------------------------------- overall result

def test_complete_live_evidence_completes_the_index_without_promoting_the_candidate(tmp_path):
    index = complete(tmp_path)
    assert index.exit_code == 0, index.document["blocking"]
    doc = index.document
    assert doc["evidence"] == "complete"
    assert doc["software"]["status"] == doc["physical"]["status"] == "complete"
    assert doc["blocking"] == [] and doc["input_errors"] == []
    assert all(found["status"] == "pass" and found["reasons"] == [] for found in rows(index).values())
    assert [found["gate"] for found in doc["software"]["gates"]] == [oai.CANDIDATE_GATE, *oai.SOFTWARE_GATE_IDS]
    assert [found["gate"] for found in doc["physical"]["gates"]] == list(oai.PHYSICAL_GATE_IDS)
    candidate = doc["candidate"]
    assert (candidate["bundle_id"], candidate["association_id"], candidate["kind"]) == (BUNDLE, ASSOCIATION,
                                                                                        "candidate")
    assert candidate["validator"]["exit_code"] == 0
    assert candidate["validator"]["derived_disposition"] == "not-ready", "a complete index promotes nothing"
    assert candidate["validator"]["lines"][0] == "VALID: not-ready"
    assert ccm.NOTE not in candidate["validator"]["lines"]
    for found in doc["software"]["gates"][1:]:
        assert found["artifact_id"] == ARTIFACTS[found["subject"].split(".")[1]]
    assert "ready" not in json.dumps({key: value for key, value in doc.items() if key != "candidate"})


def test_software_results_alone_keep_every_physical_row_unverified(tmp_path):
    index = run(tmp_path, results=(results_doc(),))
    assert index.exit_code == 2
    doc = index.document
    assert doc["evidence"] == "incomplete"
    assert doc["software"]["status"] == "complete"
    assert doc["physical"]["status"] == "incomplete"
    for gate in oai.PHYSICAL_GATE_IDS:
        assert row(index, gate) == ("unverified", ["no operator evidence was supplied"])
    assert doc["blocking"] == [f"{gate}: no operator evidence was supplied" for gate in oai.PHYSICAL_GATE_IDS]


def test_no_results_leave_every_software_gate_missing(tmp_path):
    index = run(tmp_path, evidence=(evidence_doc(),))
    assert index.exit_code == 2
    assert row(index, oai.CANDIDATE_GATE) == ("pass", [])
    for gate in oai.SOFTWARE_GATE_IDS:
        assert row(index, gate) == ("unverified", ["no result was supplied (missing)"])
    assert index.document["physical"]["status"] == "complete"


def test_an_omitted_gate_cannot_disappear_from_the_index(tmp_path):
    index = run(tmp_path, results=(results_doc(gateway_local_gate=None),), evidence=(evidence_doc(),))
    assert index.exit_code == 2
    assert row(index, "gateway-local-gate") == ("unverified", ["no result was supplied (missing)"])
    assert len(index.document["software"]["gates"]) == 1 + len(oai.SOFTWARE_GATES)
    index = run(tmp_path, results=(results_doc(),), evidence=(evidence_doc(gates=without(SINGLE)),))
    assert row(index, SINGLE) == ("unverified", ["no operator evidence was supplied"])
    assert len(index.document["physical"]["gates"]) == len(oai.PHYSICAL_GATES)


def test_an_input_error_keeps_the_index_incomplete_even_when_every_row_passes(tmp_path):
    index = run(tmp_path, results=(results_doc(), "{"), evidence=(evidence_doc(),))
    assert all(found["status"] == "pass" for found in rows(index).values())
    assert index.document["evidence"] == "incomplete"
    assert index.document["blocking"] == [
        "input: results[1]: not JSON (Expecting property name enclosed in double quotes at line 1 column 2)"]
    assert index.exit_code == 1


# ------------------------------------------------- software join and outcome

@pytest.mark.parametrize("field, value, reason", [
    ("bundle_id", OTHER_BUNDLE, "only results for a different BOM were supplied"),
    ("association_id", OTHER_ASSOCIATION, "only results for another association of this bundle were supplied (stale)"),
    ("artifact_id", "artifact-gateway-elsewhere",
     "the result names an artifact other than the candidate's components.gateway"),
    ("gate", "addon-local-gate", "no result was supplied (missing)"),
])
def test_every_join_key_field_must_match_the_candidate(tmp_path, field, value, reason):
    """Vary bundle, association, artifact and gate one at a time from a passing gateway result."""
    gateway = results_doc()["results"][1]
    assert gateway["gate"] == "gateway-local-gate"
    others = results_doc(gateway_local_gate=None)
    if field in ("bundle_id", "association_id"):
        docs = (others, {**results_doc(), field: value, "results": [gateway]})
    else:
        docs = ({**others, "results": others["results"] + [{**gateway, field: value}]},)
    index = run(tmp_path, results=docs, evidence=(evidence_doc(),))
    assert index.exit_code == 2
    assert row(index, "gateway-local-gate") == ("unverified", [reason])
    if field == "gate":  # The relabelled result now duplicates the add-on gate and is not counted twice.
        assert row(index, "addon-local-gate") == (
            "unverified", ["2 results were supplied for this gate and association; exactly one is required"])
    else:
        assert value not in text(index)
        assert all(row(index, gate)[0] == "pass" for gate in oai.SOFTWARE_GATE_IDS if gate != "gateway-local-gate")


@pytest.mark.parametrize("entry, status, reason", [
    ({"outcome": "fail"}, "fail", "the result reports a failure"),
    ({"outcome": "timeout"}, "unverified", "the run timed out"),
    ({"outcome": "not-run"}, "unverified", "the check was not run"),
    ({"omitted_checks": ["verify-github", "pip-bootstrap"]}, "unverified", "the run omitted 2 required check(s)"),
    ({"outcome": "timeout", "omitted_checks": ["verify-github"]}, "unverified", "the run timed out"),
    ({"outcome": "fail", "omitted_checks": ["verify-github"]}, "fail", "the result reports a failure"),
])
def test_only_a_complete_passing_run_counts_as_pass(tmp_path, entry, status, reason):
    index = run(tmp_path, results=(results_doc(addon_local_gate=entry),), evidence=(evidence_doc(),))
    assert index.exit_code == 2
    assert row(index, "addon-local-gate") == (status, [reason])
    assert index.document["evidence"] == "incomplete"
    assert "verify-github" not in text(index), "omitted check names are counted, never echoed"


@pytest.mark.parametrize("second", [{}, {"outcome": "fail"}])
def test_more_than_one_current_result_for_a_gate_is_ambiguous(tmp_path, second):
    duplicate = results_doc(addon_local_gate=second)
    duplicate["results"] = duplicate["results"][:1]
    index = run(tmp_path, results=(results_doc(), duplicate), evidence=(evidence_doc(),))
    assert row(index, "addon-local-gate") == (
        "unverified", ["2 results were supplied for this gate and association; exactly one is required"])
    assert index.exit_code == 2


def test_stale_and_foreign_results_stay_history_beside_a_current_pass(tmp_path):
    stale = results_doc(association=OTHER_ASSOCIATION, addon_local_gate={"outcome": "fail"})
    foreign = results_doc(bundle=OTHER_BUNDLE, addon_local_gate={"outcome": "timeout"})
    index = run(tmp_path, results=(stale, foreign, results_doc()), evidence=(evidence_doc(),))
    assert index.exit_code == 0, index.document["blocking"]
    assert OTHER_BUNDLE not in text(index) and OTHER_ASSOCIATION not in text(index)


def test_a_component_artifact_of_another_subject_does_not_cross_join(tmp_path):
    swapped = results_doc(addon_local_gate={"artifact_id": ARTIFACTS["gateway"]})
    index = run(tmp_path, results=(swapped,), evidence=(evidence_doc(),))
    assert row(index, "addon-local-gate") == (
        "unverified", ["the result names an artifact other than the candidate's components.addon"])
    assert row(index, "gateway-local-gate") == ("pass", [])


# ---------------------------------------------------------- physical rows

def test_simulated_evidence_never_upgrades_live_acceptance(tmp_path):
    index = run(tmp_path, results=(results_doc(),), evidence=(evidence_doc(environment="simulated"),))
    assert index.exit_code == 2
    for gate in oai.PHYSICAL_GATE_IDS:
        assert row(index, gate) == (
            "unverified", ["only simulated evidence was supplied; it cannot establish live acceptance"])
    failing = evidence_doc(environment="simulated", gates=(SINGLE,))
    gate_entry(failing, SINGLE)["cases"][0]["outcome"] = "fail"
    index = run(tmp_path, results=(results_doc(),), evidence=(failing,))
    assert row(index, SINGLE)[0] == "unverified"


def test_live_evidence_decides_beside_simulated_evidence(tmp_path):
    index = run(tmp_path, results=(results_doc(),), evidence=(evidence_doc(environment="simulated"), evidence_doc()))
    assert index.exit_code == 0, index.document["blocking"]


def test_software_results_cannot_name_a_physical_gate(tmp_path):
    smuggled = results_doc()
    smuggled["results"].append({"gate": SINGLE, "artifact_id": ARTIFACTS["gateway"], "outcome": "pass",
                                "omitted_checks": []})
    index = run(tmp_path, results=(smuggled,))
    assert index.exit_code == 1
    assert index.document["input_errors"] == [
        "results[0]: results[4].gate must be one of " + ", ".join(oai.SOFTWARE_GATE_IDS)]
    assert row(index, SINGLE) == ("unverified", ["no operator evidence was supplied"])
    assert row(index, "addon-local-gate") == ("unverified", ["no result was supplied (missing)"])


def test_the_candidate_identity_row_is_never_supplied_as_a_result(tmp_path):
    supplied = results_doc()
    supplied["results"].append({"gate": oai.CANDIDATE_GATE, "artifact_id": ARTIFACTS["addon"], "outcome": "pass",
                                "omitted_checks": []})
    index = run(tmp_path, results=(supplied,))
    assert index.exit_code == 1
    assert index.document["input_errors"][0].startswith("results[0]: results[4].gate must be one of")


def test_operator_evidence_and_results_are_supplied_separately(tmp_path):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    evidence = write(tree, "evidence.json", evidence_doc())
    index = check(oai.build_index(tree, metadata, [evidence], [results]), tmp_path)
    assert index.exit_code == 1
    assert index.document["input_errors"] == ["results[0]: document has 2 unknown field(s)",
                                              "operator evidence[0]: document has 1 unknown field(s)"]
    assert all(row(index, gate)[0] == "unverified" for gate in oai.SOFTWARE_GATE_IDS + oai.PHYSICAL_GATE_IDS)


def edit_evidence(gate: str, edit) -> dict:
    doc = evidence_doc()
    edit(gate_entry(doc, gate))
    return doc


@pytest.mark.parametrize("gate, edit, status, reason", [
    (RANGE, lambda entry: entry["cases"][0].update(outcome="fail"), "fail", "1 case(s) failed"),
    (RANGE, lambda entry: entry["cases"].pop(), "unverified", "1 case(s) are not accounted for"),
    (RANGE, lambda entry: entry["cases"][2].update(outcome="blocked"), "unverified",
     "1 case(s) were blocked or not run"),
    (RANGE, lambda entry: entry["cases"][3].update(outcome="not-run"), "unverified",
     "1 case(s) were blocked or not run"),
    (RANGE, lambda entry: (entry["cases"].pop(), entry["cases"][0].update(outcome="fail")), "fail",
     "1 case(s) failed"),
    (SINGLE, lambda entry: entry["cases"][0].update(outcome="fail"), "fail", "1 case(s) failed"),
    (SINGLE, lambda entry: entry["cases"][0].update(outcome="blocked"), "unverified",
     "1 case(s) were blocked or not run"),
    (SINGLE, lambda entry: entry.update(independent_review="missing"), "unverified",
     "independent review of this row's evidence is missing"),
    (SINGLE, lambda entry: entry.update(evidence_ref=None), "unverified", "no per-row evidence record is linked"),
    (SINGLE, lambda entry: entry.update(evidence_ref=ref("docs/absent-evidence.md")), "unverified",
     "the linked per-row evidence record does not exist in the worktree"),
    (SINGLE, lambda entry: entry.update(evidence_ref=ref("README.md", "https://github.com/anyone/anything")),
     "unverified", "the linked per-row evidence record is not in a Project-Helianthus repository"),
    (SINGLE, lambda entry: entry.update(evidence_ref=ref("acceptance/evidence-0.json")), "unverified",
     "the linked per-row evidence record is one of the supplied inputs"),
    (SINGLE, lambda entry: entry.update(evidence_ref=ref("acceptance/metadata.json")), "unverified",
     "the linked per-row evidence record is one of the supplied inputs"),
    (SINGLE, lambda entry: entry.update(evidence_ref=ref("docs/evidence-hardlink.json")), "unverified",
     "the linked per-row evidence record is one of the supplied inputs"),
])
def test_physical_rows_need_every_case_a_review_and_a_record(tmp_path, gate, edit, status, reason):
    tree = make_worktree(tmp_path)
    write(tree, "evidence-0.json", "placeholder")
    os.link(tree / "acceptance/evidence-0.json", tree / "docs/evidence-hardlink.json")
    index = run(tmp_path, results=(results_doc(),), evidence=(edit_evidence(gate, edit),))
    assert index.exit_code == 2
    assert row(index, gate) == (status, [reason])
    assert all(row(index, other) == ("pass", []) for other in oai.PHYSICAL_GATE_IDS if other != gate)


def test_a_record_that_vanishes_after_the_existence_check_is_not_verified(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    record = write_at(tree / "docs/vanishing-record.json", "placeholder")
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    evidence = write(tree, "evidence.json", edit_evidence(
        "adapter-direct-ad07", lambda entry: entry.update(evidence_ref=ref("docs/vanishing-record.json"))))
    original = ccm._absent_locally

    def spy(reference, root, **kwargs):
        answer = original(reference, root, **kwargs)
        if reference and reference["path"] == "docs/vanishing-record.json" and record.exists():
            record.unlink()
        return answer
    monkeypatch.setattr(ccm, "_absent_locally", spy)
    index = oai.build_index(tree, metadata, [results], [evidence])
    assert not record.exists()
    assert index.exit_code == 2
    assert row(index, "adapter-direct-ad07") == (
        "unverified", ["the linked per-row evidence record does not exist in the worktree"])


def test_each_row_needs_its_own_review(tmp_path):
    doc = evidence_doc()
    gate_entry(doc, "adapter-direct-ad07")["independent_review"] = "missing"
    index = run(tmp_path, results=(results_doc(),), evidence=(doc,))
    assert row(index, "adapter-direct-ad07") == ("unverified", ["independent review of this row's evidence is missing"])
    assert row(index, "adapter-direct-ad06") == ("pass", [])


def test_records_in_other_project_repositories_are_navigation_references(tmp_path):
    doc = edit_evidence("explorer-pi", lambda entry: entry.update(evidence_ref=ref("docs/absent.md", EXPLORER)))
    index = run(tmp_path, results=(results_doc(),), evidence=(doc,))
    assert index.exit_code == 0, index.document["blocking"]


def test_an_evidence_record_through_a_link_leaving_the_worktree_is_never_listed(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    home = tmp_path / "fakehome"
    (home / "Library/Keychains").mkdir(parents=True)
    (home / "Library/Keychains/login.db").write_text("x", encoding="utf-8")
    (tree / "docs/h").symlink_to(home)
    listed = []
    doc = edit_evidence(SINGLE, lambda entry: entry.update(evidence_ref=ref("docs/h/Library/Keychains/login.db")))
    inputs = [write(tree, "metadata.json", candidate_metadata()), write(tree, "results.json", results_doc()),
              write(tree, "evidence.json", doc)]
    listing_spy(monkeypatch, listed)
    index = check(oai.build_index(tree, inputs[0], [inputs[1]], [inputs[2]]), tmp_path)
    assert row(index, SINGLE) == ("unverified", ["the linked per-row evidence record does not exist in the worktree"])
    assert listed and identity(home) not in listed and identity(home / "Library") not in listed


@pytest.mark.parametrize("field, value, reason", [
    ("bundle_id", OTHER_BUNDLE, "only operator evidence for a different BOM was supplied"),
    ("association_id", OTHER_ASSOCIATION,
     "only operator evidence for another association of this bundle was supplied (stale)"),
    ("gate", "ha-ingress-trust", "no operator evidence was supplied"),
    ("case", "T05", None),
    ("environment", "simulated", "only simulated evidence was supplied; it cannot establish live acceptance"),
    ("independent_review", "missing", "independent review of this row's evidence is missing"),
])
def test_every_operator_evidence_key_field_must_match(tmp_path, field, value, reason):
    """Vary bundle, association, gate, case, environment and review one at a time for one range gate."""
    gate = "transport-direct-adapter"
    rest, varied = evidence_doc(gates=without(gate)), evidence_doc(gates=(gate,))
    if field == "gate":
        rest, varied = evidence_doc(gates=without(gate, value)), evidence_doc(gates=(value,))
    elif field == "case":
        gate_entry(varied, gate)["cases"][0]["case"] = value
    elif field == "independent_review":
        gate_entry(varied, gate)[field] = value
    else:
        varied[field] = value
    index = run(tmp_path, results=(results_doc(),), evidence=(rest, varied))
    if field == "case":  # T05 belongs to another gate: the record is malformed, not silently accepted.
        assert index.exit_code == 1
        assert index.document["input_errors"] == [
            f"operator evidence[1]: gates[0].cases[0].case is not a case of {gate}"]
        assert row(index, gate) == ("unverified", ["no operator evidence was supplied"])
        return
    assert index.exit_code == 2
    assert row(index, gate) == ("unverified", [reason])
    assert OTHER_BUNDLE not in text(index) and OTHER_ASSOCIATION not in text(index)


def test_more_than_one_live_record_for_a_gate_is_ambiguous(tmp_path):
    index = run(tmp_path, results=(results_doc(),), evidence=(evidence_doc(), evidence_doc(gates=("legacy-mux",))))
    assert row(index, "legacy-mux") == (
        "unverified", ["2 live operator evidence records were supplied for this gate; exactly one is required"])
    assert index.exit_code == 2


@pytest.mark.parametrize("edit, message", [
    (lambda doc: doc["gates"].__setitem__(1, copy.deepcopy(doc["gates"][0])),
     "gates[1].gate repeats transport-direct-adapter"),
    (lambda doc: doc["gates"].append(copy.deepcopy(doc["gates"][0])), "gates must not exceed 52 entries"),
    (lambda doc: doc["gates"][0]["cases"].append(dict(doc["gates"][0]["cases"][0])),
     "gates[0].cases must not exceed 4 entries"),
    (lambda doc: doc["gates"][0]["cases"].__setitem__(1, {"case": "T01", "outcome": "pass"}),
     "gates[0].cases[1].case repeats a case of transport-direct-adapter"),
    (lambda doc: doc["gates"][5]["cases"].__setitem__(0, {"case": "AD01", "outcome": "pass"}),
     "gates[5].cases[0].case is not a case of adapter-direct-ad01"),
    (lambda doc: doc["gates"][0]["cases"].__setitem__(0, {"case": 1, "outcome": "pass"}),
     "gates[0].cases[0].case is not a case of transport-direct-adapter"),
    (lambda doc: doc["gates"][0]["cases"][0].update(outcome="xpass"),
     "gates[0].cases[0].outcome must be one of pass, fail, blocked, not-run"),
    (lambda doc: doc.update(environment="replay"), "environment must be one of live, simulated"),
    (lambda doc: doc["gates"][0].update(independent_review=True),
     "gates[0].independent_review must be one of satisfied, missing"),
    (lambda doc: doc.update(independent_review="satisfied"), "document has 1 unknown field(s)"),
    (lambda doc: doc.update(gates=[]), "gates must be a nonempty array"),
    (lambda doc: doc["gates"][0].update(cases=[]), "gates[0].cases must be a nonempty array"),
    (lambda doc: doc["gates"][0].update(evidence_ref=ref("../outside.md")),
     "gates[0].evidence_ref.path must be a clean repository-relative file path"),
    (lambda doc: doc["gates"][0].pop("evidence_ref"), "gates[0] is missing evidence_ref"),
    (lambda doc: doc["gates"][0].pop("independent_review"), "gates[0] is missing independent_review"),
])
def test_operator_evidence_schema_is_strict(tmp_path, edit, message):
    doc = evidence_doc()
    edit(doc)
    index = run(tmp_path, results=(results_doc(),), evidence=(doc,))
    assert index.exit_code == 1
    assert index.document["input_errors"] == [f"operator evidence[0]: {message}"]
    assert index.document["physical"]["status"] == "incomplete"


@pytest.mark.parametrize("edit, message", [
    (lambda doc: doc.update(results=[]), "results must be a nonempty array"),
    (lambda doc: doc.update(results=doc["results"] * 17), "results must not exceed 64 entries"),
    (lambda doc: doc["results"][0].update(outcome="passed"),
     "results[0].outcome must be one of pass, fail, timeout, not-run"),
    (lambda doc: doc["results"][0].update(omitted_checks="verify-github"), "results[0].omitted_checks must be an array"),
    (lambda doc: doc["results"][0].update(omitted_checks=["Verify GitHub"]),
     "results[0].omitted_checks[0] must be a short public check name"),
    (lambda doc: doc["results"][0].update(omitted_checks=[f"pin-{COMMIT_LIKE[:8]}"]),
     "results[0].omitted_checks[0] must be a short public check name"),
    (lambda doc: doc["results"][0].update(omitted_checks=["a"] * 65),
     "results[0].omitted_checks must not exceed 64 entries"),
    (lambda doc: doc["results"][0].update(omitted_checks=["a", "a"]), "results[0].omitted_checks must not repeat values"),
    (lambda doc: doc["results"][0].update(artifact_id=f"artifact-{COMMIT_LIKE[:12]}"),
     "results[0].artifact_id embeds restricted publication data"),
    (lambda doc: doc.update(bundle_id="Bundle"), "bundle_id must be an opaque ID"),
    (lambda doc: doc.update(format="helianthus-offline-test-results/2"),
     "format must be the literal helianthus-offline-test-results/1"),
    (lambda doc: doc["results"][0].pop("omitted_checks"), "results[0] is missing omitted_checks"),
])
def test_result_manifest_schema_is_strict(tmp_path, edit, message):
    doc = results_doc()
    edit(doc)
    index = run(tmp_path, results=(doc,), evidence=(evidence_doc(),))
    assert index.exit_code == 1
    assert index.document["input_errors"] == [f"results[0]: {message}"]
    assert index.document["evidence"] == "incomplete"


@pytest.mark.parametrize("raw, message", [
    ("{", "not JSON (Expecting property name enclosed in double quotes at line 1 column 2)"),
    ('{"format": 1, "format": 2}', "duplicate key"),
    (b"\xff", "not UTF-8"),
    ("[]", "document must be an object"),
    ('{"format": NaN}', "non-finite number NaN"),
])
def test_malformed_manifests_are_unusable(tmp_path, raw, message):
    index = run(tmp_path, results=(raw,))
    assert index.exit_code == 1
    assert index.document["input_errors"] == [f"results[0]: {message}"]


def test_unknown_field_names_are_never_echoed(tmp_path):
    doc = results_doc()
    doc["results"][0]["customer-router-secret"] = True
    evidence = evidence_doc()
    evidence["site-serial-secret"] = "x"
    index = run(tmp_path, results=(doc,), evidence=(evidence,))
    assert index.document["input_errors"] == ["results[0]: results[0] has 1 unknown field(s)",
                                              "operator evidence[0]: document has 1 unknown field(s)"]
    assert "router" not in text(index) and "serial" not in text(index)


# -------------------------------------------- candidate validator reuse

def test_the_candidate_metadata_validator_is_reused_in_public_only_mode(tmp_path, monkeypatch):
    calls = []
    original = ccm.validate

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(oai.ccm, "validate", spy)
    assert complete(tmp_path).exit_code == 0
    tree = (tmp_path / "worktree").resolve()
    assert len(calls) == 1 and set(calls[0][1]) == {"metadata_bytes", "root_fd"} and calls[0][0][1] == tree


def test_metadata_swapped_after_the_check_is_never_reopened_by_path(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    original = ccm.validate

    def swap_then_validate(path, root, *args, **kwargs):
        metadata.unlink()
        os.mkfifo(metadata)  # A reopen by pathname would block here; the checked descriptor must be used.
        return original(path, root, *args, **kwargs)
    monkeypatch.setattr(oai.ccm, "validate", swap_then_validate)
    index = oai.build_index(tree, metadata, [], [])
    assert index.document["candidate"]["bundle_id"] == BUNDLE
    assert index.document["candidate"]["validator"]["exit_code"] == 0


def test_metadata_growing_after_the_size_check_is_never_read_past_the_limit(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    original = ccm.validate
    parsed = []
    strict = ccm._strict_json

    def grow_then_validate(path, root, *args, **kwargs):
        with open(metadata, "ab") as handle:
            handle.write(b" " * (oai.MAX_INPUT_BYTES + 1))
        return original(path, root, *args, **kwargs)

    def record(raw):
        parsed.append(len(raw))
        return strict(raw)
    monkeypatch.setattr(oai.ccm, "validate", grow_then_validate)
    monkeypatch.setattr(ccm, "_strict_json", record)
    oai.build_index(tree, metadata, [], [])
    assert parsed and max(parsed) <= oai.MAX_INPUT_BYTES


@pytest.mark.parametrize("relative", [relative for _, relative, _ in ccm.PACKAGE_INPUTS])
def test_every_packaging_input_is_bounded_before_parsing(tmp_path, relative):
    tree = make_worktree(tmp_path)
    packaging = tree / relative
    with packaging.open("ab") as handle:
        handle.write(b" " * (oai.MAX_INPUT_BYTES + 1))
    metadata = write(tree, "metadata.json", candidate_metadata())
    index = oai.build_index(tree, metadata, [], [])
    assert index.exit_code == 1
    assert row(index, oai.CANDIDATE_GATE) == (
        "unverified", ["the candidate metadata validator reported INPUT_UNAVAILABLE"])
    assert any("exceeds the 1 MiB input limit" in line
               for line in index.document["candidate"]["validator"]["lines"])


@pytest.mark.parametrize("relative", [relative for _, relative, _ in ccm.PACKAGE_INPUTS])
def test_each_packaging_input_is_read_once_from_one_bounded_descriptor(tmp_path, monkeypatch, relative):
    tree = make_worktree(tmp_path).resolve()
    bounds = []
    original = ccm._read_descriptor

    def spy(descriptor, limit=ccm.MAX_INPUT_BYTES):
        bounds.append(limit)
        return original(descriptor, limit)
    monkeypatch.setattr(ccm, "_read_descriptor", spy)
    outcome = ccm.validate(write(tree, "metadata.json", candidate_metadata()), tree)
    assert outcome.exit_code == 0 and outcome.metadata is not None
    assert len(bounds) == len(ccm.PACKAGE_INPUTS) + 1 and set(bounds) == {oai.MAX_INPUT_BYTES}


def test_nothing_global_is_mutated_while_the_index_validates(tmp_path, monkeypatch):
    before = {name: getattr(ccm, name) for name in dir(ccm)}
    seen = []
    original = ccm.validate

    def spy(*args, **kwargs):
        seen.append({name: getattr(ccm, name) for name in dir(ccm)})
        return original(*args, **kwargs)
    monkeypatch.setattr(oai.ccm, "validate", spy)
    assert complete(tmp_path).exit_code == 0
    monkeypatch.undo()
    assert seen and seen[0] == {**before, "validate": seen[0]["validate"]}
    assert {name: getattr(ccm, name) for name in dir(ccm)} == before
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
            node, (ast.AugAssign, ast.AnnAssign)) else []
        assert not any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                       and target.value.id == "ccm" for target in targets)


def test_the_index_never_reads_packaging_files_itself():
    source = SCRIPT.read_text(encoding="utf-8")
    for owned_by_the_validator in ["build.yml", "test-image", "Dockerfile", "config.json", "bom.json", "yaml",
                                   "_match_build_workflow", "CANONICAL_BUILD_WORKFLOW", "check_release_cohort"]:
        assert owned_by_the_validator not in source, owned_by_the_validator


def test_an_unrecognised_packaging_shape_blocks_the_index(tmp_path):
    make_worktree(tmp_path, build_edit=lambda build: build.replace("jobs:\n", "# extra\njobs:\n", 1))
    index = complete(tmp_path)
    assert index.exit_code == 2
    status, reasons = row(index, oai.CANDIDATE_GATE)
    assert status == "unverified" and len(reasons) == 1
    assert reasons[0].startswith("unmet candidate prerequisite: unrecognised packaging shape: build workflow does "
                                 "not match the canonical workflow triggers, permissions and image environment")
    assert index.document["evidence"] == "incomplete"
    assert all(found["status"] == "pass" for gate, found in rows(index).items() if gate != oai.CANDIDATE_GATE)


def setpath(doc: dict, path: tuple, value) -> dict:
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return doc


@pytest.mark.parametrize("edits, reasons", [
    ([(("kind",), "preparatory")], ["kind is preparatory; preparation alone never means accepted"]),
    ([(("exact_bom", "status"), "unverified"), (("exact_bom", "attestation_id"), None)], ["exact_bom is unverified"]),
    ([(("output_binding", "status"), "partial")], ["output_binding is partial"]),
    ([(("components", "gateway", "release_label"), None)], ["components.gateway.release_label is unavailable"]),
    ([(("components", "explorer", "public_ref"), None)], ["components.explorer.public_ref is unavailable"]),
    ([(("acceptance", "Portal", "status"), "rejected")], ["acceptance.Portal is rejected"]),
    ([(("architectures",), ["aarch64", "amd64"])],
     ["architectures differ from the set the build workflow publishes under the version tag"]),
    ([(("components", "addon", "public_ref"), ref("docs/absent.md"))],
     ["components.addon.public_ref does not exist in the provisioned package"]),
])
def test_unmet_candidate_prerequisites_other_than_pending_acceptance_block_the_index(tmp_path, edits, reasons):
    meta = candidate_metadata()
    for path, value in edits:
        setpath(meta, path, value)
    index = complete(tmp_path, meta)
    assert index.exit_code == 2
    assert row(index, oai.CANDIDATE_GATE) == ("unverified", [f"unmet candidate prerequisite: {r}" for r in reasons])


def test_an_unfrozen_bom_blocks_the_index(tmp_path):
    make_worktree(tmp_path, freeze={"owner": "INT-16", "status": "unfrozen"})
    index = complete(tmp_path)
    assert row(index, oai.CANDIDATE_GATE) == (
        "unverified", ["unmet candidate prerequisite: helianthus/bom.json is not frozen by INT-16"])
    assert index.exit_code == 2


def test_only_pending_acceptance_is_tolerated(tmp_path):
    tree = make_worktree(tmp_path)
    outcome = ccm.validate(write(tree, "metadata.json", candidate_metadata()), tree)
    assert outcome.exit_code == 0
    assert outcome.public_reasons == oai.PENDING_ACCEPTANCE
    assert len(oai.PENDING_ACCEPTANCE) == len(ccm.ACCEPTANCE_KEYS) == 6


def test_a_fully_accepted_candidate_claiming_not_ready_is_usable(tmp_path):
    meta = candidate_metadata()
    meta["acceptance"] = {key: {"status": "accepted", "association_id": ASSOCIATION, "evidence_ref": ref(EVIDENCE)}
                          for key in ccm.ACCEPTANCE_KEYS}
    index = complete(tmp_path, meta)
    assert index.exit_code == 0, index.document["blocking"]
    assert index.document["candidate"]["validator"]["derived_disposition"] == "not-ready"


@pytest.mark.parametrize("edit, status, reason", [
    (lambda meta: meta.update(disposition="ready-for-review"), "fail",
     "the candidate metadata validator reported DISPOSITION_MISMATCH"),
    (lambda meta: setpath(meta, ("components", "addon", "release_label"), "0.7.5"), "fail",
     "the candidate metadata validator reported METADATA_CONFLICT"),
    (lambda meta: (meta.update(disposition="ready-for-review"), meta.update(acceptance={
        key: {"status": "accepted", "association_id": ASSOCIATION, "evidence_ref": ref(EVIDENCE)}
        for key in ccm.ACCEPTANCE_KEYS})), "unverified",
     "the candidate metadata validator reported PRIVATE_EVIDENCE_REQUIRED"),
])
def test_a_candidate_the_validator_does_not_return_valid_for_joins_nothing(tmp_path, edit, status, reason):
    meta = candidate_metadata()
    edit(meta)
    index = complete(tmp_path, meta)
    assert index.exit_code == 1
    assert row(index, oai.CANDIDATE_GATE) == (status, [reason])
    assert index.document["candidate"]["bundle_id"] == BUNDLE
    for gate in oai.SOFTWARE_GATE_IDS + oai.PHYSICAL_GATE_IDS:
        assert row(index, gate) == UNESTABLISHED


def test_invalid_metadata_establishes_no_identity(tmp_path):
    meta = candidate_metadata()
    meta["customer-router-secret"] = 1
    index = complete(tmp_path, meta)
    assert index.exit_code == 1
    assert row(index, oai.CANDIDATE_GATE) == ("fail", ["the candidate metadata validator reported INVALID_DOCUMENT"])
    candidate = index.document["candidate"]
    assert (candidate["bundle_id"], candidate["association_id"], candidate["kind"]) == (None, None, None)
    assert candidate["validator"]["lines"] == ["INVALID_DOCUMENT: metadata: document has 1 unknown field(s)"]
    for gate in oai.SOFTWARE_GATE_IDS + oai.PHYSICAL_GATE_IDS:
        assert row(index, gate) == UNESTABLISHED
    assert "router" not in text(index)


@pytest.mark.parametrize("break_input, line", [
    (lambda tree: (tree / "helianthus/bom.json").unlink(),
     "INPUT_UNAVAILABLE: package input helianthus/bom.json cannot be read (No such file or directory)"),
    (lambda tree: ((tree / "helianthus/bom.json").unlink(), os.mkfifo(tree / "helianthus/bom.json")),
     "INPUT_UNAVAILABLE: package input helianthus/bom.json is not a regular file"),
])
def test_unavailable_packaging_input_leaves_the_candidate_unverified_without_hanging(tmp_path, break_input, line):
    break_input(make_worktree(tmp_path))
    index = complete(tmp_path)
    assert index.exit_code == 1
    assert row(index, oai.CANDIDATE_GATE) == ("unverified",
                                              ["the candidate metadata validator reported INPUT_UNAVAILABLE"])
    assert index.document["candidate"]["validator"]["lines"][0] == line
    assert row(index, SINGLE) == UNESTABLISHED


def test_validator_outcome_exposes_validated_metadata_and_public_reasons(tmp_path):
    tree = make_worktree(tmp_path)
    meta = candidate_metadata()
    outcome = ccm.validate(write(tree, "metadata.json", meta), tree)
    assert outcome.metadata == meta
    meta["kind"] = "preparatory"
    outcome = ccm.validate(write(tree, "metadata.json", meta), tree)
    assert outcome.public_reasons[0] == "kind is preparatory; preparation alone never means accepted"
    outcome = ccm.validate(write(tree, "metadata.json", "{}"), tree)
    assert outcome.metadata is None and outcome.exit_code == 1


def test_the_validator_never_lists_a_directory_outside_the_checkout(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    (tmp_path / "fakehome/secret").mkdir(parents=True)
    (tree / "docs/h").symlink_to(tmp_path / "fakehome")
    listed = []
    listing_spy(monkeypatch, listed)
    assert ccm._absent_locally(ref("docs/h/secret/x.md"), tree) is True
    assert listed and identity(tmp_path / "fakehome") not in listed and identity(tmp_path / "fakehome/secret") not in listed
    assert ccm._absent_locally(ref(EVIDENCE), tree) is False


def link_tree(tmp_path: Path) -> Path:
    tree = make_worktree(tmp_path)
    (tree / "real/Sub").mkdir(parents=True)
    (tree / "real/Sub/x.md").write_text("x", encoding="utf-8")
    (tree / "real/Name.md").write_text("x", encoding="utf-8")
    (tree / "docs/h").symlink_to(tree / "real")
    return tree


def test_references_keep_the_exact_case_below_a_followed_link(tmp_path, monkeypatch):
    tree = link_tree(tmp_path)
    listed = []
    listing_spy(monkeypatch, listed)
    assert ccm._absent_locally(ref("docs/h/Sub/x.md"), tree) is False
    for below in (identity(tree / "real"), identity(tree / "real/Sub")):
        assert below in listed
    assert not {identity(tmp_path), identity(tmp_path.parent)} & set(listed)
    assert ccm._absent_locally(ref("docs/h/sub/x.md"), tree) is True
    assert ccm._absent_locally(ref("docs/h/Sub/X.md"), tree) is True


def test_exact_case_holds_through_chained_links_and_file_links(tmp_path):
    tree = link_tree(tmp_path)
    (tree / "docs/h2").symlink_to(tree / "docs/h")
    (tree / "docs/file.md").symlink_to(tree / "real/Name.md")
    (tree / "docs/wrong.md").symlink_to(tree / "real/name.md")
    assert ccm._absent_locally(ref("docs/h2/Sub/x.md"), tree) is False
    assert ccm._absent_locally(ref("docs/h2/sub/x.md"), tree) is True
    assert ccm._absent_locally(ref("docs/h2/Sub/X.md"), tree) is True
    assert ccm._absent_locally(ref("docs/file.md"), tree) is False
    assert ccm._absent_locally(ref("docs/wrong.md"), tree) is True


def test_a_wrong_case_segment_between_a_link_and_a_final_link_is_absent(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    (tree / "real/Sub").mkdir(parents=True)
    (tree / "elsewhere").mkdir()
    (tree / "elsewhere/target.md").write_text("x", encoding="utf-8")
    (tree / "real/Sub/link.md").symlink_to(tree / "elsewhere/target.md")
    (tree / "docs/h").symlink_to(tree / "real")
    listed = []
    listing_spy(monkeypatch, listed)
    assert ccm._absent_locally(ref("docs/h/Sub/link.md"), tree) is False
    assert identity(tree / "real") in listed
    assert identity(tmp_path) not in listed and identity(tmp_path.parent) not in listed
    assert ccm._absent_locally(ref("docs/h/sub/link.md"), tree) is True


def test_a_wrong_case_segment_between_two_links_in_a_chain_is_absent(tmp_path):
    tree = make_worktree(tmp_path)
    (tree / "b/Dir").mkdir(parents=True)
    (tree / "d").mkdir()
    (tree / "d/f.md").write_text("x", encoding="utf-8")
    (tree / "b/Dir/c").symlink_to(tree / "d")
    (tree / "a").symlink_to(tree / "b")
    assert ccm._absent_locally(ref("a/Dir/c/f.md"), tree) is False
    assert ccm._absent_locally(ref("a/dir/c/f.md"), tree) is True


def test_a_wrong_case_after_the_last_link_or_in_a_link_name_is_absent(tmp_path):
    tree = make_worktree(tmp_path)
    (tree / "real/Sub").mkdir(parents=True)
    (tree / "real/Sub/Name.md").write_text("x", encoding="utf-8")
    (tree / "docs/h").symlink_to(tree / "real")
    (tree / "docs/Link.md").symlink_to(tree / "real/Sub/Name.md")
    assert ccm._absent_locally(ref("docs/h/Sub/Name.md"), tree) is False
    assert ccm._absent_locally(ref("docs/h/Sub/name.md"), tree) is True
    assert ccm._absent_locally(ref("docs/Link.md"), tree) is False
    assert ccm._absent_locally(ref("docs/link.md"), tree) is True
    assert ccm._absent_locally(ref("docs/H/Sub/Name.md"), tree) is True


def test_restricted_text_from_the_validator_is_redacted(tmp_path, monkeypatch):
    def leaky(metadata, package_root, **kwargs):
        return ccm.Outcome(0, "not-ready", ["VALID: not-ready", f"K25: pin {COMMIT_LIKE}", ccm.NOTE],
                           candidate_metadata(), oai.PENDING_ACCEPTANCE + (f"pin {COMMIT_LIKE} differs",))
    monkeypatch.setattr(oai.ccm, "validate", leaky)
    index = complete(tmp_path)
    assert index.document["candidate"]["validator"]["lines"] == ["VALID: not-ready", "K25: pin <redacted>"]
    assert row(index, oai.CANDIDATE_GATE) == ("unverified", ["unmet candidate prerequisite: pin <redacted> differs"])



# ---------------------------------- descriptor-bound input handling

FORBIDDEN_PATH_READS = ("read_bytes", "read_text", "is_file", "iterdir")


def refuse_path_reads(monkeypatch, tree: Path) -> None:
    for name in FORBIDDEN_PATH_READS:
        original = getattr(Path, name)

        def guard(self, *args, _original=original, _name=name, **kwargs):
            if Path(os.path.abspath(self)).is_relative_to(tree) or not Path(self).is_absolute():
                raise AssertionError(f"Path.{_name} used on a checkout path")
            return _original(self, *args, **kwargs)
        monkeypatch.setattr(Path, name, guard)


def test_packaging_inputs_and_listings_never_use_path_reads(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    evidence = write(tree, "evidence.json", evidence_doc())
    refuse_path_reads(monkeypatch, tree)
    outcome = ccm.validate(metadata, tree)
    assert outcome.exit_code == 0, outcome.lines
    index = oai.build_index(tree, metadata, [results], [evidence])
    assert index.exit_code == 0, index.document["blocking"]


def test_every_checkout_open_is_no_follow_and_files_are_non_blocking(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    evidence = write(tree, "evidence.json", evidence_doc())
    opened = []
    original = os.open

    def spy(path, flags, *args, **kwargs):
        opened.append((os.fsdecode(path), flags, kwargs.get("dir_fd")))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    index = oai.build_index(tree, metadata, [results], [evidence])
    assert index.exit_code == 0, index.document["blocking"]
    assert opened
    for path, flags, dir_fd in opened:
        assert flags & os.O_NOFOLLOW, path
        if not flags & os.O_DIRECTORY:
            assert flags & os.O_NONBLOCK, path
    opened_names = {Path(path).name for path, _, _ in opened}
    assert {"build.yml", "test-image.yml", "bom.json", "config.json", "Dockerfile", "metadata.json",
            "results.json", "evidence.json", "synthetic-evidence.md"} <= opened_names
    assert all(dir_fd is not None for path, _, dir_fd in opened if os.sep not in path.strip(os.sep)
               and path not in ("",) and not Path(path).is_absolute())


class Hang(Exception):
    pass


def swap_at_open(monkeypatch, victim: Path, swap) -> None:
    """Run swap() just before the first os.open whose final component is victim's name."""
    original = os.open
    done = []

    def spy(path, flags, *args, **kwargs):
        if not done and Path(os.fsdecode(path)).name == victim.name:
            done.append(True)
            swap()
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)


def alarm(seconds: int = 5):
    import signal

    def handler(signum, frame):
        raise Hang("blocked")
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    return signal


@pytest.mark.parametrize("kind", ["fifo", "link"])
def test_a_packaging_input_swapped_before_the_open_is_never_followed(tmp_path, monkeypatch, kind):
    tree = make_worktree(tmp_path).resolve()
    victim = tree / "helianthus/bom.json"
    outside = tmp_path / "outside.json"
    outside.write_text(victim.read_text(encoding="utf-8"), encoding="utf-8")
    metadata = write(tree, "metadata.json", candidate_metadata())

    def swap():
        victim.unlink()
        if kind == "fifo":
            os.mkfifo(victim)
        else:
            victim.symlink_to(outside)
    swap_at_open(monkeypatch, victim, swap)
    signal = alarm()
    try:
        outcome = ccm.validate(metadata, tree)
    finally:
        signal.alarm(0)
    expected = ("is not a regular file" if kind == "fifo" else "cannot be read")
    assert outcome.exit_code == 2
    assert any(line.startswith("INPUT_UNAVAILABLE: package input helianthus/bom.json") and expected in line
               for line in outcome.lines), outcome.lines


def test_a_packaging_directory_swapped_for_a_link_is_never_followed(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    directory = tree / "helianthus"
    metadata = write(tree, "metadata.json", candidate_metadata())
    holder = tmp_path / "moved"

    def swap():
        directory.rename(holder)
        directory.symlink_to(holder)
    swap_at_open(monkeypatch, directory, swap)
    outcome = ccm.validate(metadata, tree)
    assert outcome.exit_code == 2
    assert any(line.startswith("INPUT_UNAVAILABLE: package input helianthus/config.json cannot be read")
               for line in outcome.lines), outcome.lines


def test_a_listed_directory_swapped_for_a_link_is_never_listed(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    (tree / "docs/h").mkdir()
    (tree / "docs/h/x.md").write_text("x\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text("outside\n", encoding="utf-8")
    original = os.open

    def spy(path, flags, *args, **kwargs):
        if os.fsdecode(path) == "h" and kwargs.get("dir_fd") is not None:
            (tree / "docs/h").rename(tmp_path / "held")
            (tree / "docs/h").symlink_to(outside)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    listed = []
    listing_spy(monkeypatch, listed)
    assert ccm._absent_locally(ref("docs/h/x.md"), tree) is True
    assert identity(outside) not in listed


def test_a_metadata_ancestor_swapped_for_a_link_reads_nothing_outside(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    write_at(outside / "metadata.json", candidate_metadata())
    metadata = write(tree, "metadata.json", {"format": "x"})
    original = os.open
    swapped = []

    def spy(path, flags, *args, **kwargs):
        if os.fsdecode(path) == "acceptance" and not swapped:
            swapped.append(True)
            (tree / "acceptance").rename(tmp_path / "held")
            (tree / "acceptance").symlink_to(outside)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    index = oai.build_index(tree, metadata, [], [])
    assert swapped
    assert index.document["candidate"]["bundle_id"] is None
    assert index.exit_code == 1
    assert index.document["input_errors"] and index.document["input_errors"][0].startswith("metadata cannot be read")


def test_input_identity_comes_from_the_descriptor_that_was_read(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    metadata = write(tree, "metadata.json", candidate_metadata())
    first = write(tree, "results-a.json", results_doc())
    second = write(tree, "results-b.json", results_doc())
    other = write(tree, "other.json", results_doc())

    def swap():  # After the path was resolved, the name now holds the inode of another supplied input.
        first.unlink()
        os.link(second, first)
    swap_at_open(monkeypatch, first, swap)
    index = oai.build_index(tree, metadata, [first, second], [])
    assert other.exists()
    assert index.document["input_errors"] == ["results[1] repeats an input that was already supplied"]


def test_concurrent_builds_keep_their_own_candidates_and_mutate_nothing(tmp_path, monkeypatch):
    import threading
    first = make_worktree(tmp_path / "one").resolve()
    second_meta = json.loads(json.dumps(candidate_metadata()).replace(BUNDLE, "bundle-synthetic-second")
                             .replace(ASSOCIATION, "association-synthetic-second"))
    second = make_worktree(tmp_path / "two").resolve()
    first_path = write(first, "metadata.json", candidate_metadata())
    second_path = write(second, "metadata.json", second_meta)
    barrier = threading.Barrier(2, timeout=10)
    seen = []
    load, package = ccm._load, ccm._read_package
    original = ccm._read_descriptor
    waited = threading.local()

    def spy(descriptor, limit=ccm.MAX_INPUT_BYTES):
        if not getattr(waited, "done", False):
            waited.done = True
            seen.append((ccm._load is load, ccm._read_package is package))
            barrier.wait()
        return original(descriptor, limit)
    monkeypatch.setattr(ccm, "_read_descriptor", spy)
    outcomes = {}

    def build(key, tree, metadata):
        outcomes[key] = oai.build_index(tree, metadata, [], [])
    threads = [threading.Thread(target=build, args=("one", first, first_path)),
               threading.Thread(target=build, args=("two", second, second_path))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert seen == [(True, True), (True, True)]
    assert outcomes["one"].document["candidate"]["bundle_id"] == BUNDLE
    assert outcomes["two"].document["candidate"]["bundle_id"] == "bundle-synthetic-second"
    assert ccm._load is load and ccm._read_package is package


# ------------------------------------------------- explicit local inputs

def test_inputs_outside_the_worktree_are_refused_without_echoing_paths(tmp_path):
    tree = make_worktree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "metadata.json").write_text(json.dumps(candidate_metadata()), encoding="utf-8")
    (outside / "results.json").write_text(json.dumps(results_doc()), encoding="utf-8")
    (tree / "acceptance/linked.json").symlink_to(outside / "results.json")
    escape = tree / "acceptance" / ".." / ".." / "outside" / "results.json"
    index = check(oai.build_index(tree, outside / "metadata.json",
                                  [tree / "acceptance/linked.json", escape, tree], []), tmp_path)
    assert index.exit_code == 1
    assert index.document["input_errors"] == [
        "metadata is not a file inside the worktree",
        "results[0] is not a file inside the worktree",
        "results[1] is not a file inside the worktree",
        "results[2] is not a file inside the worktree",
    ]
    assert index.document["candidate"]["validator"] is None
    assert row(index, oai.CANDIDATE_GATE) == ("unverified", ["the candidate metadata was not validated"])


def test_a_link_inside_the_worktree_to_a_worktree_file_is_accepted(tmp_path):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    (tree / "docs/results-link.json").symlink_to(results)
    index = check(oai.build_index(tree, metadata, [tree / "docs/results-link.json"], []), tmp_path)
    assert index.exit_code == 2 and index.document["software"]["status"] == "complete"


@pytest.mark.parametrize("make, message", [
    (lambda tree: tree / "acceptance", "is not a regular file"),
    (lambda tree: tree / "absent.json", "cannot be read"),
    (lambda tree: (tree / ".git").mkdir() or write_at(tree / ".git/results.json", results_doc()),
     "is inside repository metadata"),
    (lambda tree: write_at(tree / "acceptance/big.json", b" " * (oai.MAX_INPUT_BYTES + 1)),
     "exceeds the 1 MiB input limit"),
    (lambda tree: os.mkfifo(tree / "acceptance/pipe") or tree / "acceptance/pipe", "is not a regular file"),
    (lambda tree: Path(str(tree / "acceptance/nul") + "\0.json"), "cannot be read"),
])
def test_unusable_result_inputs_are_named_by_role(tmp_path, make, message):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    index = check(oai.build_index(tree, metadata, [make(tree)], []), tmp_path)
    assert index.exit_code == 1
    assert index.document["input_errors"] == [f"results[0] {message}"]


@pytest.mark.parametrize("make, message", [
    (lambda tree: write_at(tree / "acceptance/metadata.json", json.dumps(candidate_metadata()) + " " * oai.MAX_INPUT_BYTES),
     "metadata exceeds the 1 MiB input limit"),
    (lambda tree: os.mkfifo(tree / "acceptance/metadata-pipe") or tree / "acceptance/metadata-pipe",
     "metadata is not a regular file"),
])
def test_metadata_is_checked_before_the_validator_reads_it(tmp_path, monkeypatch, make, message):
    tree = make_worktree(tmp_path)

    def never(*args, **kwargs):
        raise AssertionError("the validator must not read an unusable metadata input")
    monkeypatch.setattr(oai.ccm, "validate", never)
    index = check(oai.build_index(tree, make(tree), [], []), tmp_path)
    assert index.document["input_errors"] == [message]
    assert index.document["candidate"]["validator"] is None
    assert index.exit_code == 1


def test_an_input_exactly_at_the_size_limit_is_read(tmp_path):
    tree = make_worktree(tmp_path)
    raw = json.dumps(results_doc())
    padded = raw + " " * (oai.MAX_INPUT_BYTES - len(raw))
    assert len(padded.encode("utf-8")) == oai.MAX_INPUT_BYTES
    index = check(oai.build_index(tree, write(tree, "metadata.json", candidate_metadata()),
                                  [write(tree, "padded.json", padded)], []), tmp_path)
    assert index.document["input_errors"] == []


def test_repeated_and_excess_inputs_are_refused(tmp_path):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    os.link(results, tree / "docs/results-hardlink.json")
    index = check(oai.build_index(tree, metadata, [results, results, metadata, tree / "docs/results-hardlink.json"],
                                  []), tmp_path)
    assert index.document["input_errors"] == ["results[1] repeats an input that was already supplied",
                                              "results[2] repeats an input that was already supplied",
                                              "results[3] repeats an input that was already supplied"]
    assert index.exit_code == 1
    many = [write(tree, f"many-{number}.json", results_doc()) for number in range(oai.MAX_RESULT_FILES + 1)]
    index = check(oai.build_index(tree, metadata, many, many[:oai.MAX_EVIDENCE_FILES + 1]), tmp_path)
    assert index.document["input_errors"] == ["at most 16 results files may be supplied",
                                              "at most 16 operator evidence files may be supplied"]
    assert index.exit_code == 1


def test_an_unreadable_package_root_is_refused(tmp_path):
    for root in (tmp_path / "absent", Path(str(tmp_path) + "\0")):
        index = check(oai.build_index(root, tmp_path / "absent/metadata.json", [tmp_path / "absent/results.json"],
                                      []), tmp_path)
        assert index.exit_code == 1
        assert index.document["input_errors"] == ["package root is not a readable directory"]


def test_a_home_relative_path_is_never_expanded(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path)
    monkeypatch.chdir(tree)
    index = check(oai.build_index(tree, Path("~/metadata.json"), [], []), tmp_path)
    assert index.document["input_errors"] == ["metadata cannot be read"]


# ---------------------------------------------- offline and read-only

def test_the_builder_imports_and_calls_nothing_that_executes_writes_or_enumerates():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "argparse", "dataclasses", "json", "os", "pathlib", "re", "stat", "sys",
                        "typing", "check_candidate_metadata"}
    os_uses = {node.attr for node in ast.walk(tree)
               if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os"}
    assert os_uses <= {"open", "fstat", "stat", "read", "close", "O_RDONLY", "O_NONBLOCK", "O_NOFOLLOW"}, os_uses
    forbidden = {"open", "write", "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace", "rmdir",
                 "touch", "chmod", "symlink_to", "hardlink_to", "expanduser", "home", "getenv", "environ",
                 "iterdir", "glob", "rglob", "listdir", "scandir", "walk", "system", "popen", "exec", "eval",
                 "__import__", "getattr"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            is_os_open = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "os"
            assert called not in forbidden or (called == "open" and is_os_open), called


def test_building_the_index_opens_no_socket_process_or_home_directory(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path).resolve()
    inside = {identity(path) for path in [tree, *tree.rglob("*")] if path.is_dir()}
    listed = []

    def refuse(*args, **kwargs):
        raise AssertionError("network, process, home or enumeration access attempted")
    for owner, name in [(socket, "socket"), (socket, "create_connection"), (subprocess, "Popen"), (os, "system"),
                        (os, "execv"), (os, "walk"), (Path, "home"), (Path, "expanduser"), (Path, "glob"),
                        (Path, "rglob"), (os.path, "expanduser")]:
        monkeypatch.setattr(owner, name, refuse)
    listing_spy(monkeypatch, listed)
    metadata = write(tree, "metadata.json", candidate_metadata())
    index = oai.build_index(tree, metadata, [write(tree, "results.json", results_doc())],
                            [write(tree, "evidence.json", evidence_doc())])
    assert index.exit_code == 0, index.document["blocking"]
    assert listed and set(listed) <= inside, "only worktree entries are looked up"


def test_the_real_package_is_never_a_usable_candidate(tmp_path):
    """This checkout's unmodified packaging is 0.6.x and pins exact revisions; none may leak or be joined."""
    tree = tmp_path / "worktree"
    for relative in ("helianthus/config.json", "helianthus/Dockerfile", "helianthus/bom.json",
                     ".github/workflows/build.yml", ".github/workflows/test-image.yml", "RELEASE_COHORT.md"):
        (tree / relative).parent.mkdir(parents=True, exist_ok=True)
        (tree / relative).write_bytes((ROOT / relative).read_bytes())
    (tree / "acceptance").mkdir()
    (tree / "docs").mkdir()
    (tree / EVIDENCE).write_text("synthetic\n", encoding="utf-8")
    index = complete(tmp_path)
    assert index.exit_code == 1
    assert row(index, oai.CANDIDATE_GATE) == ("fail", ["the candidate metadata validator reported METADATA_CONFLICT"])
    assert ("METADATA_CONFLICT: provisioned add-on version is outside the 0.7 cohort"
            in index.document["candidate"]["validator"]["lines"])
    pins = re.findall(r"[0-9a-f]{40}", (ROOT / "helianthus/Dockerfile").read_text(encoding="utf-8"))
    assert pins and not any(pin[:7] in text(index) for pin in pins)


# ------------------------------------------------------------ catalogue

def test_physical_gates_mirror_the_consolidated_handoff_rows():
    cases = oai.CASES
    ranges = [gate for gate, _ in oai.RANGE_GATES]
    assert ranges == ["transport-direct-adapter", "transport-ebusd-tcp", "transport-proxy-single-client",
                      "transport-proxy-dual-client", "proxy-semantics-adjunct"]
    transport = [case for gate in ranges[:4] for case in cases[gate]]
    assert transport == [f"T{number:02d}" for number in range(1, 89)]
    assert [len(cases[gate]) for gate in ranges[:4]] == [4, 4, 16, 64]
    assert cases["proxy-semantics-adjunct"] == tuple(f"PX{number:02d}" for number in range(1, 13))
    expected_rows = ([f"adapter-direct-ad{number:02d}" for number in range(1, 13)]
                     + [f"passive-smoke-p{number:02d}" for number in range(1, 7)]
                     + ["esera-passive-boundary"]
                     + [f"legacy-persist-p{number}" for number in range(1, 7)]
                     + [f"legacy-persist-n{number}" for number in range(1, 5)]
                     + [f"legacy-identity-p{number}" for number in range(1, 7)]
                     + [f"legacy-identity-n{number}" for number in range(1, 6)]
                     + ["legacy-mux", "ha-ingress-routing", "ha-ingress-trust", "ha-ingress-lifecycle",
                        "explorer-pi", "eebus-output-binding", "matter-output-binding"])
    assert list(oai.ROW_GATES) == expected_rows
    assert all(cases[gate] == (gate,) for gate in expected_rows)
    assert list(oai.PHYSICAL_GATE_IDS) == ranges + expected_rows
    assert len(oai.PHYSICAL_GATE_IDS) == len(set(oai.PHYSICAL_GATE_IDS)) == 52
    assert sum(len(gate_cases) for _, gate_cases in oai.PHYSICAL_GATES) == 147
    assert not any("rtu" in gate for gate in oai.PHYSICAL_GATE_IDS), "historical RTU evidence is never a live row"
    assert all(ccm.OPAQUE_ID.fullmatch(gate) for gate in oai.PHYSICAL_GATE_IDS)


def test_software_gates_cover_each_named_component_once():
    assert [component for _, component in oai.SOFTWARE_GATES] == list(ccm.COMPONENT_KEYS)
    assert oai.CANDIDATE_GATE not in oai.SOFTWARE_GATE_IDS
    assert not set(oai.SOFTWARE_GATE_IDS) & set(oai.PHYSICAL_GATE_IDS)


def test_the_companion_page_documents_the_catalogue_and_formats():
    page = DOC.read_text(encoding="utf-8")
    for literal in [oai.INDEX_FORMAT, oai.RESULTS_FORMAT, oai.EVIDENCE_FORMAT, oai.CANDIDATE_GATE,
                    *oai.SOFTWARE_GATE_IDS, *oai.OUTCOMES, *oai.CASE_OUTCOMES, *oai.ENVIRONMENTS,
                    *oai.REVIEW_VALUES, *(gate for gate, _ in oai.RANGE_GATES)]:
        assert f"`{literal}`" in page, literal
    for gate, gate_cases in oai.RANGE_GATES:
        assert f"| `{gate}` |" in page and f"`{gate_cases[0]}`–`{gate_cases[-1]}`" in page, gate
    families = {}
    for gate in oai.ROW_GATES:
        family = re.sub(r"-[pn]?\d+$|-ad\d+$", "", gate) if re.search(r"\d$", gate) else gate
        families.setdefault(family, []).append(gate)
    for family, gates in families.items():
        assert f"`{gates[0]}`" in page and f"`{gates[-1]}`" in page, family
    for statement in ["1 MiB", "At most 16", "Project-Helianthus repository", "promotes no disposition",
                      "PRIVATE_EVIDENCE_REQUIRED", "pending"]:
        assert statement in page, statement
    assert oai.MAX_INPUT_BYTES == 1 << 20 and oai.MAX_RESULT_FILES == oai.MAX_EVIDENCE_FILES == 16


def test_required_gate_registers_the_tests_once_after_the_validator():
    gate = (ROOT / "scripts/ci_local.sh").read_text(encoding="utf-8")
    assert gate.count("tests/test_offline_acceptance_index.py") == 1
    assert gate.count("tests/test_candidate_metadata.py") == 1
    validator = gate.index("python3 -m pytest -q tests/test_candidate_metadata.py\n")
    assert validator < gate.index("python3 -m pytest -q tests/test_offline_acceptance_index.py\n")


# ------------------------------------------------------------------ CLI

def test_cli_prints_the_index_and_exits(tmp_path):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    evidence = write(tree, "evidence.json", evidence_doc())
    base = [sys.executable, str(SCRIPT), "--package-root", str(tree), "--metadata", str(metadata),
            "--results", str(results)]
    done = subprocess.run(base + ["--operator-evidence", str(evidence)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["evidence"] == "complete"
    done = subprocess.run(base, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    assert json.loads(done.stdout)["physical"]["status"] == "incomplete"
    assert str(tmp_path) not in done.stdout
    done = subprocess.run([sys.executable, str(SCRIPT), "--metadata", str(metadata)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    assert "--package-root" in done.stderr and done.stdout == ""


def test_help_documents_usage_and_limits():
    done = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60,
                          env={**os.environ, "COLUMNS": "2000"})
    assert done.returncode == 0
    help_text = " ".join(done.stdout.split())
    for expected in ["--package-root", "--metadata", "--results", "--operator-evidence", oai.INDEX_FORMAT,
                     "Exit 0", "Exit 1", "Exit 2", "different-BOM", "timed-out", "omitted-check",
                     "simulated evidence never upgrades", "public-only", "promotes no disposition",
                     "no execution", "listing outside the worktree", "hardware qualification"]:
        assert expected in help_text, expected


PRIVATE_PATH = "/private/operator-records/customer-secret.json"


def test_usage_errors_never_echo_option_text_or_values(tmp_path, capsys):
    tree = make_worktree(tmp_path)
    metadata = write(tree, "metadata.json", candidate_metadata())
    good = ["--package-root", str(tree), "--metadata", str(metadata)]
    cases = [
        good + ["--results-file", PRIVATE_PATH],
        ["--metadata", str(metadata)],
        good + ["--results", PRIVATE_PATH + "-x", "--bogus-option"],
    ]
    for argv in cases:
        with pytest.raises(SystemExit) as raised:
            oai.main(argv)
        assert raised.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        for text in (captured.err, captured.out):
            assert PRIVATE_PATH not in text and "results-file" not in text and "bogus" not in text
            assert str(tmp_path) not in text
        assert "the command line cannot be used" in captured.err
        done = subprocess.run([sys.executable, str(SCRIPT)] + argv, capture_output=True, text=True, timeout=60)
        assert done.returncode == 1
        assert done.stdout == ""
        for text in (done.stderr, done.stdout):
            assert PRIVATE_PATH not in text and "results-file" not in text and "bogus" not in text
            assert str(tmp_path) not in text
        assert "the command line cannot be used" in done.stderr


# ------------------------------------------------ one record per physical gate

SHARED = "the linked per-row evidence record is also linked from another gate; each gate needs its own record"
FIRST, SECOND = "adapter-direct-ad01", "adapter-direct-ad02"


def shared_run(tmp_path: Path, links: dict, prepare=None, edit=None) -> oai.Index:
    tree = make_worktree(tmp_path)
    if prepare:
        prepare(tree)
    doc = evidence_doc()
    for gate, reference in links.items():
        gate_entry(doc, gate)["evidence_ref"] = reference
    if edit:
        edit(doc)
    return run(tmp_path, results=(results_doc(),), evidence=(doc,), tree=tree)


def only_shared(index: oai.Index, *gates: str) -> None:
    for gate, found in rows(index).items():
        if gate in gates:
            assert (found["status"], found["reasons"]) == ("unverified", [SHARED]), gate
        else:
            assert (found["status"], found["reasons"]) == ("pass", []), gate


def test_two_gates_linked_to_one_record_are_both_unverified(tmp_path):
    index = shared_run(tmp_path, {SECOND: ref(record(FIRST))})
    assert index.exit_code == 2
    only_shared(index, FIRST, SECOND)


def test_one_record_for_every_gate_passes_no_row(tmp_path):
    index = shared_run(tmp_path, {gate: ref(EVIDENCE) for gate in oai.PHYSICAL_GATE_IDS})
    assert index.exit_code == 2
    only_shared(index, *oai.PHYSICAL_GATE_IDS)


def test_a_hard_link_to_the_same_record_is_the_same_record(tmp_path):
    index = shared_run(tmp_path, {SECOND: ref("docs/alias.md")},
                       prepare=lambda tree: os.link(tree / record(FIRST), tree / "docs/alias.md"))
    only_shared(index, FIRST, SECOND)


def test_a_symlink_to_the_same_record_is_the_same_record(tmp_path):
    def prepare(tree):
        try:
            (tree / "docs/alias.md").symlink_to(Path("records") / f"{FIRST}.md")
        except OSError:
            pytest.skip("this platform cannot create symlinks")
    index = shared_run(tmp_path, {SECOND: ref("docs/alias.md")}, prepare=prepare)
    only_shared(index, FIRST, SECOND)


def test_the_repository_name_case_does_not_make_a_record_distinct(tmp_path):
    index = shared_run(tmp_path, {SECOND: ref(record(FIRST), ADDON.lower())})
    only_shared(index, FIRST, SECOND)


def test_a_failed_case_stays_a_failure_beside_a_shared_record(tmp_path):
    index = shared_run(tmp_path, {SECOND: ref(record(FIRST))},
                       edit=lambda doc: gate_entry(doc, FIRST)["cases"][0].update(outcome="fail"))
    assert row(index, FIRST) == ("fail", ["1 case(s) failed"])
    assert row(index, SECOND) == ("unverified", [SHARED])
    assert index.exit_code == 2


def test_the_shared_record_reason_echoes_no_gate_path_or_reference(tmp_path):
    index = shared_run(tmp_path, {SECOND: ref(record(FIRST))})
    for gate in (FIRST, SECOND):
        reason = row(index, gate)[1][0]
        assert reason == SHARED
        for supplied in (FIRST, SECOND, record(FIRST), ADDON, "docs/records"):
            assert supplied not in reason


def test_distinct_records_keep_every_row_passing(tmp_path):
    assert complete(tmp_path).exit_code == 0


# ------------------------------------- one pinned checkout root per run

MARKER = "replacement-tree-marker"


def swap_after_first_open(monkeypatch, tmp_path: Path, reads: list) -> None:
    """After the checkout root was first opened, rename its ancestor and plant a different tree in its place."""
    state = {"swapped": False}
    original_open, original_read = ccm._open, ccm._read_descriptor

    def swap() -> None:
        (tmp_path / "job").rename(tmp_path / "job-original")
        tree = make_worktree(tmp_path / "job")
        for name in ("metadata.json", "results.json", "evidence.json"):  # The supplied paths resolve here too.
            write(tree, name, MARKER)
        for path in tree.rglob("*"):  # Every file of the replacement carries the marker.
            if path.is_file() and not path.is_symlink():
                path.write_text(MARKER, encoding="utf-8")

    def spy(path, flags, dir_fd=None):
        descriptor = original_open(path, flags, dir_fd)
        if not state["swapped"]:
            state["swapped"] = True
            swap()
        return descriptor

    def read(descriptor, limit=ccm.MAX_INPUT_BYTES):
        data = original_read(descriptor, limit)
        reads.append(data)
        return data
    monkeypatch.setattr(ccm, "_open", spy)
    monkeypatch.setattr(ccm, "_read_descriptor", read)


def test_an_ancestor_swapped_after_the_root_was_pinned_is_never_followed(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path / "job")
    metadata = write(tree, "metadata.json", candidate_metadata())
    results = write(tree, "results.json", results_doc())
    evidence = write(tree, "evidence.json", evidence_doc())
    reads: list = []
    swap_after_first_open(monkeypatch, tmp_path, reads)
    index = check(oai.build_index(tree, metadata, [results], [evidence]), tmp_path)
    assert (tmp_path / "job-original").is_dir() and reads
    assert not any(MARKER.encode() in data for data in reads), "a replacement tree was read"
    assert MARKER not in text(index)
    assert index.exit_code == 0, index.document["blocking"]


def test_the_validator_alone_never_follows_a_swapped_ancestor(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path / "job")
    metadata = write(tree, "metadata.json", candidate_metadata())
    reads: list = []
    swap_after_first_open(monkeypatch, tmp_path, reads)
    outcome = ccm.validate(metadata, tree, metadata_bytes=metadata.read_bytes())
    assert outcome.exit_code == 0 and reads and not any(MARKER.encode() in data for data in reads)


def test_a_listing_below_a_swapped_ancestor_never_lists_the_replacement(tmp_path, monkeypatch):
    tree = make_worktree(tmp_path / "job")
    (tree / "docs/alias").symlink_to("records")
    root_fd = ccm._pin_root(tree)
    try:
        (tmp_path / "job").rename(tmp_path / "job-original")
        replacement = make_worktree(tmp_path / "job")
        (replacement / "docs/records/only-in-replacement.md").write_text(MARKER, encoding="utf-8")
        (replacement / "docs/alias").symlink_to("records")
        listed: list = []
        listing_spy(monkeypatch, listed)
        absent = ccm._absent_locally(ref("docs/alias/only-in-replacement.md"), tree, root_fd=root_fd)
        present = ccm._absent_locally(ref(f"docs/alias/{FIRST}.md"), tree, root_fd=root_fd)
    finally:
        os.close(root_fd)
    assert absent is True and present is False
    assert identity(replacement / "docs/records") not in listed and identity(replacement / "docs") not in listed

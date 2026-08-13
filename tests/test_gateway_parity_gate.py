from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_gateway_parity_gate as gate  # noqa: E402


FIXTURE = SCRIPTS / "fixtures" / "gateway_parity_artifact_pass.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_exact_commit_provenance_contract_passes() -> None:
    payload = load_fixture()
    assert gate.validate_artifact(
        payload, gate.REQUIRED_SOURCE_REPO, payload["source_ref"]
    ) == []


def test_pull_request_or_different_tested_ref_is_rejected() -> None:
    payload = load_fixture()
    payload["tested_ref"] = "1" * 40
    payload["workflow_run"]["event"] = "pull_request"
    errors = gate.validate_artifact(
        payload, gate.REQUIRED_SOURCE_REPO, payload["source_ref"]
    )
    assert "tested_ref differs from pinned source_ref" in errors
    assert "workflow_run.event must be push" in errors


def test_online_verifier_rejects_executed_tree_mismatch(monkeypatch) -> None:
    payload = load_fixture()
    workflow = payload["workflow_run"]
    jobs = copy.deepcopy(workflow["jobs"])

    def fake_get(path: str, _token: str):
        if path.endswith(f"/actions/runs/{workflow['id']}"):
            return {
                "id": workflow["id"],
                "run_attempt": workflow["attempt"],
                "event": workflow["event"],
                "head_sha": workflow["head_sha"],
                "status": workflow["status"],
                "conclusion": workflow["conclusion"],
                "updated_at": workflow["updated_at"],
                "html_url": workflow["url"],
            }
        if "/jobs?" in path:
            return {"jobs": jobs}
        return {"tree": {"sha": "f" * 40}}

    monkeypatch.setattr(gate, "_github_token", lambda: "")
    monkeypatch.setattr(gate, "_github_json", fake_get)
    errors = gate.verify_github(payload, gate.REQUIRED_SOURCE_REPO)
    assert "GitHub pinned source tree mismatch" in errors
    assert "GitHub tested source tree mismatch" in errors

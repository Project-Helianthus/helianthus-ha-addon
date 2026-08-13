#!/usr/bin/env python3
"""Validate gateway parity artifact readiness markers for add-on rollout gates."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_SOURCE_REPO = "Project-Helianthus/helianthus-ebusgateway"
REQUIRED_GATES = ("parity_contract", "tool_classification")
REQUIRED_JOBS = ("build", "test", "lint", "terminology")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate gateway parity gate artifact")
    parser.add_argument("--artifact", required=True, help="Path to parity artifact JSON")
    parser.add_argument(
        "--source-repo",
        default=REQUIRED_SOURCE_REPO,
        help="Expected gateway source repository",
    )
    parser.add_argument(
        "--source-ref",
        required=True,
        help="Expected full gateway commit pinned by this add-on build",
    )
    parser.add_argument(
        "--verify-github",
        action="store_true",
        help="Verify the recorded workflow run, jobs, and source trees against GitHub",
    )
    return parser.parse_args()


def load_artifact(path: str) -> dict[str, Any]:
    artifact_path = Path(path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be a JSON object")
    return payload


def validate_artifact(
    payload: dict[str, Any], expected_source_repo: str, expected_source_ref: str
) -> list[str]:
    errors: list[str] = []

    source_repo = str(payload.get("source_repo", "")).strip()
    if source_repo != expected_source_repo:
        errors.append(
            f"source_repo mismatch: got={source_repo or '<empty>'} expected={expected_source_repo}"
        )

    source_ref = str(payload.get("source_ref", "")).strip()
    if source_ref != expected_source_ref:
        errors.append(
            f"source_ref mismatch: got={source_ref or '<empty>'} expected={expected_source_ref}"
        )
    generated_at = str(payload.get("generated_at", "")).strip()
    if not generated_at:
        errors.append("generated_at missing")
    else:
        try:
            dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("generated_at is not RFC3339")

    if payload.get("evidence_kind") != "github_actions_tree_equivalent_ci_v1":
        errors.append("evidence_kind mismatch")

    source_tree = str(payload.get("source_tree", "")).strip()
    tested_ref = str(payload.get("tested_ref", "")).strip()
    tested_tree = str(payload.get("tested_tree", "")).strip()
    for name, value in (
        ("source_tree", source_tree),
        ("tested_ref", tested_ref),
        ("tested_tree", tested_tree),
    ):
        if not SHA_RE.fullmatch(value):
            errors.append(f"{name} must be a full lowercase SHA")
    if source_tree and tested_tree and source_tree != tested_tree:
        errors.append("tested tree differs from pinned source tree")

    workflow = payload.get("workflow_run")
    if not isinstance(workflow, dict):
        errors.append("workflow_run missing or invalid")
    else:
        if not isinstance(workflow.get("id"), int) or workflow["id"] <= 0:
            errors.append("workflow_run.id missing or invalid")
        if workflow.get("attempt") != 1:
            errors.append("workflow_run.attempt must be 1")
        if workflow.get("head_sha") != tested_ref:
            errors.append("workflow_run.head_sha differs from tested_ref")
        if workflow.get("status") != "completed" or workflow.get("conclusion") != "success":
            errors.append("workflow_run is not completed successfully")
        if workflow.get("updated_at") != generated_at:
            errors.append("generated_at differs from workflow_run.updated_at")

        jobs = workflow.get("jobs")
        if not isinstance(jobs, list):
            errors.append("workflow_run.jobs missing or invalid")
        else:
            by_name = {str(job.get("name", "")): job for job in jobs if isinstance(job, dict)}
            for name in REQUIRED_JOBS:
                job = by_name.get(name)
                if job is None:
                    errors.append(f"workflow job {name} missing")
                elif (
                    not isinstance(job.get("id"), int)
                    or job.get("status") != "completed"
                    or job.get("conclusion") != "success"
                ):
                    errors.append(f"workflow job {name} is not completed successfully")

    gates = payload.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates missing or invalid")
        return errors

    for gate_name in REQUIRED_GATES:
        gate = gates.get(gate_name)
        if not isinstance(gate, dict):
            errors.append(f"gate {gate_name} missing")
            continue
        status = str(gate.get("status", "")).strip().lower()
        if status != "pass":
            errors.append(f"gate {gate_name} status is {status or '<empty>'}, expected pass")

    return errors


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], check=True, capture_output=True, text=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ValueError("GitHub token unavailable for online provenance verification") from exc
    token = result.stdout.strip()
    if not token:
        raise ValueError("GitHub token unavailable for online provenance verification")
    return token


def _github_json(path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def verify_github(payload: dict[str, Any], source_repo: str) -> list[str]:
    errors: list[str] = []
    workflow = payload.get("workflow_run")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("id"), int):
        return ["workflow_run unavailable for online verification"]
    token = _github_token()
    run_id = workflow["id"]
    run = _github_json(f"/repos/{source_repo}/actions/runs/{run_id}", token)
    jobs_payload = _github_json(f"/repos/{source_repo}/actions/runs/{run_id}/jobs?per_page=100", token)
    source_commit = _github_json(
        f"/repos/{source_repo}/git/commits/{payload.get('source_ref', '')}", token
    )
    tested_commit = _github_json(
        f"/repos/{source_repo}/git/commits/{payload.get('tested_ref', '')}", token
    )

    expected_run = {
        "id": workflow.get("id"),
        "run_attempt": workflow.get("attempt"),
        "head_sha": workflow.get("head_sha"),
        "status": workflow.get("status"),
        "conclusion": workflow.get("conclusion"),
        "updated_at": workflow.get("updated_at"),
        "html_url": workflow.get("url"),
    }
    for key, expected in expected_run.items():
        if run.get(key) != expected:
            errors.append(f"GitHub workflow field {key} mismatch")

    actual_jobs = {
        job.get("name"): job
        for job in jobs_payload.get("jobs", [])
        if isinstance(job, dict)
    }
    recorded_jobs = {
        job.get("name"): job
        for job in workflow.get("jobs", [])
        if isinstance(job, dict)
    }
    for name in REQUIRED_JOBS:
        actual = actual_jobs.get(name, {})
        recorded = recorded_jobs.get(name, {})
        for key in ("id", "status", "conclusion"):
            if actual.get(key) != recorded.get(key):
                errors.append(f"GitHub workflow job {name}.{key} mismatch")

    if source_commit.get("tree", {}).get("sha") != payload.get("source_tree"):
        errors.append("GitHub pinned source tree mismatch")
    if tested_commit.get("tree", {}).get("sha") != payload.get("tested_tree"):
        errors.append("GitHub tested source tree mismatch")
    return errors


def main() -> int:
    args = parse_args()
    try:
        payload = load_artifact(args.artifact)
    except FileNotFoundError:
        print(f"Gateway parity gate: FAIL (artifact missing: {args.artifact})")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Gateway parity gate: FAIL (invalid json: {exc})")
        return 1
    except ValueError as exc:
        print(f"Gateway parity gate: FAIL ({exc})")
        return 1

    errors = validate_artifact(payload, args.source_repo, args.source_ref)
    if not errors and args.verify_github:
        try:
            errors.extend(verify_github(payload, args.source_repo))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"online provenance verification failed: {exc}")
    if errors:
        print(f"Gateway parity gate: FAIL ({'; '.join(errors)})")
        return 1

    print("Gateway parity gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

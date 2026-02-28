#!/usr/bin/env python3
"""Validate gateway parity artifact readiness markers for add-on rollout gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_SOURCE_REPO = "Project-Helianthus/helianthus-ebusgateway"
REQUIRED_GATES = ("parity_contract", "tool_classification")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate gateway parity gate artifact")
    parser.add_argument("--artifact", required=True, help="Path to parity artifact JSON")
    parser.add_argument(
        "--source-repo",
        default=REQUIRED_SOURCE_REPO,
        help="Expected gateway source repository",
    )
    return parser.parse_args()


def load_artifact(path: str) -> dict[str, Any]:
    artifact_path = Path(path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be a JSON object")
    return payload


def validate_artifact(payload: dict[str, Any], expected_source_repo: str) -> list[str]:
    errors: list[str] = []

    source_repo = str(payload.get("source_repo", "")).strip()
    if source_repo != expected_source_repo:
        errors.append(
            f"source_repo mismatch: got={source_repo or '<empty>'} expected={expected_source_repo}"
        )

    if not str(payload.get("source_ref", "")).strip():
        errors.append("source_ref missing")
    if not str(payload.get("generated_at", "")).strip():
        errors.append("generated_at missing")

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

    errors = validate_artifact(payload, args.source_repo)
    if errors:
        print(f"Gateway parity gate: FAIL ({'; '.join(errors)})")
        return 1

    print("Gateway parity gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

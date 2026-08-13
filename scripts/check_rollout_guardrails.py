#!/usr/bin/env python3
"""Validate add-on rollout guardrails against gateway parity artifact status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import check_gateway_parity_gate as parity

VALID_STAGES = {"pre_parity", "post_parity"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate add-on rollout guardrails")
    parser.add_argument(
        "--guardrail",
        default="helianthus/rollout_guardrails.json",
        help="Path to add-on rollout guardrail config",
    )
    parser.add_argument(
        "--artifact",
        default="scripts/fixtures/gateway_parity_artifact_pass.json",
        help="Path to gateway parity artifact JSON",
    )
    parser.add_argument(
        "--source-repo",
        default=parity.REQUIRED_SOURCE_REPO,
        help="Expected gateway source repository",
    )
    parser.add_argument(
        "--source-ref",
        required=True,
        help="Expected full gateway commit pinned by this add-on build",
    )
    return parser.parse_args()


def load_guardrail(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("guardrail config must be a JSON object")
    return payload


def validate_guardrails(
    guardrail: dict, artifact: dict, source_repo: str, source_ref: str
) -> list[str]:
    errors: list[str] = []

    stage = str(guardrail.get("stage", "")).strip()
    if stage not in VALID_STAGES:
        errors.append(f"invalid stage: {stage or '<empty>'}")
        return errors

    allow_consumer_expansion = bool(guardrail.get("allow_consumer_expansion", False))

    required_gates = guardrail.get("required_gateway_gates", list(parity.REQUIRED_GATES))
    if not isinstance(required_gates, list) or not required_gates:
        errors.append("required_gateway_gates missing or invalid")
        return errors

    for gate in required_gates:
        gate_name = str(gate).strip()
        if not gate_name:
            errors.append("required_gateway_gates contains empty value")
            continue
        if gate_name not in parity.REQUIRED_GATES:
            errors.append(f"unsupported required gate: {gate_name}")

    if errors:
        return errors

    if stage == "pre_parity":
        if allow_consumer_expansion:
            errors.append("pre_parity stage forbids allow_consumer_expansion=true")
        return errors

    if not allow_consumer_expansion:
        errors.append("post_parity stage requires allow_consumer_expansion=true")

    parity_errors = parity.validate_artifact(artifact, source_repo, source_ref)
    if parity_errors:
        errors.extend(parity_errors)
        return errors

    gates = artifact.get("gates") if isinstance(artifact.get("gates"), dict) else {}
    for gate in required_gates:
        gate_name = str(gate)
        gate_payload = gates.get(gate_name, {})
        status = str(gate_payload.get("status", "")).strip().lower()
        if status != "pass":
            errors.append(f"required gate {gate_name} is not pass")

    return errors


def main() -> int:
    args = parse_args()

    try:
        guardrail = load_guardrail(args.guardrail)
    except FileNotFoundError:
        print(f"Rollout guardrails: FAIL (guardrail missing: {args.guardrail})")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Rollout guardrails: FAIL (invalid guardrail json: {exc})")
        return 1
    except ValueError as exc:
        print(f"Rollout guardrails: FAIL ({exc})")
        return 1

    try:
        artifact = parity.load_artifact(args.artifact)
    except FileNotFoundError:
        print(f"Rollout guardrails: FAIL (parity artifact missing: {args.artifact})")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Rollout guardrails: FAIL (invalid parity artifact json: {exc})")
        return 1
    except ValueError as exc:
        print(f"Rollout guardrails: FAIL ({exc})")
        return 1

    errors = validate_guardrails(guardrail, artifact, args.source_repo, args.source_ref)
    if errors:
        print(f"Rollout guardrails: FAIL ({'; '.join(errors)})")
        return 1

    stage = str(guardrail.get("stage", "")).strip()
    allow = bool(guardrail.get("allow_consumer_expansion", False))
    print(f"Rollout guardrails: PASS (stage={stage}, allow_consumer_expansion={str(allow).lower()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

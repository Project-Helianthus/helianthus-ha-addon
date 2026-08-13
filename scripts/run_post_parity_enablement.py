#!/usr/bin/env python3
"""Run add-on post-parity enablement tasks when rollout guardrails allow them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import check_gateway_parity_gate as parity
import check_rollout_guardrails as guardrails

REQUIRED_CONFIG_OPTIONS = ("http_port", "graphql_path", "subscription_path", "mcp_path")
REQUIRED_RUNBOOK_MARKERS = ("CHECK_CONNECTION_GRAPHQL", "CHECK_CONNECTION_MCP")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run add-on post-parity enablement tasks")
    parser.add_argument(
        "--guardrail",
        default="helianthus/rollout_guardrails.json",
        help="Path to rollout guardrail config",
    )
    parser.add_argument(
        "--artifact",
        default="scripts/fixtures/gateway_parity_artifact_pass.json",
        help="Path to gateway parity artifact",
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
    parser.add_argument(
        "--addon-config",
        default="helianthus/config.json",
        help="Path to add-on config.json",
    )
    parser.add_argument(
        "--smoke-runbook",
        default="SMOKE_RUNBOOK.md",
        help="Path to smoke runbook markdown",
    )
    return parser.parse_args()


def run_enablement_checks(addon_config_path: str, smoke_runbook_path: str) -> list[str]:
    errors: list[str] = []

    try:
        addon_config = json.loads(Path(addon_config_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"add-on config missing: {addon_config_path}"]
    except json.JSONDecodeError as exc:
        return [f"add-on config invalid json: {exc}"]

    options = addon_config.get("options") if isinstance(addon_config, dict) else None
    schema = addon_config.get("schema") if isinstance(addon_config, dict) else None
    if not isinstance(options, dict):
        errors.append("add-on config options missing or invalid")
    if not isinstance(schema, dict):
        errors.append("add-on config schema missing or invalid")

    for key in REQUIRED_CONFIG_OPTIONS:
        if isinstance(options, dict) and key not in options:
            errors.append(f"add-on config options missing key: {key}")
        if isinstance(schema, dict) and key not in schema:
            errors.append(f"add-on config schema missing key: {key}")

    try:
        runbook_text = Path(smoke_runbook_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"smoke runbook missing: {smoke_runbook_path}")
        return errors

    for marker in REQUIRED_RUNBOOK_MARKERS:
        if marker not in runbook_text:
            errors.append(f"smoke runbook missing marker: {marker}")

    return errors


def main() -> int:
    args = parse_args()

    try:
        guardrail = guardrails.load_guardrail(args.guardrail)
    except FileNotFoundError:
        print(f"Post-parity enablement: FAIL (guardrail missing: {args.guardrail})")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Post-parity enablement: FAIL (invalid guardrail json: {exc})")
        return 1
    except ValueError as exc:
        print(f"Post-parity enablement: FAIL ({exc})")
        return 1

    stage = str(guardrail.get("stage", "")).strip()
    if stage != "post_parity":
        print(f"Post-parity enablement: SKIP (stage={stage or '<empty>'})")
        return 0

    try:
        artifact = parity.load_artifact(args.artifact)
    except FileNotFoundError:
        print(f"Post-parity enablement: FAIL (parity artifact missing: {args.artifact})")
        return 1
    except json.JSONDecodeError as exc:
        print(f"Post-parity enablement: FAIL (invalid parity artifact json: {exc})")
        return 1
    except ValueError as exc:
        print(f"Post-parity enablement: FAIL ({exc})")
        return 1

    rollout_errors = guardrails.validate_guardrails(
        guardrail, artifact, args.source_repo, args.source_ref
    )
    if rollout_errors:
        print(f"Post-parity enablement: FAIL ({'; '.join(rollout_errors)})")
        return 1

    enablement_errors = run_enablement_checks(args.addon_config, args.smoke_runbook)
    if enablement_errors:
        print(f"Post-parity enablement: FAIL ({'; '.join(enablement_errors)})")
        return 1

    print("Post-parity enablement: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

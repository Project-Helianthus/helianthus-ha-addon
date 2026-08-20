#!/usr/bin/env python3
"""Validate the closed M5-08 Fronius-to-Home-Assistant rollout artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
from typing import Any


CONTRACT_ID = "helianthus.fronius-ha-rollout/v1"
ADDON_VERSION = "0.6.53"
GATEWAY_REF = "739721c9ed19e95bb6531a3b87ebc5f49a3ef19e"
HA_INTEGRATION_REF = "e614e63898d4ddc317c66f1a673fefe0e2786245"
REQUIRED_ASSERTIONS = {
    "raw_mcp",
    "semantic_mcp",
    "graphql_m2m",
    "portal_semantic",
    "portal_raw",
    "home_assistant",
    "external_mtls",
    "credential_recovery",
    "channel_recovery",
    "restart",
    "modbus_independent_disable",
    "ha_independent_disable",
    "compatible_rollback",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _closed(value: object, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _rfc3339(value: object, context: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be RFC3339")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")


def validate(payload: object, mode: str) -> list[str]:
    errors: list[str] = []
    try:
        root = _closed(
            payload,
            {
                "contract_id",
                "evidence_kind",
                "mode",
                "release",
                "required_assertions",
                "safety",
                "limits",
                "rollback",
                "live",
            },
            "artifact",
        )
        if root["contract_id"] != CONTRACT_ID:
            errors.append("contract_id mismatch")
        if root["mode"] != mode:
            errors.append("mode mismatch")
        expected_kind = "contract_fixture_v1" if mode == "contract" else "live_smoke_v1"
        if root["evidence_kind"] != expected_kind:
            errors.append("evidence_kind mismatch")

        release = _closed(
            root["release"],
            {"addon_version", "gateway_ref", "ha_integration_ref"},
            "release",
        )
        expected_release = {
            "addon_version": ADDON_VERSION,
            "gateway_ref": GATEWAY_REF,
            "ha_integration_ref": HA_INTEGRATION_REF,
        }
        if release != expected_release:
            errors.append("release identity mismatch")
        if not SHA_RE.fullmatch(str(release["gateway_ref"])) or not SHA_RE.fullmatch(
            str(release["ha_integration_ref"])
        ):
            errors.append("release refs must be full SHAs")

        assertions = _closed(root["required_assertions"], REQUIRED_ASSERTIONS, "assertions")
        expected_status = "required" if mode == "contract" else "pass"
        if any(value != expected_status for value in assertions.values()):
            errors.append(f"all assertions must be {expected_status}")

        safety = _closed(
            root["safety"],
            {"no_modbus_writes", "no_inverter_mutation", "endpoint_values_redacted"},
            "safety",
        )
        if set(safety.values()) != {True}:
            errors.append("all safety invariants must be true")

        limits = _closed(
            root["limits"],
            {"external_poll_min_seconds", "raw_max_registers", "response_max_bytes"},
            "limits",
        )
        if limits != {
            "external_poll_min_seconds": 5,
            "raw_max_registers": 125,
            "response_max_bytes": 1_048_576,
        }:
            errors.append("rollout limits mismatch")

        rollback = _closed(
            root["rollback"],
            {"prior_version", "schema_compatible", "backup_required"},
            "rollback",
        )
        if rollback != {
            "prior_version": "0.6.52",
            "schema_compatible": True,
            "backup_required": True,
        }:
            errors.append("rollback contract mismatch")

        if mode == "contract":
            if root["live"] is not None:
                errors.append("contract fixture must not contain live evidence")
        else:
            live = _closed(
                root["live"],
                {
                    "image_digest",
                    "installed_at",
                    "backup_ref",
                    "evidence_ref",
                    "runtime_version",
                    "gateway_build_id",
                    "ha_integration_ref",
                },
                "live evidence",
            )
            if not DIGEST_RE.fullmatch(str(live["image_digest"])):
                errors.append("live image_digest must be sha256")
            if not DIGEST_RE.fullmatch(str(live["evidence_ref"])):
                errors.append("live evidence_ref must be sha256")
            _rfc3339(live["installed_at"], "live installed_at")
            if not isinstance(live["backup_ref"], str) or not live["backup_ref"]:
                errors.append("live backup_ref missing")
            if live["runtime_version"] != ADDON_VERSION:
                errors.append("live runtime version mismatch")
            if live["gateway_build_id"] != GATEWAY_REF:
                errors.append("live gateway build mismatch")
            if live["ha_integration_ref"] != HA_INTEGRATION_REF:
                errors.append("live HA integration mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--mode", choices=("contract", "lab"), required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Fronius HA rollout: FAIL ({exc})")
        return 1
    errors = validate(payload, args.mode)
    if errors:
        print(f"Fronius HA rollout: FAIL ({'; '.join(errors)})")
        return 1
    print(f"Fronius HA rollout: PASS (mode={args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the closed M5-08 Fronius-to-Home-Assistant rollout artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CONTRACT_ID = "helianthus.fronius-ha-rollout/v1"
ADDON_VERSION = "0.6.56"
GATEWAY_REF = "a759efd7f72a099288f1fc2b7cf20236d37cfa0b"
HA_INTEGRATION_REF = "e614e63898d4ddc317c66f1a673fefe0e2786245"
IMAGE_REPOSITORY = "ghcr.io/project-helianthus/helianthus-ha-addon"
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
BACKUP_RE = re.compile(r"^[0-9a-f]{8}$")
RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


def _closed(value: object, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _rfc3339(value: object, context: str) -> None:
    if not isinstance(value, str) or RFC3339_RE.fullmatch(value) is None:
        raise ValueError(f"{context} must be RFC3339")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")


def _platform_id(platform: object) -> str:
    if not isinstance(platform, dict):
        return ""
    operating_system = platform.get("os")
    architecture = platform.get("architecture")
    if not isinstance(operating_system, str) or not isinstance(architecture, str):
        return ""
    identifier = f"{operating_system}/{architecture}"
    variant = platform.get("variant")
    if architecture == "arm" and isinstance(variant, str) and variant:
        identifier += f"/{variant}"
    return identifier


def resolve_publication(
    image_repository: str, image_tag: str, target_platform: str
) -> dict[str, str]:
    if image_repository != IMAGE_REPOSITORY or image_tag != ADDON_VERSION:
        raise ValueError("live image repository or tag mismatch")
    repository_path = image_repository.removeprefix("ghcr.io/")
    token_query = urlencode(
        {
            "service": "ghcr.io",
            "scope": f"repository:{repository_path}:pull",
        }
    )
    token_request = Request(
        f"https://ghcr.io/token?{token_query}",
        headers={"Accept": "application/json"},
    )
    with urlopen(token_request, timeout=30) as response:
        token_payload = json.loads(response.read(65_537))
    token = token_payload.get("token") if isinstance(token_payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("GHCR pull token missing")

    manifest_request = Request(
        f"https://ghcr.io/v2/{repository_path}/manifests/{image_tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ", ".join(
                (
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                )
            ),
        },
    )
    with urlopen(manifest_request, timeout=30) as response:
        manifest_digest = response.headers.get("Docker-Content-Digest", "")
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576 or DIGEST_RE.fullmatch(manifest_digest) is None:
        raise ValueError("GHCR manifest response is invalid or unbounded")
    manifest = json.loads(raw)
    descriptors = manifest.get("manifests") if isinstance(manifest, dict) else None
    if not isinstance(descriptors, list):
        raise ValueError("GHCR tag is not a multi-platform manifest")
    matches = [
        descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict)
        and _platform_id(descriptor.get("platform")) == target_platform
    ]
    if len(matches) != 1:
        raise ValueError("GHCR target platform is missing or ambiguous")
    platform_digest = matches[0].get("digest")
    if not isinstance(platform_digest, str) or DIGEST_RE.fullmatch(platform_digest) is None:
        raise ValueError("GHCR platform digest is invalid")
    return {
        "image_repository": image_repository,
        "image_tag": image_tag,
        "target_platform": target_platform,
        "manifest_digest": manifest_digest,
        "platform_digest": platform_digest,
    }


def validate(
    payload: object,
    mode: str,
    *,
    publication: dict[str, str] | None = None,
) -> list[str]:
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
        if any(type(value) is not bool or value is not True for value in safety.values()):
            errors.append("all safety invariants must be true")

        limits = _closed(
            root["limits"],
            {"external_poll_min_seconds", "raw_max_registers", "response_max_bytes"},
            "limits",
        )
        if any(type(value) is not int for value in limits.values()) or limits != {
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
        if (
            type(rollback["schema_compatible"]) is not bool
            or type(rollback["backup_required"]) is not bool
            or rollback
            != {
                "prior_version": "0.6.55",
                "schema_compatible": True,
                "backup_required": True,
            }
        ):
            errors.append("rollback contract mismatch")

        if mode == "contract":
            if root["live"] is not None:
                errors.append("contract fixture must not contain live evidence")
        else:
            live = _closed(
                root["live"],
                {
                    "image_repository",
                    "image_tag",
                    "target_platform",
                    "manifest_digest",
                    "platform_digest",
                    "installed_image_digest",
                    "installed_at",
                    "backup_ref",
                    "evidence_ref",
                    "runtime_version",
                    "gateway_build_id",
                    "ha_integration_ref",
                },
                "live evidence",
            )
            if publication is None:
                errors.append("verified OCI publication is required in lab mode")
            else:
                for field in (
                    "image_repository",
                    "image_tag",
                    "target_platform",
                    "manifest_digest",
                    "platform_digest",
                ):
                    if live[field] != publication.get(field):
                        errors.append(f"live {field} differs from verified OCI publication")
            for field in ("manifest_digest", "platform_digest", "installed_image_digest"):
                if not DIGEST_RE.fullmatch(str(live[field])):
                    errors.append(f"live {field} must be sha256")
            if live["installed_image_digest"] != live["manifest_digest"]:
                errors.append("installed image digest differs from published manifest")
            if not DIGEST_RE.fullmatch(str(live["evidence_ref"])):
                errors.append("live evidence_ref must be sha256")
            _rfc3339(live["installed_at"], "live installed_at")
            if not isinstance(live["backup_ref"], str) or not BACKUP_RE.fullmatch(
                live["backup_ref"]
            ):
                errors.append("live backup_ref must be an 8-character lowercase hex slug")
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
    publication = None
    if args.mode == "lab":
        live = payload.get("live") if isinstance(payload, dict) else None
        try:
            if not isinstance(live, dict):
                raise ValueError("live evidence missing")
            publication = resolve_publication(
                str(live.get("image_repository", "")),
                str(live.get("image_tag", "")),
                str(live.get("target_platform", "")),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Fronius HA rollout: FAIL (OCI publication verification failed: {exc})")
            return 1
    errors = validate(payload, args.mode, publication=publication)
    if errors:
        print(f"Fronius HA rollout: FAIL ({'; '.join(errors)})")
        return 1
    print(f"Fronius HA rollout: PASS (mode={args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

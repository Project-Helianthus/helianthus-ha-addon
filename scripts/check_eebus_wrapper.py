#!/usr/bin/env python3
"""Check the add-on's eeBUS runtime boundary after AdminV1 removal."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
DOCKERFILE = ROOT / "helianthus/Dockerfile"
WORKFLOW = ROOT / ".github/workflows/build.yml"
PARITY = ROOT / "scripts/fixtures/gateway_parity_artifact_pass.json"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
HELPER = ROOT / "helianthus/rootfs/usr/share/helianthus/eebus_admin_credentials.py"

RELEASE = "0.6.44"
GATEWAY = "dadba65ea77e197c6e542a98a554b09f2016cb16"
REMOVED_OPTIONS = (
    "eebus_admin_enabled",
    "eebus_admin_owner_username",
    "eebus_admin_origin",
    "eebus_admin_session_ttl",
    "eebus_admin_owner_secret",
    "eebus_admin_ha_secret",
)
REMOVED_WRAPPER_TERMS = (
    "eebus_admin",
    "eebus-admin",
    "eebus_admin_credentials.py",
    "/run/helianthus/eebus-admin",
)


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    parity = json.loads(PARITY.read_text(encoding="utf-8"))
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    run = RUN.read_text(encoding="utf-8")

    assert config["version"] == RELEASE, "config.json must be the 0.6.44 release authority"
    assert f"ARG EBUSGATEWAY_VERSION={GATEWAY}" in dockerfile, "Dockerfile primary gateway pin drifted"
    assert f"EBUSGATEWAY_VERSION={GATEWAY}" in workflow, "workflow primary gateway pin drifted"
    for key in ("source_ref", "tested_ref"):
        assert parity[key] == GATEWAY, f"parity {key} must pin the release gateway"
    assert parity["workflow_run"]["head_sha"] == GATEWAY, "parity head must be the release gateway"
    for name in REMOVED_OPTIONS:
        assert name not in config["options"] and name not in config["schema"], f"obsolete eeBUS Admin option remains: {name}"
    assert not HELPER.exists(), "obsolete eeBUS Admin credential helper remains packaged"
    for term in REMOVED_WRAPPER_TERMS:
        assert term not in run, f"obsolete eeBUS Admin wrapper wiring remains: {term}"
    assert "/data/helianthus-gateway" not in run, "persistent gateway override remains"
    print("eeBUS wrapper removal contract passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"eeBUS wrapper removal contract: FAIL ({exc})")
        raise SystemExit(1)

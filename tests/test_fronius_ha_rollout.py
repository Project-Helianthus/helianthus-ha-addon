from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.53"
GATEWAY = "739721c9ed19e95bb6531a3b87ebc5f49a3ef19e"
HA_INTEGRATION = "e614e63898d4ddc317c66f1a673fefe0e2786245"
FIXTURE = ROOT / "scripts/fixtures/fronius_ha_rollout_contract_pass.json"
VERIFIER = ROOT / "scripts/check_fronius_ha_rollout.py"


def _verifier_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("check_fronius_ha_rollout", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_payload() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["mode"] = "lab"
    payload["evidence_kind"] = "live_smoke_v1"
    payload["required_assertions"] = {
        name: "pass" for name in payload["required_assertions"]
    }
    payload["live"] = {
        "image_digest": "sha256:" + "a" * 64,
        "installed_at": "2026-08-20T15:00:00+03:00",
        "backup_ref": "b930e982",
        "evidence_ref": "sha256:" + "b" * 64,
        "runtime_version": VERSION,
        "gateway_build_id": GATEWAY,
        "ha_integration_ref": HA_INTEGRATION,
    }
    return payload


def test_release_pins_exact_m5_06_gateway_and_m5_07_consumer() -> None:
    config = json.loads((ROOT / "helianthus/config.json").read_text(encoding="utf-8"))
    dockerfile = (ROOT / "helianthus/Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    changelog = (ROOT / "helianthus/CHANGELOG.md").read_text(encoding="utf-8")

    assert config["version"] == VERSION
    assert f"ARG EBUSGATEWAY_VERSION={GATEWAY}" in dockerfile
    assert f"EBUSGATEWAY_VERSION={GATEWAY}" in workflow
    assert f"## {VERSION} " in changelog
    assert GATEWAY in changelog
    assert HA_INTEGRATION in changelog


def test_rollout_contract_fixture_covers_every_m5_08_gate() -> None:
    assert VERIFIER.is_file()
    assert FIXTURE.is_file()
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--artifact", str(FIXTURE), "--mode", "contract"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["release"] == {
        "addon_version": VERSION,
        "gateway_ref": GATEWAY,
        "ha_integration_ref": HA_INTEGRATION,
    }
    assert set(payload["required_assertions"]) == {
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


def test_rollout_verifier_is_wired_into_ci_and_smoke_runbook() -> None:
    ci = (ROOT / "scripts/ci_local.sh").read_text(encoding="utf-8")
    pr_ci = (ROOT / ".github/workflows/pr-ci.yml").read_text(encoding="utf-8")
    runbook = (ROOT / "SMOKE_RUNBOOK.md").read_text(encoding="utf-8")

    assert "tests/test_fronius_ha_rollout.py" in ci
    assert "check_fronius_ha_rollout.py" in ci
    assert "tests/test_fronius_ha_rollout.py" in pr_ci
    assert "check_fronius_ha_rollout.py" in pr_ci
    for marker in (
        "M5_08_RAW_MCP",
        "M5_08_SEMANTIC_MCP",
        "M5_08_GRAPHQL_M2M",
        "M5_08_PORTAL_SEMANTIC",
        "M5_08_PORTAL_RAW",
        "M5_08_HOME_ASSISTANT",
        "M5_08_EXTERNAL_MTLS",
        "M5_08_RECOVERY",
        "M5_08_INDEPENDENT_DISABLE",
        "M5_08_ROLLBACK",
    ):
        assert marker in runbook


def test_rollout_verifier_rejects_numeric_boolean_claims() -> None:
    verifier = _verifier_module()
    for path in (
        ("safety", "no_modbus_writes"),
        ("safety", "no_inverter_mutation"),
        ("safety", "endpoint_values_redacted"),
        ("rollback", "schema_compatible"),
        ("rollback", "backup_required"),
    ):
        payload = deepcopy(_live_payload())
        payload[path[0]][path[1]] = 1
        assert verifier.validate(payload, "lab")


def test_rollout_verifier_rejects_whitespace_backup_reference() -> None:
    verifier = _verifier_module()
    payload = _live_payload()
    payload["live"]["backup_ref"] = " "
    assert verifier.validate(payload, "lab")

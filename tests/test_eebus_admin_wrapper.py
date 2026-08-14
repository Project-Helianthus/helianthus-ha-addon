from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
DOCKERFILE = ROOT / "helianthus/Dockerfile"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
HELPER = (
    ROOT
    / "helianthus/rootfs/usr/share/helianthus/eebus_admin_credentials.py"
)
BUILD_WORKFLOW = ROOT / ".github/workflows/build.yml"
PARITY = ROOT / "scripts/fixtures/gateway_parity_artifact_pass.json"

CURRENT_GATEWAY = "78130598d7420b7d04b35bee8aa86fc0fb3f1d39"
FALLBACK_GATEWAY = "035e2b5cf703d68f75b809c45d2b1342696c07ef"
CURRENT_TREE = "f3a829785224e4b19b0534fb1d4034a78efe411a"
OWNER_SECRET = "owner-0123456789abcdef0123456789ab"
HA_SECRET = "ha-machine-0123456789abcdef0123456"


def enabled_options(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "eebus_enabled": True,
        "eebus_admin_enabled": True,
        "eebus_admin_owner_username": "operator",
        "eebus_admin_origin": "http://192.0.2.10:8080",
        "eebus_admin_session_ttl": "20m",
        "eebus_admin_owner_secret": OWNER_SECRET,
        "eebus_admin_ha_secret": HA_SECRET,
    }
    payload.update(overrides)
    return payload


def run_helper(tmp_path: Path, payload: object) -> tuple[subprocess.CompletedProcess[str], Path]:
    assert HELPER.is_file(), "eeBUS AdminV1 credential materializer is missing"
    options = tmp_path / "options.json"
    options.write_text(json.dumps(payload), encoding="utf-8")
    runtime = tmp_path / "run" / "eebus-admin"
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--options",
            str(options),
            "--runtime-dir",
            str(runtime),
        ],
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": os.environ.get("PATH", "")},
    )
    return result, runtime


def parsed_status(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def assert_no_runtime_credentials(runtime: Path) -> None:
    assert not (runtime / "owner").exists()
    assert not (runtime / "ha").exists()


def test_release_pin_and_build_version_have_one_authority() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
    parity = json.loads(PARITY.read_text(encoding="utf-8"))

    assert config["version"] == "0.6.43"
    assert f"ARG EBUSGATEWAY_VERSION={CURRENT_GATEWAY}" in dockerfile
    assert f"ARG EBUSGATEWAY_FALLBACK_VERSION={FALLBACK_GATEWAY}" in dockerfile
    assert "ARG BUILD_VERSION" in dockerfile
    assert "main.buildVersion=${BUILD_VERSION}" in dockerfile
    assert "main.buildID=${EBUSGATEWAY_VERSION}" in dockerfile
    assert "main.buildID=${EBUSGATEWAY_FALLBACK_VERSION}" in dockerfile
    assert f"EBUSGATEWAY_VERSION={CURRENT_GATEWAY}" in workflow
    assert f"EBUSGATEWAY_FALLBACK_VERSION={FALLBACK_GATEWAY}" in workflow
    assert "BUILD_VERSION=${{ steps.addon.outputs.version }}" in workflow
    assert parity["source_ref"] == CURRENT_GATEWAY
    assert parity["tested_ref"] == CURRENT_GATEWAY
    assert parity["source_tree"] == CURRENT_TREE
    assert parity["tested_tree"] == CURRENT_TREE
    assert parity["workflow_run"]["id"] == 31792320140


def test_admin_schema_is_disabled_by_default_and_secrets_are_passwords() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    options = config["options"]
    schema = config["schema"]

    assert options["eebus_admin_enabled"] is False
    assert options["eebus_admin_owner_username"] == "operator"
    assert options["eebus_admin_origin"] == ""
    assert options["eebus_admin_session_ttl"] == "20m"
    assert options["eebus_admin_owner_secret"] == ""
    assert options["eebus_admin_ha_secret"] == ""
    assert schema["eebus_admin_enabled"] == "bool"
    assert schema["eebus_admin_owner_username"] == "str"
    assert schema["eebus_admin_origin"] == "str"
    assert schema["eebus_admin_session_ttl"] == "str"
    assert schema["eebus_admin_owner_secret"] == "password"
    assert schema["eebus_admin_ha_secret"] == "password"


def test_disabled_or_eebus_disabled_clears_stale_runtime_files(tmp_path: Path) -> None:
    for payload in (
        enabled_options(eebus_admin_enabled=False),
        enabled_options(eebus_enabled=False),
    ):
        stale_dir = tmp_path / "run" / "eebus-admin"
        stale_dir.mkdir(parents=True, exist_ok=True)
        (stale_dir / "owner").write_text("stale-owner", encoding="utf-8")
        (stale_dir / "ha").write_text("stale-ha", encoding="utf-8")
        result, runtime = run_helper(tmp_path, payload)
        status_payload = parsed_status(result)
        assert status_payload == {"status": "disabled"}
        assert_no_runtime_credentials(runtime)


def test_valid_bundle_materializes_only_two_atomic_private_files(tmp_path: Path) -> None:
    result, runtime = run_helper(tmp_path, enabled_options())
    payload = parsed_status(result)

    assert payload == {
        "status": "ready",
        "owner_username": "operator",
        "origin": "http://192.0.2.10:8080",
        "session_ttl": "20m",
    }
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert sorted(path.name for path in runtime.iterdir()) == ["ha", "owner"]
    assert (runtime / "owner").read_text(encoding="ascii") == OWNER_SECRET
    assert (runtime / "ha").read_text(encoding="ascii") == HA_SECRET
    assert stat.S_IMODE((runtime / "owner").stat().st_mode) == 0o600
    assert stat.S_IMODE((runtime / "ha").stat().st_mode) == 0o600
    assert OWNER_SECRET not in result.stdout + result.stderr
    assert HA_SECRET not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {"eebus_admin_owner_secret": "short"},
        {"eebus_admin_ha_secret": "x" * 257},
        {"eebus_admin_owner_secret": HA_SECRET},
        {"eebus_admin_owner_secret": "x" * 31 + " "},
        {"eebus_admin_ha_secret": "x" * 31 + "\n"},
        {"eebus_admin_ha_secret": "x" * 31 + "é"},
        {"eebus_admin_owner_secret": 42},
        {"eebus_admin_origin": "https://user@example.test"},
        {"eebus_admin_origin": "https://example.test/path"},
        {"eebus_admin_session_ttl": "25h"},
        {"eebus_admin_owner_username": "bad:user"},
    ],
)
def test_invalid_bundle_is_categorical_and_removes_both_files(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    result, runtime = run_helper(tmp_path, enabled_options(**overrides))
    payload = parsed_status(result)

    assert payload == {"status": "unavailable", "reason": "configuration"}
    assert_no_runtime_credentials(runtime)
    rendered = result.stdout + result.stderr
    assert OWNER_SECRET not in rendered
    assert HA_SECRET not in rendered
    for value in overrides.values():
        if isinstance(value, str):
            assert value not in rendered


def test_symlinked_runtime_target_fails_closed_without_partial_output(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "owner"
    sentinel.write_text("do-not-touch", encoding="utf-8")
    runtime = tmp_path / "run" / "eebus-admin"
    runtime.mkdir(parents=True)
    (runtime / "owner").symlink_to(sentinel)
    (runtime / "ha").write_text("stale-ha", encoding="utf-8")

    result, returned_runtime = run_helper(tmp_path, enabled_options())
    payload = parsed_status(result)

    assert returned_runtime == runtime
    assert payload == {"status": "unavailable", "reason": "runtime_store"}
    assert sentinel.read_text(encoding="utf-8") == "do-not-touch"
    assert_no_runtime_credentials(runtime)


def test_rotation_replaces_both_credentials_without_leaking_old_or_new(tmp_path: Path) -> None:
    first, runtime = run_helper(tmp_path, enabled_options())
    assert parsed_status(first)["status"] == "ready"
    rotated_owner = "rotated-owner-0123456789abcdef0123"
    rotated_ha = "rotated-ha-0123456789abcdef012345"

    second, runtime = run_helper(
        tmp_path,
        enabled_options(
            eebus_admin_owner_secret=rotated_owner,
            eebus_admin_ha_secret=rotated_ha,
        ),
    )
    assert parsed_status(second)["status"] == "ready"
    assert (runtime / "owner").read_text(encoding="ascii") == rotated_owner
    assert (runtime / "ha").read_text(encoding="ascii") == rotated_ha
    rendered = first.stdout + first.stderr + second.stdout + second.stderr
    for secret in (OWNER_SECRET, HA_SECRET, rotated_owner, rotated_ha):
        assert secret not in rendered


def test_wrapper_never_reads_secret_options_and_isolates_fallback_args() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert "eebus_admin_credentials.py" in run
    assert "bashio::config 'eebus_admin_owner_secret'" not in run
    assert "bashio::config 'eebus_admin_ha_secret'" not in run
    assert "export EEBUS_ADMIN" not in run
    assert "-eebus-admin-owner-secret-file" in run
    assert "-eebus-admin-ha-secret-file" in run
    assert "-eebus-admin-origin" in run
    assert "-eebus-admin-session-ttl" in run
    assert "gateway_args+=(\"${eebus_admin_args[@]}\")" in run
    assert "gateway_common_args+=(\"${eebus_admin_args[@]}\")" not in run
    fallback_section = run.split('modbus_fallback_args=("${gateway_common_args[@]}")', 1)[1]
    assert "eebus_admin_args" not in fallback_section
    assert OWNER_SECRET not in run
    assert HA_SECRET not in run

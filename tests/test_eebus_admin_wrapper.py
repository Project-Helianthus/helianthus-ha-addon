from __future__ import annotations

import json
import os
import stat
import subprocess
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


def test_release_pin_is_0644_and_gateway_provenance_is_exact() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    parity = json.loads(PARITY.read_text(encoding="utf-8"))

    assert config["version"] == RELEASE
    assert f"ARG EBUSGATEWAY_VERSION={GATEWAY}" in dockerfile
    assert f"EBUSGATEWAY_VERSION={GATEWAY}" in workflow
    assert parity["source_ref"] == GATEWAY
    assert parity["tested_ref"] == GATEWAY
    assert parity["workflow_run"]["head_sha"] == GATEWAY


def test_config_has_no_eebus_admin_schema_or_options() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    for name in REMOVED_OPTIONS:
        assert name not in config["options"]
        assert name not in config["schema"]


def test_wrapper_has_no_eebus_admin_materializer_or_persistent_override() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert not HELPER.exists()
    for term in REMOVED_WRAPPER_TERMS:
        assert term not in run
    assert "/data/helianthus-gateway" not in run


def test_eebus_runtime_keeps_pairing_without_admin_argv_logs_or_environment(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "run-under-test.sh"
    gateway = tmp_path / "gateway.py"
    helper = tmp_path / "legacy-helper.py"
    argv = tmp_path / "argv"
    log = tmp_path / "log"
    runtime = tmp_path / "runtime"
    interface_id = tmp_path / "interface-id"
    options = tmp_path / "options.json"
    options.write_text("{}", encoding="utf-8")
    interface_id.write_text("001122334455\n", encoding="utf-8")
    helper.write_text(
        "#!/usr/bin/env python3\nprint('{\"status\": \"ready\", \"owner_username\": \"operator\", \"origin\": \"http://192.0.2.10\", \"session_ttl\": \"20m\"}')\n",
        encoding="utf-8",
    )
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
    gateway.write_text(
        "#!/usr/bin/env python3\nimport os, pathlib, sys\n"
        "if '--help' in sys.argv:\n"
        "    sys.stderr.write('\\n'.join('-' + value for value in ('eebus-enabled', 'eebus-listen-port', 'eebus-interfaces', 'eebus-subnets', 'eebus-state-root', 'eebus-discovery-enabled', 'eebus-remote-ski-allowlist', 'eebus-pairing-window-mode', 'instance-guid-source', 'semantic-cache-path')) + '\\n')\n"
        "    raise SystemExit(0)\n"
        "pathlib.Path(os.environ['TEST_ARGV']).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    gateway.chmod(gateway.stat().st_mode | stat.S_IXUSR)

    prelude = r'''
bashio::config() {
  case "$1" in
    transport) printf '%s\n' enh ;; network) printf '%s\n' tcp ;;
    address) printf '%s\n' 203.0.113.10:9999 ;; proxy_profile) printf '%s\n' disabled ;;
    host) printf '%s\n' 127.0.0.1 ;; port|http_port) printf '%s\n' 8080 ;;
    path|graphql_path|subscription_path) printf '%s\n' /graphql ;; mcp_path) printf '%s\n' /mcp ;;
    mdns|broadcast|observe_first_enabled|passive_state_direct_apply|eebus_enabled|eebus_discovery_enabled) printf '%s\n' true ;;
    passive_config_direct_apply|enable_static_seed_table|adapter_direct_enabled|modbus_tcp_enabled) printf '%s\n' false ;;
    mdns_instance) printf '%s\n' helianthus ;; source_addr) printf '%s\n' auto ;;
    scan_request_timeout) printf '%s\n' 400ms ;; read_timeout|write_timeout|dial_timeout|modbus_tcp_dial_timeout) printf '%s\n' 5s ;;
    proxy_listen_addr) printf '%s\n' 0.0.0.0:19001 ;; external_write_policy) printf '%s\n' record_only ;;
    v8_classifier_mode) printf '%s\n' enforce ;; eebus_listen_port) printf '%s\n' 4712 ;;
    eebus_interface) printf '%s\n' lo ;; eebus_subnets) printf '%s\n' 192.0.2.0/24 ;;
    eebus_remote_ski_allowlist|adapter_direct_address|modbus_tcp_endpoint) printf '\n' ;;
    *) printf '\n' ;;
  esac
}
bashio::var.true() { case "$1" in true|1|yes|on) return 0 ;; *) return 1 ;; esac; }
bashio::log.info() { printf 'INFO: %s\n' "$*" >> "$TEST_LOG"; }
bashio::log.warning() { printf 'WARN: %s\n' "$*" >> "$TEST_LOG"; }
bashio::log.error() { printf 'ERROR: %s\n' "$*" >> "$TEST_LOG"; }
bashio::exit.nok() { printf 'NOK: %s\n' "$*" >&2; exit 1; }
'''
    text = RUN.read_text(encoding="utf-8")
    text = text.replace("/usr/local/bin/helianthus-gateway", "${TEST_GATEWAY}")
    text = text.replace("/data/helianthus-gateway", "${TEST_OVERRIDE}")
    text = text.replace("/data/source_addr.last", "${TEST_SOURCE_STATE}")
    text = text.replace("/etc/machine-id", "${TEST_MACHINE_ID}")
    text = text.replace('interface_id_path="/sys/class/net/${eebus_interface}/address"', 'interface_id_path="${TEST_INTERFACE_ID_PATH}"')
    text = text.replace('eebus_options_path="/data/options.json"', 'eebus_options_path="${TEST_EEBUS_OPTIONS}"')
    text = text.replace("/usr/share/helianthus/eebus_admin_credentials.py", "${TEST_LEGACY_HELPER}")
    text = text.replace("/run/helianthus/eebus-admin", "${TEST_LEGACY_RUNTIME}")
    wrapper.write_text(prelude + "\n" + text, encoding="utf-8")

    env = os.environ | {
        "TEST_ARGV": str(argv), "TEST_LOG": str(log), "TEST_GATEWAY": str(gateway),
        "TEST_OVERRIDE": str(tmp_path / "missing-override"), "TEST_SOURCE_STATE": str(tmp_path / "source-state"),
        "TEST_LEGACY_HELPER": str(helper), "TEST_LEGACY_RUNTIME": str(runtime),
        "TEST_INTERFACE_ID_PATH": str(interface_id),
        "TEST_MACHINE_ID": str(tmp_path / "machine-id"),
        "TEST_EEBUS_OPTIONS": str(options),
        "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(ROOT / "helianthus/rootfs/usr/share/helianthus/check_runtime_state_wrapper.py"),
        "HELIANTHUS_RUNTIME_STATE_PATH": str(tmp_path / "runtime-state.json"),
        "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(tmp_path / "instance-guid"),
        "HELIANTHUS_MIGRATION_MARKER_PATH": str(tmp_path / "migration-marker"),
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"),
        "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options), "HELIANTHUS_MODBUS_HEALTH_FILE": str(tmp_path / "health"),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(tmp_path / "endpoint"),
    }
    result = subprocess.run(["bash", str(wrapper)], text=True, capture_output=True, env=env, check=False)
    assert result.returncode == 0, result.stderr
    rendered = "\n".join((argv.read_text(encoding="utf-8"), log.read_text(encoding="utf-8"), result.stdout, result.stderr))
    assert "-eebus-enabled=true" in rendered
    assert "-eebus-pairing-window-mode" in rendered
    for term in REMOVED_WRAPPER_TERMS:
        assert term not in rendered
    assert "eeBUS admin" not in rendered

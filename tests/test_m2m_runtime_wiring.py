from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "helianthus/config.json"
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"
VERSION = "0.6.56"
TLS_ROOT = "/ssl/helianthus-pv-m2m"


def test_supervisor_exposes_only_non_secret_m2m_controls_and_read_only_config() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert config["version"] == VERSION
    assert config["map"] == ["ssl:ro"]
    assert "config:ro" not in config["map"]
    assert config["ports"]["8443/tcp"] == 8443
    assert config["options"]["m2m_graphql_enabled"] is False
    assert config["options"]["m2m_graphql_server_name"] == ""
    assert config["options"]["m2m_graphql_asset_ref"] == ""
    assert config["schema"]["m2m_graphql_enabled"] == "bool"
    assert config["schema"]["m2m_graphql_server_name"] == "str"
    assert config["schema"]["m2m_graphql_asset_ref"] == "str"
    assert not any(
        token in key.lower()
        for key in config["options"] | config["schema"]
        for token in ("m2m_ca", "m2m_cert", "m2m_key", "m2m_secret")
    )


def test_wrapper_uses_fixed_tls_files_and_complete_m2m_flag_bundle() -> None:
    run = RUN.read_text(encoding="utf-8")

    fixed_files = (
        "ca.pem",
        "server-cert.pem",
        "server-key.pem",
        "portal-client-cert.pem",
        "portal-client-key.pem",
    )
    assert f'm2m_tls_root="{TLS_ROOT}"' in run
    for name in fixed_files:
        assert f'${{m2m_tls_root}}/{name}' in run
    required_flags = (
        "m2m-graphql-listen",
        "m2m-graphql-server-name",
        "m2m-graphql-client-ca",
        "m2m-graphql-server-cert",
        "m2m-graphql-server-key",
        "m2m-graphql-allowed-assets",
        "m2m-graphql-known-assets",
        "portal-pv-m2m-url",
        "portal-pv-m2m-server-name",
        "portal-pv-m2m-ca",
        "portal-pv-m2m-client-cert",
        "portal-pv-m2m-client-key",
        "portal-pv-asset-ref",
    )
    for flag in required_flags:
        assert f'gateway_supports_flag "{flag}"' in run or flag in run
        assert f'-{flag}' in run
    assert 'gateway_args+=("${m2m_args[@]}")' in run
    assert run.index('gateway_args+=("${m2m_args[@]}")') < run.index(
        'exec "${gateway_bin}" "${gateway_args[@]}"'
    )


def test_m2m_disabled_state_is_inert_and_wrapper_stays_single_process() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert "m2m_graphql_enabled" in run
    assert 'm2m_args=()' in run
    assert 'if bashio::var.true "${m2m_graphql_enabled}"; then' in run
    assert 'bashio::log.info "M2M GraphQL runtime: disabled"' in run
    assert run.count('exec "${gateway_bin}" "${gateway_args[@]}"') == 1
    for forbidden in (
        "m2m_child_pid",
        "m2m_supervisor",
        "m2m_retry",
        "m2m_fallback",
        "m2m_certificate_generator",
    ):
        assert forbidden not in run


def test_m2m_enabled_values_are_type_checked_and_never_logged() -> None:
    run = RUN.read_text(encoding="utf-8")

    assert "m2m_graphql_enabled boolean" in run
    assert "m2m_graphql_server_name string" in run
    assert "m2m_graphql_asset_ref string" in run
    enabled_read = run.index("m2m_graphql_enabled=$(jq -r")
    enabled_gate = run.index('if [ "${m2m_graphql_enabled}" = "true" ]; then', enabled_read)
    string_validation = run.index(
        "m2m_validate_protected_option m2m_graphql_server_name string", enabled_gate
    )
    assert enabled_read < enabled_gate < string_validation
    assert "M2M GraphQL runtime: enabled" in run
    assert "${m2m_graphql_server_name}" not in {
        line for line in run.splitlines() if "bashio::log" in line
    }
    assert "${m2m_graphql_asset_ref}" not in {
        line for line in run.splitlines() if "bashio::log" in line
    }


def test_enabled_wrapper_executes_gateway_with_portal_semantic_switch(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "run-under-test.sh"
    gateway = tmp_path / "gateway.py"
    argv = tmp_path / "argv"
    log = tmp_path / "log"
    options = tmp_path / "options.json"
    tls_root = tmp_path / "tls"
    tls_root.mkdir()
    for name in (
        "ca.pem",
        "server-cert.pem",
        "server-key.pem",
        "portal-client-cert.pem",
        "portal-client-key.pem",
    ):
        (tls_root / name).write_text("fixture\n", encoding="utf-8")
    options.write_text(
        json.dumps(
            {
                "m2m_graphql_enabled": True,
                "m2m_graphql_server_name": "2001:db8::10",
                "m2m_graphql_asset_ref": "pv-asset-fixture",
            }
        ),
        encoding="utf-8",
    )
    flags = (
        "m2m-graphql-listen",
        "m2m-graphql-server-name",
        "m2m-graphql-client-ca",
        "m2m-graphql-server-cert",
        "m2m-graphql-server-key",
        "m2m-graphql-allowed-assets",
        "m2m-graphql-known-assets",
        "portal-pv-semantic-enabled",
        "portal-pv-m2m-url",
        "portal-pv-m2m-server-name",
        "portal-pv-m2m-ca",
        "portal-pv-m2m-client-cert",
        "portal-pv-m2m-client-key",
        "portal-pv-asset-ref",
        "instance-guid-source",
    )
    gateway.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        f"flags = {flags!r}\n"
        "if '--help' in sys.argv:\n"
        "    sys.stderr.write('\\n'.join('-' + value for value in flags) + '\\n')\n"
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
    mdns|broadcast|observe_first_enabled|passive_state_direct_apply) printf '%s\n' true ;;
    passive_config_direct_apply|enable_static_seed_table|adapter_direct_enabled|eebus_enabled|eebus_discovery_enabled|modbus_tcp_enabled) printf '%s\n' false ;;
    mdns_instance) printf '%s\n' helianthus ;; source_addr) printf '%s\n' auto ;;
    scan_request_timeout) printf '%s\n' 400ms ;; read_timeout|write_timeout|dial_timeout|modbus_tcp_dial_timeout) printf '%s\n' 5s ;;
    proxy_listen_addr) printf '%s\n' 0.0.0.0:19001 ;; external_write_policy) printf '%s\n' record_only ;;
    v8_classifier_mode) printf '%s\n' enforce ;;
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
    text = text.replace("/data/options.json", "${TEST_OPTIONS}")
    text = text.replace(TLS_ROOT, "${TEST_TLS_ROOT}")
    wrapper.write_text(prelude + "\n" + text, encoding="utf-8")

    env = os.environ | {
        "TEST_ARGV": str(argv),
        "TEST_LOG": str(log),
        "TEST_GATEWAY": str(gateway),
        "TEST_OVERRIDE": str(tmp_path / "missing-override"),
        "TEST_SOURCE_STATE": str(tmp_path / "source-state"),
        "TEST_OPTIONS": str(options),
        "TEST_TLS_ROOT": str(tls_root),
        "HELIANTHUS_RUNTIME_STATE_WRAPPER": str(
            ROOT / "helianthus/rootfs/usr/share/helianthus/check_runtime_state_wrapper.py"
        ),
        "HELIANTHUS_RUNTIME_STATE_PATH": str(tmp_path / "runtime-state.json"),
        "HELIANTHUS_LEGACY_INSTANCE_GUID_PATH": str(tmp_path / "instance-guid"),
        "HELIANTHUS_MIGRATION_MARKER_PATH": str(tmp_path / "migration-marker"),
        "HELIANTHUS_MODBUS_RUNTIME_GUARD": str(
            ROOT / "helianthus/rootfs/usr/share/helianthus/modbus_runtime_guard.py"
        ),
        "HELIANTHUS_MODBUS_OPTIONS_PATH": str(options),
        "HELIANTHUS_MODBUS_ENDPOINT_FILE": str(tmp_path / "modbus-endpoint"),
    }
    result = subprocess.run(
        ["bash", str(wrapper)], text=True, capture_output=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    executed = argv.read_text(encoding="utf-8").splitlines()
    assert "-portal-pv-semantic-enabled=true" in executed
    assert executed[executed.index("-m2m-graphql-server-name") + 1] == "2001:db8::10"
    assert executed[executed.index("-portal-pv-m2m-server-name") + 1] == "2001:db8::10"
